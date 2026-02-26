#!/usr/bin/env python3
"""
CrowdCount Main Orchestrator
Manages device startup: provisions if no WiFi, streams if connected
"""

import os
import sys
import time
import subprocess
import signal
import configparser
import hashlib
import hmac as hmac_mod
import json
import logging
import uuid
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent / 'src' / 'provisioning'))
from logging_config import setup_logging

# Setup logging
logger = setup_logging('crowdcount-main')

# Paths
SCRIPT_DIR = Path(__file__).parent
PROVISIONING_DIR = SCRIPT_DIR / "src" / "provisioning"
STREAM_DIR = SCRIPT_DIR / "src" / "counter-stream"

PROVISIONED_FLAGS = [
    Path("/boot/firmware/provisioned"),
    Path("/boot/provisioned")
]

DEVICE_CONFIG = STREAM_DIR / "device-info.conf"

# Device identity file locations
IDENTITY_PATHS = [
    Path('/boot/firmware/device-identity.conf'),
    Path('/boot/device-identity.conf'),
]

# Marker file: once SSH is hardened, don't repeat on every boot
SSH_HARDENED_MARKER = Path('/boot/firmware/.ssh-hardened')


class CrowdCountMain:
    """Main orchestrator for CrowdCount device"""

    def __init__(self):
        self.running = True
        self.current_process = None
        self.device_id = None
        self.api_password = None
        self.tailscale_auth_key = None
        self._load_config()

    def _load_config(self):
        """Load device identity and configuration"""
        # Load device identity (for DEVICE_ID and API_PASSWORD)
        for identity_path in IDENTITY_PATHS:
            if identity_path.exists():
                try:
                    config = configparser.ConfigParser()
                    config.read(identity_path)
                    section = config['DEFAULT'] if 'DEFAULT' in config else config[config.sections()[0]]
                    self.device_id = section.get('DEVICE_ID', None)
                    # Also read API password for version reporting
                    self.api_password = section.get('API_PASSWORD', None) or None
                    if self.device_id:
                        print(f"✓ Loaded device identity: {self.device_id} from {identity_path}")
                        break
                except Exception as e:
                    print(f"⚠ Error reading {identity_path}: {e}")

        # Fallback: read API_PASSWORD directly from identity file if configparser missed it
        if self.device_id and not self.api_password:
            for identity_path in IDENTITY_PATHS:
                if identity_path.exists():
                    try:
                        with open(identity_path) as f:
                            for line in f:
                                line = line.strip()
                                if line.startswith('API_PASSWORD='):
                                    val = line.split('=', 1)[1].strip()
                                    if val:
                                        self.api_password = val
                                        break
                        if self.api_password:
                            break
                    except Exception:
                        pass

        # Load device config (for Tailscale auth key)
        if DEVICE_CONFIG.exists():
            try:
                # Read raw file (it's in KEY=VALUE format, not INI)
                with open(DEVICE_CONFIG) as f:
                    for line in f:
                        if line.startswith('TAILSCALE_AUTH_KEY='):
                            self.tailscale_auth_key = line.split('=', 1)[1].strip()
                            if self.tailscale_auth_key:
                                print(f"✓ Loaded Tailscale auth key")
                            break
            except Exception as e:
                print(f"⚠ Error reading device config: {e}")

    def _sign_request(self, method, url, body):
        """Compute HMAC-SHA256 signature headers for API requests."""
        if not self.api_password or not self.device_id:
            return {}
        from urllib.parse import urlparse
        signing_key = hashlib.sha256(f"{self.device_id}:{self.api_password}".encode()).digest()
        path = urlparse(url).path
        timestamp = str(int(time.time()))
        nonce = str(uuid.uuid4())
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        string_to_sign = f"{method}\n{path}\n{body_hash}\n{timestamp}\n{nonce}"
        signature = hmac_mod.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        return {
            'X-CC-Signature': signature,
            'X-CC-Timestamp': timestamp,
            'X-CC-Nonce': nonce,
            'X-CC-Device-Id': self.device_id,
            'X-CC-Sig-Version': '1',
        }

    def _get_current_commit(self):
        """Return the current HEAD commit hash by reading .git directly."""
        try:
            git_dir = SCRIPT_DIR / '.git'
            head_file = git_dir / 'HEAD'
            head = head_file.read_text().strip()
            if head.startswith('ref: '):
                # HEAD is a symbolic ref like "ref: refs/heads/main"
                ref_path = git_dir / head[5:]
                return ref_path.read_text().strip()
            # Detached HEAD — already a commit hash
            return head
        except Exception as e:
            print(f"⚠ Could not read git commit: {e}")
            return None

    def report_version(self):
        """Report the current git commit hash to the API server."""
        if not self.device_id:
            print("⚠ Skipping version report: no device_id")
            return
        if not self.api_password:
            print("⚠ Skipping version report: no API_PASSWORD in device-identity.conf")
            return
        commit = self._get_current_commit()
        if not commit:
            print("⚠ Skipping version report: could not get git commit hash")
            return
        try:
            import requests
            url = "https://api.crowdcount.tech/report_version"
            payload = json.dumps({
                "device_id": self.device_id,
                "password": self.api_password,
                "commit_hash": commit,
            })
            headers = {
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid.uuid4()),
            }
            headers.update(self._sign_request("POST", url, payload))
            resp = requests.post(url, data=payload, headers=headers, timeout=30)
            if resp.ok:
                print(f"✓ Reported version {commit[:8]} to server")
            else:
                print(f"⚠ Version report failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"⚠ Could not report version: {e}")

    def ensure_tailscaled_running(self):
        """Make sure the tailscaled daemon is running, restart it if needed."""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', 'tailscaled'],
                capture_output=True, timeout=5, text=True
            )
            if result.stdout.strip() == 'active':
                return True

            print("⚠ tailscaled is not running, attempting restart...")
            subprocess.run(
                ['sudo', 'systemctl', 'restart', 'tailscaled'],
                capture_output=True, timeout=15
            )
            time.sleep(2)

            result = subprocess.run(
                ['systemctl', 'is-active', 'tailscaled'],
                capture_output=True, timeout=5, text=True
            )
            if result.stdout.strip() == 'active':
                print("✓ tailscaled restarted successfully")
                return True
            else:
                print("✗ tailscaled failed to restart")
                return False
        except Exception as e:
            print(f"✗ Error checking tailscaled: {e}")
            return False

    def authenticate_tailscale(self):
        """Authenticate Tailscale with auth key and device hostname"""
        if not self.tailscale_auth_key:
            print("⚠ No Tailscale auth key configured, skipping authentication")
            return False

        # Make sure the daemon is running first
        if not self.ensure_tailscaled_running():
            print("⚠ Cannot authenticate — tailscaled is not running")
            return False

        try:
            # Check if already authenticated
            result = subprocess.run(
                ['tailscale', 'status'],
                capture_output=True,
                timeout=5,
                text=True
            )

            # If already authenticated and running, skip
            if result.returncode == 0 and 'logged out' not in result.stdout.lower():
                print("✓ Tailscale already authenticated")
                return True

            # Authenticate with hostname
            hostname = self.device_id if self.device_id else "crowdcount-counter"
            print(f"Authenticating Tailscale with hostname: {hostname}")

            cmd = ['tailscale', 'up', f'--authkey={self.tailscale_auth_key}', f'--hostname={hostname}']
            result = subprocess.run(cmd, capture_output=True, timeout=30, text=True)

            if result.returncode == 0:
                print(f"✓ Tailscale authenticated as {hostname}")
                return True
            else:
                print(f"✗ Tailscale authentication failed: {result.stderr}")
                return False

        except Exception as e:
            print(f"✗ Error authenticating Tailscale: {e}")
            return False

    def harden_ssh(self):
        """Disable regular SSH after confirming Tailscale SSH works.

        Only runs once (uses marker file). If Tailscale auth failed,
        this method should not be called — regular SSH stays as fallback.
        """
        if SSH_HARDENED_MARKER.exists():
            return  # Already hardened on a previous boot

        try:
            # Enable Tailscale SSH
            result = subprocess.run(
                ['sudo', 'tailscale', 'set', '--ssh'],
                capture_output=True, timeout=10, text=True
            )
            if result.returncode != 0:
                print(f"⚠ Failed to enable Tailscale SSH, keeping regular SSH: {result.stderr}")
                return

            print("✓ Tailscale SSH enabled")

            # Disable regular SSH
            for cmd in [
                ['sudo', 'systemctl', 'stop', 'ssh'],
                ['sudo', 'systemctl', 'disable', 'ssh'],
                ['sudo', 'systemctl', 'mask', 'ssh'],
            ]:
                subprocess.run(cmd, capture_output=True, timeout=10)

            print("✓ Regular SSH disabled — only Tailscale SSH available")

            # Write marker so we don't repeat this on every boot
            try:
                SSH_HARDENED_MARKER.write_text(
                    f"SSH hardened on {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
            except PermissionError:
                subprocess.run(
                    ['sudo', 'bash', '-c', f'echo "SSH hardened on $(date)" > {SSH_HARDENED_MARKER}'],
                    capture_output=True, timeout=5
                )

            print(f"✓ Marker written: {SSH_HARDENED_MARKER}")

        except Exception as e:
            print(f"⚠ SSH hardening failed (regular SSH still available): {e}")

    def check_wifi_connected(self):
        """Check if WiFi is currently connected using multiple methods"""
        # Method 1: Try NetworkManager (most reliable on modern systems)
        try:
            result = subprocess.run(
                ['nmcli', '-t', '-f', 'STATE', 'general'],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0:
                state = result.stdout.strip()
                if state in ['connected', 'connected (site only)', 'connected (local only)']:
                    # Verify WiFi specifically is connected (not just Tailscale/loopback)
                    try:
                        ssid_result = subprocess.run(
                            ['nmcli', '-t', '-f', 'active,ssid', 'dev', 'wifi'],
                            capture_output=True,
                            timeout=5,
                            text=True
                        )
                        for line in ssid_result.stdout.strip().split('\n'):
                            if line.startswith('yes:'):
                                ssid = line.split(':', 1)[1]
                                return True, ssid if ssid else "unknown"
                    except Exception:
                        pass
                    # nmcli says connected but no active WiFi — Tailscale or other non-WiFi connection
        except FileNotFoundError:
            pass  # nmcli not available, try next method
        except Exception:
            pass

        # Method 2: Try iwgetid (classic method)
        try:
            result = subprocess.run(
                ['iwgetid'],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                # Get SSID for display
                try:
                    ssid = subprocess.run(
                        ['iwgetid', '-r'],
                        capture_output=True,
                        timeout=5,
                        text=True
                    ).stdout.strip()
                    return True, ssid if ssid else "unknown"
                except Exception:
                    return True, "unknown"
        except FileNotFoundError:
            pass  # iwgetid not available, try next method
        except Exception:
            pass

        # Method 3: Check default route on wlan0 (not tailscale/lo)
        try:
            result = subprocess.run(
                ['ip', 'route', 'show', 'default', 'dev', 'wlan0'],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                ssid = self._get_ssid_from_wpa()
                return True, ssid if ssid else "unknown"
        except Exception:
            pass

        # Method 4: Check wpa_supplicant status
        try:
            result = subprocess.run(
                ['wpa_cli', 'status'],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('wpa_state='):
                        state = line.split('=', 1)[1]
                        if state == 'COMPLETED':
                            ssid = self._get_ssid_from_wpa()
                            return True, ssid if ssid else "unknown"
        except FileNotFoundError:
            pass
        except Exception:
            pass

        # All methods failed
        return False, None

    def _get_ssid_from_wpa(self):
        """Get SSID from wpa_supplicant"""
        try:
            result = subprocess.run(
                ['wpa_cli', 'status'],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('ssid='):
                        return line.split('=', 1)[1]
        except Exception:
            pass
        return None

    def is_provisioned(self):
        """Check if device has been provisioned"""
        return any(flag.exists() for flag in PROVISIONED_FLAGS)

    def has_device_config(self):
        """Check if device configuration exists"""
        return DEVICE_CONFIG.exists()

    def try_saved_wifi(self, max_attempts=3, retry_delay=5):
        """Try to connect to saved WiFi credentials before provisioning,
        then fallback networks.

        Args:
            max_attempts: Number of connection attempts per network
            retry_delay: Seconds between attempts

        Returns:
            bool: True if connected successfully
        """
        FALLBACK_NETWORKS = [
            ("Elkan's iPhone", "CrowdCountHotspot"),
        ]

        # Check for saved WiFi credentials
        credential_locations = [
            Path('/boot/firmware/wifi-credentials.conf'),
            Path('/boot/wifi-credentials.conf'),
            Path.home() / '.config' / 'crowdcount' / 'wifi-credentials.conf',
        ]

        saved_ssid = None
        saved_password = None

        for config_file in credential_locations:
            if config_file.exists():
                try:
                    with open(config_file, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith('WIFI_SSID='):
                                saved_ssid = line.split('=', 1)[1]
                            elif line.startswith('WIFI_PASSWORD='):
                                saved_password = line.split('=', 1)[1]

                    if saved_ssid and saved_password:
                        print(f"✓ Found saved WiFi credentials for: {saved_ssid}")
                        break
                except Exception as e:
                    print(f"⚠ Error reading {config_file}: {e}")
                    continue

        # Build list of networks: saved first, then fallbacks
        networks = []
        if saved_ssid and saved_password:
            networks.append((saved_ssid, saved_password))
        for fb_ssid, fb_pass in FALLBACK_NETWORKS:
            if fb_ssid != saved_ssid:
                networks.append((fb_ssid, fb_pass))

        if not networks:
            print("No saved or fallback WiFi credentials found")
            return False

        for ssid, password in networks:
            print(f"📡 Attempting to connect to WiFi: {ssid}")

            for attempt in range(1, max_attempts + 1):
                print(f"  Attempt {attempt}/{max_attempts}...")

                try:
                    # First check if already connected
                    wifi_connected, current_ssid = self.check_wifi_connected()
                    if wifi_connected:
                        print(f"✓ Already connected to WiFi: {current_ssid}")
                        return True

                    # Turn on WiFi radio if off
                    subprocess.run(
                        ['sudo', 'nmcli', 'radio', 'wifi', 'on'],
                        capture_output=True,
                        timeout=10
                    )
                    time.sleep(2)

                    # Try to connect
                    result = subprocess.run(
                        ['sudo', 'nmcli', 'dev', 'wifi', 'connect', ssid,
                         'password', password],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )

                    if result.returncode == 0:
                        print(f"✓ Connected to WiFi: {ssid}")
                        return True
                    else:
                        error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                        print(f"  Connection failed: {error_msg}")

                except subprocess.TimeoutExpired:
                    print(f"  Connection attempt timed out")
                except Exception as e:
                    print(f"  Error: {e}")

                if attempt < max_attempts:
                    print(f"  Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)

            print(f"✗ Failed to connect to {ssid} after {max_attempts} attempts")

        print(f"✗ Failed to connect to any WiFi network")
        return False

    def check_tailscale_connected(self):
        """Check if Tailscale is running and connected"""
        try:
            result = subprocess.run(
                ['tailscale', 'status', '--json'],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0:
                import json
                status = json.loads(result.stdout)
                # Check if we have a valid backend state
                backend_state = status.get('BackendState', '')
                if backend_state == 'Running':
                    # Get our Tailscale IP
                    self_peer = status.get('Self', {})
                    tailscale_ips = self_peer.get('TailscaleIPs', [])
                    if tailscale_ips:
                        return True, tailscale_ips[0]
                return False, None
        except Exception as e:
            print(f"⚠ Error checking Tailscale: {e}")
            return False, None

    def run_provisioning(self):
        """Run the provisioning process (waits indefinitely for connection)"""
        print("\n" + "="*60)
        print("STARTING PROVISIONING MODE")
        print("="*60)
        print("Device is not connected to WiFi")
        print("Starting Bluetooth provisioning...")
        print("Waiting for user to provision via mobile app...")
        print("="*60 + "\n")

        provision_script = PROVISIONING_DIR / "provision_manager.py"

        try:
            # Run provisioning as a subprocess
            self.current_process = subprocess.Popen(
                [sys.executable, str(provision_script)],
                cwd=str(PROVISIONING_DIR)
            )

            # Wait for provisioning to complete
            return_code = self.current_process.wait()

            if return_code == 0:
                print("\n✓ Provisioning completed successfully")
                return True
            else:
                print(f"\n⚠ Provisioning exited with code {return_code}")
                return False

        except Exception as e:
            print(f"\n✗ Error running provisioning: {e}")
            return False
        finally:
            if self.current_process:
                try:
                    self.current_process.kill()
                    self.current_process.wait(timeout=5)
                except Exception:
                    pass
            self.current_process = None

    def run_streaming(self):
        """Run the streaming process"""
        print("\n" + "="*60)
        print("STARTING STREAMING MODE")
        print("="*60)
        print("Device is connected and provisioned")
        print("Starting camera stream...")
        print("="*60 + "\n")

        stream_script = STREAM_DIR / "start_stream.sh"

        try:
            # Run streaming as a subprocess
            self.current_process = subprocess.Popen(
                ['/bin/bash', str(stream_script)],
                cwd=str(STREAM_DIR)
            )

            # Wait for streaming to complete (runs indefinitely)
            return_code = self.current_process.wait()

            if return_code == 0:
                print("\n✓ Streaming stopped normally")
                return True
            else:
                print(f"\n⚠ Streaming exited with code {return_code}")
                return False

        except Exception as e:
            print(f"\n✗ Error running streaming: {e}")
            return False
        finally:
            if self.current_process:
                try:
                    self.current_process.kill()
                    self.current_process.wait(timeout=5)
                except Exception:
                    pass
            self.current_process = None

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(sig, frame):
            print("\n⚠ Received shutdown signal")
            self.running = False

            proc = self.current_process
            if proc:
                print("Stopping current process...")
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                        proc.wait(timeout=3)
                    except Exception:
                        pass
                except Exception:
                    pass

            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def run(self):
        """Main orchestration loop"""
        self.setup_signal_handlers()

        print("\n" + "="*60)
        print("CROWDCOUNT DEVICE STARTUP")
        print("="*60)
        print(f"Working Directory: {SCRIPT_DIR}")
        if self.device_id:
            print(f"Device ID: {self.device_id}")
        print("="*60 + "\n")

        # Authenticate Tailscale on startup (if not already authenticated)
        print("Checking Tailscale authentication...")
        tailscale_ok = self.authenticate_tailscale()

        # Harden SSH only after Tailscale auth is confirmed working on THIS device.
        # If Tailscale auth fails, regular SSH stays enabled as fallback access.
        if tailscale_ok:
            self.harden_ssh()
        else:
            print("⚠ Tailscale not authenticated — keeping regular SSH enabled as fallback")
        print()

        version_reported = False

        # Main decision loop
        while self.running:
            # Check WiFi status
            wifi_connected, ssid = self.check_wifi_connected()
            is_provisioned = self.is_provisioned()
            has_config = self.has_device_config()
            tailscale_connected, tailscale_ip = self.check_tailscale_connected()

            print(f"Status Check:")
            print(f"  WiFi Connected: {wifi_connected} {f'({ssid})' if ssid else ''}")
            print(f"  Tailscale: {tailscale_connected} {f'({tailscale_ip})' if tailscale_ip else ''}")
            print(f"  Provisioned: {is_provisioned}")
            print(f"  Config Exists: {has_config}")
            print()

            # Decision logic
            if not wifi_connected:
                # No WiFi → try saved credentials first, then provision
                print("Decision: WiFi not connected")
                print()

                # First, try to connect using saved WiFi credentials
                print("Trying saved WiFi credentials...")
                if self.try_saved_wifi(max_attempts=3, retry_delay=5):
                    # Successfully connected to saved WiFi
                    print("\n✓ Connected using saved WiFi credentials")
                    print("Rechecking status...")
                    time.sleep(2)
                    continue

                # Saved WiFi failed or no credentials - start provisioning
                print("\nSaved WiFi connection failed or no credentials found")
                print("Starting Bluetooth provisioning...")
                success = self.run_provisioning()

                if success:
                    # After provisioning, recheck and potentially start streaming
                    print("\nRechecking status after provisioning...")
                    time.sleep(2)
                    continue
                else:
                    # Provisioning failed, wait and retry
                    print("\nProvisioning failed. Retrying in 30 seconds...")
                    time.sleep(30)
                    continue

            elif wifi_connected and is_provisioned and has_config:
                # Connected and ready → check Tailscale, then stream
                if not tailscale_connected:
                    print("Decision: WiFi connected but Tailscale not ready")
                    print("Waiting for Tailscale to connect...")
                    time.sleep(5)
                    continue

                if not version_reported:
                    self.report_version()
                    version_reported = True

                print("Decision: Starting streaming")
                success = self.run_streaming()

                if not success:
                    # Streaming failed, wait and retry
                    print("\nStreaming failed. Retrying in 10 seconds...")
                    time.sleep(10)
                    continue
                else:
                    # Streaming stopped normally (shouldn't happen)
                    print("\nStreaming stopped. Restarting in 10 seconds...")
                    time.sleep(10)
                    continue

            else:
                # Connected but not fully provisioned
                print("Decision: WiFi connected but device not fully provisioned")
                print("Starting provisioning to complete setup...")
                success = self.run_provisioning()

                if success:
                    print("\nSetup complete. Rechecking status...")
                    time.sleep(2)
                    continue
                else:
                    print("\nSetup failed. Retrying in 30 seconds...")
                    time.sleep(30)
                    continue


def main():
    """Entry point"""
    main_orchestrator = CrowdCountMain()
    main_orchestrator.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
