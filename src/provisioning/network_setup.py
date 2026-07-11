#!/usr/bin/env python3
"""
Network Setup Manager
Handles WiFi and Tailscale configuration
"""

import subprocess
import time
import os
import requests
from pathlib import Path

# Import video config
try:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from video_config import VIDEO_FPS, VIDEO_WIDTH, VIDEO_HEIGHT
except ImportError:
    # Fallback defaults if config not found
    VIDEO_FPS = 15
    VIDEO_WIDTH = 640
    VIDEO_HEIGHT = 480


FALLBACK_NETWORKS = []


class NetworkSetup:
    """Manages WiFi and Tailscale network configuration"""

    def __init__(self, device_id):
        self.device_id = device_id
        self.wifi_connected = False
        self.tailscale_connected = False

    def _sanitize_ssid(self, ssid: str) -> bool:
        """Validate SSID format.

        Returns:
            True if SSID is valid, False otherwise
        """
        if not ssid or not isinstance(ssid, str):
            return False

        # WiFi SSIDs are max 32 bytes
        if len(ssid.encode("utf-8")) > 32:
            return False

        return True

    def _sanitize_password(self, password: str) -> bool:
        """Validate WiFi password format.

        Returns:
            True if password is valid, False otherwise
        """
        if not password or not isinstance(password, str):
            return False

        if len(password) > 256:
            return False

        return True

    def _validate_tailscale_key(self, auth_key: str) -> bool:
        """Validate Tailscale auth key format.

        Returns:
            True if key appears valid, False otherwise
        """
        if not auth_key or not isinstance(auth_key, str):
            return False

        # Tailscale auth keys start with 'tskey-auth-' or 'tskey-'
        if not (auth_key.startswith("tskey-auth-") or auth_key.startswith("tskey-")):
            print("Warning: Auth key doesn't match expected Tailscale format")
            return False

        # Check reasonable length (Tailscale keys are typically 40-60+ chars)
        if len(auth_key) < 20 or len(auth_key) > 200:
            print(f"Warning: Auth key length ({len(auth_key)}) seems unusual")
            return False

        return True

    def _validate_ip_address(self, ip: str) -> bool:
        """Validate IP address format.

        Returns:
            True if IP is valid, False otherwise
        """
        if not ip or not isinstance(ip, str):
            return False

        # Basic IPv4 validation
        parts = ip.split(".")
        if len(parts) != 4:
            return False

        try:
            for part in parts:
                num = int(part)
                if num < 0 or num > 255:
                    return False
        except ValueError:
            return False

        return True

    def configure_wifi(self, ssid, password):
        """
        Connect to WiFi network using NetworkManager (nmcli)

        Args:
            ssid: WiFi network name
            password: WiFi password

        Returns:
            bool: True if connection successful
        """
        print(f"📡 Configuring WiFi: {ssid}")

        # SECURITY: Validate inputs to prevent command injection
        if not self._sanitize_ssid(ssid):
            print("✗ Invalid SSID format or contains dangerous characters")
            return False

        if not self._sanitize_password(password):
            print("✗ Invalid password format or contains dangerous characters")
            return False

        try:
            # Turn WiFi off and on to ensure clean state
            try:
                subprocess.run(
                    ["sudo", "nmcli", "radio", "wifi", "off"],
                    capture_output=True,
                    timeout=10,
                )
                time.sleep(2)
            finally:
                subprocess.run(
                    ["sudo", "nmcli", "radio", "wifi", "on"],
                    capture_output=True,
                    timeout=10,
                )

            # Wait for WiFi radio to come up and scan for networks
            # Pi Zero 2W can be slow to scan - wait until we see the target SSID
            print(f"  Waiting for WiFi scan to find '{ssid}'...")
            scan_timeout = 15  # seconds
            scan_start = time.time()
            network_found = False
            while time.time() - scan_start < scan_timeout:
                try:
                    scan_result = subprocess.run(
                        ["sudo", "nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if ssid in scan_result.stdout:
                        network_found = True
                        print(
                            f"  ✓ Network '{ssid}' found after {time.time() - scan_start:.0f}s"
                        )
                        break
                except Exception:
                    pass
                time.sleep(2)

            if not network_found:
                # Force a rescan and try once more
                print("  Network not found in scan, forcing rescan...")
                subprocess.run(
                    ["sudo", "nmcli", "dev", "wifi", "rescan"],
                    capture_output=True,
                    timeout=5,
                )
                time.sleep(5)

            # Delete any existing connection profiles for this SSID to avoid
            # duplicates (MyNetwork, MyNetwork-1, MyNetwork-2, etc.)
            subprocess.run(
                ["sudo", "nmcli", "connection", "delete", ssid],
                capture_output=True,
                timeout=10,
            )  # Ignore errors if none exist

            # Connect to network
            result = subprocess.run(
                ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", password],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                # Verify we actually have connectivity (IP address assigned)
                print("  nmcli reports connected, verifying connectivity...")
                verify_timeout = 15  # seconds
                verify_start = time.time()
                while time.time() - verify_start < verify_timeout:
                    try:
                        ip_result = subprocess.run(
                            ["ip", "-4", "addr", "show", "wlan0"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        if "inet " in ip_result.stdout:
                            print(f"✓ Connected to WiFi: {ssid} (IP assigned)")
                            self.wifi_connected = True
                            self._save_wifi_config(ssid, password)
                            return True
                    except Exception:
                        pass
                    time.sleep(2)

                # nmcli said success but no IP - might still be connecting
                print("⚠ Connected but no IP yet, assuming success")
                self.wifi_connected = True
                self._save_wifi_config(ssid, password)
                return True
            else:
                print(f"✗ WiFi connection failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired as e:
            print(f"✗ WiFi configuration timed out during: {e.cmd}")
            return False
        except Exception as e:
            print(f"✗ WiFi configuration error: {e}")
            return False

    def configure_tailscale(self, auth_key, hostname=None):
        """
        Join Tailscale network using auth key

        Args:
            auth_key: Tailscale authentication key
            hostname: Optional hostname (defaults to device_id)

        Returns:
            bool: True if connection successful
        """
        if not hostname:
            hostname = self.device_id.lower().replace("_", "-")

        print(f"🔐 Joining Tailscale network as {hostname}")

        # Validate auth key format
        if not self._validate_tailscale_key(auth_key):
            print("✗ Invalid Tailscale auth key format")
            return False

        try:
            # Check if Tailscale is installed
            subprocess.run(["which", "tailscale"], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            print("✗ Tailscale not installed. Run setup_pi.sh first.")
            return False

        try:
            # Join Tailscale network
            result = subprocess.run(
                [
                    "sudo",
                    "tailscale",
                    "up",
                    "--authkey",
                    auth_key,
                    "--hostname",
                    hostname,
                    "--accept-routes",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                print("✓ Joined Tailscale network")

                # Get Tailscale IP
                time.sleep(3)
                tailscale_ip = self._get_tailscale_ip()
                if tailscale_ip:
                    print(f"  Tailscale IP: {tailscale_ip}")
                    self.tailscale_connected = True
                    return True
                else:
                    print("⚠ Tailscale connected but couldn't get IP")
                    return True
            else:
                print(f"✗ Tailscale connection failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print("✗ Tailscale connection timed out")
            return False
        except Exception as e:
            print(f"✗ Tailscale configuration error: {e}")
            return False

    def _get_tailscale_ip(self):
        """Get the Tailscale IP address"""
        try:
            result = subprocess.run(
                ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _save_wifi_config(self, ssid, password):
        """Save WiFi configuration for future reconnection on boot"""
        # Save to boot partition (survives reflash) - primary location
        boot_locations = [
            Path("/boot/firmware/wifi-credentials.conf"),
            Path("/boot/wifi-credentials.conf"),
        ]

        saved = False
        for config_file in boot_locations:
            try:
                config_dir = config_file.parent
                if config_dir.exists():
                    with open(config_file, "w") as f:
                        f.write("# CrowdCount WiFi Credentials\n")
                        f.write(
                            f"# Auto-saved on {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        )
                        f.write(f"WIFI_SSID={ssid}\n")
                        f.write(f"WIFI_PASSWORD={password}\n")
                    # Restrict permissions (root only)
                    os.chmod(config_file, 0o600)
                    print(f"  ✓ WiFi credentials saved to {config_file}")
                    saved = True
                    break
            except Exception as e:
                print(f"  ⚠ Could not save to {config_file}: {e}")
                continue

        if not saved:
            # Fallback to user config directory
            config_dir = Path.home() / ".config" / "crowdcount"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / "wifi-credentials.conf"
            try:
                with open(config_file, "w") as f:
                    f.write("# CrowdCount WiFi Credentials\n")
                    f.write(f"WIFI_SSID={ssid}\n")
                    f.write(f"WIFI_PASSWORD={password}\n")
                os.chmod(config_file, 0o600)
                print(f"  ✓ WiFi credentials saved to {config_file}")
            except Exception as e:
                print(f"  ⚠ Could not save WiFi credentials: {e}")

    @staticmethod
    def get_saved_wifi_credentials():
        """Load saved WiFi credentials from persistent storage

        Returns:
            tuple: (ssid, password) or (None, None) if not found
        """
        # Check locations in priority order
        credential_locations = [
            Path("/boot/firmware/wifi-credentials.conf"),
            Path("/boot/wifi-credentials.conf"),
            Path.home() / ".config" / "crowdcount" / "wifi-credentials.conf",
        ]

        for config_file in credential_locations:
            if config_file.exists():
                try:
                    ssid = None
                    password = None
                    with open(config_file, "r") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("WIFI_SSID="):
                                ssid = line.split("=", 1)[1]
                            elif line.startswith("WIFI_PASSWORD="):
                                password = line.split("=", 1)[1]

                    if ssid and password:
                        print(f"✓ Found saved WiFi credentials for: {ssid}")
                        return ssid, password
                except Exception as e:
                    print(f"⚠ Error reading {config_file}: {e}")
                    continue

        return None, None

    def try_saved_wifi(self, max_attempts=3, retry_delay=5):
        """Try to connect to saved WiFi credentials, then fallback networks

        Args:
            max_attempts: Number of connection attempts per network
            retry_delay: Seconds between attempts

        Returns:
            bool: True if connected successfully
        """
        # Build list of networks to try: saved credentials first, then fallbacks
        networks = []
        ssid, password = self.get_saved_wifi_credentials()
        if ssid and password:
            networks.append((ssid, password))
        for fb_ssid, fb_pass in FALLBACK_NETWORKS:
            if fb_ssid != ssid:  # Don't retry saved network
                networks.append((fb_ssid, fb_pass))

        if not networks:
            print("No saved or fallback WiFi credentials found")
            return False

        for net_ssid, net_password in networks:
            print(f"📡 Attempting to connect to WiFi: {net_ssid}")

            for attempt in range(1, max_attempts + 1):
                print(f"  Attempt {attempt}/{max_attempts}...")

                try:
                    # First check if already connected to this network
                    result = subprocess.run(
                        ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        for line in result.stdout.strip().split("\n"):
                            if line.startswith("yes:") and net_ssid in line:
                                print(f"✓ Already connected to {net_ssid}")
                                self.wifi_connected = True
                                return True

                    # Try to connect
                    result = subprocess.run(
                        [
                            "sudo",
                            "nmcli",
                            "dev",
                            "wifi",
                            "connect",
                            net_ssid,
                            "password",
                            net_password,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                    if result.returncode == 0:
                        print(f"✓ Connected to WiFi: {net_ssid}")
                        self.wifi_connected = True
                        return True
                    else:
                        print(f"  Connection failed: {result.stderr.strip()}")

                except subprocess.TimeoutExpired:
                    print("  Connection attempt timed out")
                except Exception as e:
                    print(f"  Error: {e}")

                if attempt < max_attempts:
                    print(f"  Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)

            print(f"✗ Failed to connect to {net_ssid} after {max_attempts} attempts")

        print("✗ Failed to connect to any WiFi network")
        return False

    def write_device_config(self, server_ip, stream_name=None, tailscale_auth_key=None):
        """
        Write device-info.conf for streaming service

        Args:
            server_ip: MediaMTX server IP (Tailscale IP)
            stream_name: Optional stream name (defaults to device_id)
            tailscale_auth_key: Optional Tailscale auth key for re-authentication

        Returns:
            Path to config file or None on error
        """
        if not stream_name:
            stream_name = self.device_id

        # Validate server IP
        if not self._validate_ip_address(server_ip):
            print(f"✗ Invalid server IP address: {server_ip}")
            return None

        # Find the counter-stream directory
        script_dir = Path(__file__).parent.parent / "counter-stream"
        config_file = script_dir / "device-info.conf"

        print(f"📝 Writing device configuration to {config_file}")

        config_content = f"""# Device Configuration File
# Auto-generated by provisioning system on {time.strftime("%Y-%m-%d %H:%M:%S")}

# Unique identifier for this device/camera (used as stream name)
DEVICE_ID={stream_name}

# MediaMTX server Tailscale IP address
SERVER_IP={server_ip}

# RTSP port (default: 8554)
RTSP_PORT=8554

# Video settings
WIDTH={VIDEO_WIDTH}
HEIGHT={VIDEO_HEIGHT}
FPS={VIDEO_FPS}

# CrowdCount API URL
API_URL=https://api.crowdcount.tech

# Tailscale auth key (for re-authentication if needed)
TAILSCALE_AUTH_KEY={tailscale_auth_key or ""}
"""

        with open(config_file, "w") as f:
            f.write(config_content)

        print("✓ Device configuration written")
        return config_file

    def register_with_server(self, server_ip, stream_name, password=""):
        """
        Register device with MediaMTX server

        Args:
            server_ip: Server IP address
            stream_name: Stream name
            password: Optional password

        Returns:
            bool: True if registration successful
        """
        url = f"http://{server_ip}:5000/device/register"

        payload = {
            "stream_name": stream_name,
            "device_id": self.device_id,
        }

        if password:
            payload["password"] = password

        print(f"📡 Registering with server at {server_ip}")

        try:
            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 200:
                print("✓ Registered with server")
                return True
            else:
                print(f"⚠ Server returned status {response.status_code}")
                # Don't fail on registration - server might not be running
                return True

        except requests.exceptions.RequestException as e:
            print(f"⚠ Could not register with server: {e}")
            # Don't fail - device can still stream
            return True


if __name__ == "__main__":
    # Test network setup
    setup = NetworkSetup("CC-TEST-001")
    print("Network setup initialized")
    print(f"WiFi connected: {setup.wifi_connected}")
    print(f"Tailscale connected: {setup.tailscale_connected}")
