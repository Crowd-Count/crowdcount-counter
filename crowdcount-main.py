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
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
PROVISIONING_DIR = SCRIPT_DIR / "src" / "provisioning"
STREAM_DIR = SCRIPT_DIR / "src" / "counter-stream"

PROVISIONED_FLAGS = [
    Path("/boot/firmware/provisioned"),
    Path("/boot/provisioned")
]

DEVICE_CONFIG = STREAM_DIR / "device-info.conf"


class CrowdCountMain:
    """Main orchestrator for CrowdCount device"""

    def __init__(self):
        self.running = True
        self.current_process = None

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
                    # Get SSID from NetworkManager
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
                    except:
                        pass
                    return True, "unknown"
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
                except:
                    return True, "unknown"
        except FileNotFoundError:
            pass  # iwgetid not available, try next method
        except Exception:
            pass

        # Method 3: Check default route (indicates internet connectivity)
        try:
            result = subprocess.run(
                ['ip', 'route', 'show', 'default'],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                # Has default route - likely connected
                # Try to get WiFi info
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
        except:
            pass
        return None

    def is_provisioned(self):
        """Check if device has been provisioned"""
        return any(flag.exists() for flag in PROVISIONED_FLAGS)

    def has_device_config(self):
        """Check if device configuration exists"""
        return DEVICE_CONFIG.exists()

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
        """Run the provisioning process"""
        print("\n" + "="*60)
        print("STARTING PROVISIONING MODE")
        print("="*60)
        print("Device is not connected to WiFi")
        print("Starting Bluetooth provisioning...")
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
            self.current_process = None

            if return_code == 0:
                print("\n✓ Provisioning completed successfully")
                return True
            else:
                print(f"\n⚠ Provisioning exited with code {return_code}")
                return False

        except Exception as e:
            print(f"\n✗ Error running provisioning: {e}")
            self.current_process = None
            return False

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
            self.current_process = None

            if return_code == 0:
                print("\n✓ Streaming stopped normally")
                return True
            else:
                print(f"\n⚠ Streaming exited with code {return_code}")
                return False

        except Exception as e:
            print(f"\n✗ Error running streaming: {e}")
            self.current_process = None
            return False

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(sig, frame):
            print("\n⚠ Received shutdown signal")
            self.running = False

            if self.current_process:
                print("Stopping current process...")
                try:
                    self.current_process.terminate()
                    self.current_process.wait(timeout=5)
                except:
                    self.current_process.kill()

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
        print("="*60 + "\n")

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
                # No WiFi → provision
                print("Decision: Device needs provisioning (no WiFi)")
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
