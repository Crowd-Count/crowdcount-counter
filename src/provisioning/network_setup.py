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


class NetworkSetup:
    """Manages WiFi and Tailscale network configuration"""

    def __init__(self, device_id):
        self.device_id = device_id
        self.wifi_connected = False
        self.tailscale_connected = False

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

        try:
            # Turn WiFi off and on to ensure clean state
            subprocess.run(['sudo', 'nmcli', 'radio', 'wifi', 'off'],
                         check=True, capture_output=True)
            time.sleep(2)
            subprocess.run(['sudo', 'nmcli', 'radio', 'wifi', 'on'],
                         check=True, capture_output=True)
            time.sleep(3)

            # Connect to network
            result = subprocess.run(
                ['sudo', 'nmcli', 'dev', 'wifi', 'connect', ssid,
                 'password', password],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                print(f"✓ Connected to WiFi: {ssid}")
                self.wifi_connected = True

                # Save WiFi config for persistence
                self._save_wifi_config(ssid, password)
                return True
            else:
                print(f"✗ WiFi connection failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print("✗ WiFi connection timed out")
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
            hostname = self.device_id.lower().replace('_', '-')

        print(f"🔐 Joining Tailscale network as {hostname}")

        try:
            # Check if Tailscale is installed
            subprocess.run(['which', 'tailscale'], check=True,
                         capture_output=True)
        except subprocess.CalledProcessError:
            print("✗ Tailscale not installed. Run setup_pi.sh first.")
            return False

        try:
            # Join Tailscale network
            result = subprocess.run(
                ['sudo', 'tailscale', 'up',
                 '--authkey', auth_key,
                 '--hostname', hostname,
                 '--accept-routes'],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                print(f"✓ Joined Tailscale network")

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
                ['tailscale', 'ip', '-4'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return None

    def _save_wifi_config(self, ssid, password):
        """Save WiFi configuration for future reference"""
        config_dir = Path.home() / '.config' / 'crowdcount'
        config_dir.mkdir(parents=True, exist_ok=True)

        config_file = config_dir / 'wifi.conf'
        with open(config_file, 'w') as f:
            f.write(f"SSID={ssid}\n")
            f.write(f"# Password stored in NetworkManager\n")

        # Restrict permissions
        os.chmod(config_file, 0o600)
        print(f"  WiFi config saved to {config_file}")

    def write_device_config(self, server_ip, stream_name=None):
        """
        Write device-info.conf for streaming service

        Args:
            server_ip: MediaMTX server IP (Tailscale IP)
            stream_name: Optional stream name (defaults to device_id)
        """
        if not stream_name:
            stream_name = self.device_id

        # Find the counter-stream directory
        script_dir = Path(__file__).parent.parent / 'counter-stream'
        config_file = script_dir / 'device-info.conf'

        print(f"📝 Writing device configuration to {config_file}")

        config_content = f"""# Device Configuration File
# Auto-generated by provisioning system on {time.strftime('%Y-%m-%d %H:%M:%S')}

# Unique identifier for this device/camera (used as stream name)
DEVICE_ID={stream_name}

# MediaMTX server Tailscale IP address
SERVER_IP={server_ip}

# RTSP port (default: 8554)
RTSP_PORT=8554

# Video settings
WIDTH=640
HEIGHT=480
FPS=30

# Optional: Authentication password (if MediaMTX requires it)
# Leave empty if no authentication is needed
PASSWORD=
"""

        with open(config_file, 'w') as f:
            f.write(config_content)

        print(f"✓ Device configuration written")
        return config_file

    def register_with_server(self, server_ip, stream_name, password=''):
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
            'stream_name': stream_name,
            'device_id': self.device_id,
        }

        if password:
            payload['password'] = password

        print(f"📡 Registering with server at {server_ip}")

        try:
            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 200:
                print(f"✓ Registered with server")
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
