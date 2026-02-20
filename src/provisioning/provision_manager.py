#!/usr/bin/env python3
"""
Provisioning Manager
Main orchestrator for device provisioning via Bluetooth
"""

import os
import sys
import time
import signal
from pathlib import Path
from gi.repository import GLib

from device_identity import DeviceIdentity
from bluetooth_server import (
    BluetoothProvisioningServer,
    STATUS_WIFI_CONNECTING,
    STATUS_WIFI_FAILED,
    STATUS_SUCCESS,
    STATUS_WIFI_CONNECTED,
)
from network_setup import NetworkSetup


class ProvisioningManager:
    """Manages the complete provisioning process"""

    # Provisioned flags (priority: boot partition first)
    PROVISIONED_FLAG = '/boot/firmware/provisioned'  # Primary (Pi 5, newer models)
    PROVISIONED_FLAG_ALT = '/boot/provisioned'       # Legacy (older Pi models)

    def __init__(self):
        self.device_identity = DeviceIdentity()
        self.network_setup = NetworkSetup(self.device_identity.device_id)
        self.bluetooth_server = None

    def is_provisioned(self):
        """Check if device has already been provisioned"""
        return (os.path.exists(self.PROVISIONED_FLAG) or
                os.path.exists(self.PROVISIONED_FLAG_ALT))

    def mark_provisioned(self):
        """Mark device as provisioned"""
        # Try to write to /boot/firmware first (Pi 5), fall back to /boot
        for flag_path in [self.PROVISIONED_FLAG, self.PROVISIONED_FLAG_ALT]:
            try:
                flag_dir = os.path.dirname(flag_path)
                if os.path.exists(flag_dir):
                    with open(flag_path, 'w') as f:
                        f.write(f"Provisioned on {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"Device ID: {self.device_identity.device_id}\n")
                    print(f"✓ Marked as provisioned: {flag_path}")
                    return True
            except Exception as e:
                print(f"⚠ Could not write to {flag_path}: {e}")
                continue

        print("⚠ Warning: Could not write provisioned flag")
        return False

    def reset_provisioning(self):
        """Reset provisioning state (for re-provisioning)"""
        for flag_path in [self.PROVISIONED_FLAG, self.PROVISIONED_FLAG_ALT]:
            if os.path.exists(flag_path):
                try:
                    os.remove(flag_path)
                    print(f"✓ Removed provisioning flag: {flag_path}")
                except Exception as e:
                    print(f"⚠ Could not remove {flag_path}: {e}")

    def is_wifi_connected(self):
        """Check if WiFi is currently connected"""
        try:
            import subprocess
            result = subprocess.run(['iwgetid'], capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def _reset_provisioning_data(self):
        """Reset provisioning data to allow new credentials"""
        if self.bluetooth_server and self.bluetooth_server.provisioning_data:
            self.bluetooth_server.provisioning_data.reset()

    def _set_status(self, status):
        """Update provisioning status for mobile app feedback"""
        if self.bluetooth_server and self.bluetooth_server.provisioning_data:
            self.bluetooth_server.provisioning_data.set_status(status)

    def on_provisioning_complete(self, data):
        """Callback when all provisioning data is received"""
        try:
            self._do_provisioning(data)
        except Exception as e:
            print(f"\n✗ Unexpected error during provisioning: {e}")
            import traceback
            traceback.print_exc()
            self._set_status(STATUS_WIFI_FAILED)
            self._reset_provisioning_data()

    def _do_provisioning(self, data):
        """Execute the provisioning steps. Called by on_provisioning_complete."""
        print("\n" + "="*60)
        print("📦 PROVISIONING DATA RECEIVED")
        print("="*60)
        print(f"WiFi Network: {data.wifi_ssid}")
        print(f"Server IP: {data.server_ip}")
        print(f"Stream Name: {data.stream_name or self.device_identity.device_id}")
        print("="*60)
        print()

        # Step 1: Configure WiFi with retries
        print("Step 1/4: Configuring WiFi...")
        self._set_status(STATUS_WIFI_CONNECTING)
        max_wifi_attempts = 5
        wifi_success = False

        for attempt in range(1, max_wifi_attempts + 1):
            print(f"  WiFi connection attempt {attempt}/{max_wifi_attempts}...")
            if self.network_setup.configure_wifi(data.wifi_ssid, data.wifi_password):
                wifi_success = True
                self._set_status(STATUS_WIFI_CONNECTED)
                break
            if attempt < max_wifi_attempts:
                print(f"  Retrying in 10 seconds...")
                time.sleep(10)

        if not wifi_success:
            print("✗ WiFi configuration failed after all attempts!")
            print("   Please verify credentials and try again via Bluetooth.")
            self._set_status(STATUS_WIFI_FAILED)
            # DON'T stop BLE - allow user to send new credentials
            self._reset_provisioning_data()
            return

        # Step 2: Configure Tailscale (only if a key was provided)
        stream_name = data.stream_name or self.device_identity.device_id
        if data.tailscale_auth_key and data.tailscale_auth_key.strip():
            print("\nStep 2/4: Joining Tailscale network...")
            if not self.network_setup.configure_tailscale(data.tailscale_auth_key, stream_name):
                print("✗ Tailscale configuration failed!")
                print("   Please check auth key and try again via Bluetooth.")
                # DON'T stop BLE - allow user to send new credentials
                self._reset_provisioning_data()
                return
        else:
            print("\nStep 2/4: Skipping Tailscale (pre-configured on device)")

        # Step 3: Write device configuration
        print("\nStep 3/4: Writing device configuration...")
        try:
            self.network_setup.write_device_config(
                data.server_ip,
                stream_name,
                tailscale_auth_key=data.tailscale_auth_key
            )
        except Exception as e:
            print(f"✗ Failed to write config: {e}")
            print("   Please try again via Bluetooth.")
            # DON'T stop BLE - allow user to send new credentials
            self._reset_provisioning_data()
            return

        # Step 4: Register with server
        print("\nStep 4/4: Registering with server...")
        self.network_setup.register_with_server(data.server_ip, stream_name)

        # Mark as provisioned
        self.mark_provisioned()
        self._set_status(STATUS_SUCCESS)

        print("\n" + "="*60)
        print("✓ PROVISIONING COMPLETE!")
        print("="*60)
        print()
        print("The device will now:")
        print("  1. Disable Bluetooth provisioning")
        print("  2. Start the streaming service")
        print()
        print("You can view the stream in the CrowdCount app.")
        print("="*60)
        print()

        # Stop Bluetooth server (must run on GLib main loop thread)
        time.sleep(2)
        GLib.idle_add(self.bluetooth_server.stop)

    def start_provisioning(self):
        """Start the provisioning process"""
        print("\n" + "="*60)
        print("CROWDCOUNT DEVICE PROVISIONING")
        print("="*60)
        print(f"Device: {self.device_identity}")
        print(f"Model: {self.device_identity.model}")
        print("="*60)
        print()

        # Check if already provisioned
        if self.is_provisioned():
            if self.is_wifi_connected():
                print("✓ Device already provisioned and WiFi connected!")
                print()
                print("To re-provision:")
                print("  1. Run: sudo rm /boot/firmware/provisioned")
                print("  2. Reboot the device")
                print()
                # Return True since device is ready (already provisioned)
                return True
            else:
                print("⚠ Device provisioned but WiFi not connected")
                print("  Starting Bluetooth for re-provisioning...")
                print()
                # Fall through to start BLE server

        # Check WiFi status (for non-provisioned devices)
        elif self.is_wifi_connected():
            print("✓ WiFi already connected")
            print("  Skipping Bluetooth provisioning")
            print()

            # Check if device config exists (relative to this script's location)
            device_config = Path(__file__).parent.parent / "counter-stream" / "device-info.conf"
            if device_config.exists():
                print("✓ Device configuration exists")
                print("  Marking device as provisioned...")
                self.mark_provisioned()
                print()
                print("Device is ready to stream!")
                return True
            else:
                print("⚠ Device configuration missing!")
                print(f"  Please create: {device_config}")
                print()
                print("If you need to re-provision, disconnect WiFi first.")
                return False

        # Start Bluetooth server
        print("Starting Bluetooth provisioning server...")
        print()
        print("Next steps:")
        print("  1. Open the CrowdCount app on your phone")
        print("  2. Scan the QR code on this device")
        print("  3. Enter your WiFi credentials")
        print()

        self.bluetooth_server = BluetoothProvisioningServer(
            self.device_identity,
            self.on_provisioning_complete
        )

        return self.bluetooth_server.start()

    def run(self):
        """Main entry point"""
        # Setup signal handlers
        def signal_handler(sig, frame):
            print("\n⚠ Provisioning interrupted")
            if self.bluetooth_server:
                self.bluetooth_server.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start provisioning
        self.start_provisioning()


def main():
    """Command-line entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='CrowdCount Device Provisioning')
    parser.add_argument('--reset', action='store_true',
                       help='Reset provisioning state')
    parser.add_argument('--force', action='store_true',
                       help='Force provisioning even if already provisioned')
    args = parser.parse_args()

    manager = ProvisioningManager()

    if args.reset:
        print("Resetting provisioning state...")
        manager.reset_provisioning()
        print("✓ Device can now be re-provisioned")
        return 0

    if args.force:
        manager.reset_provisioning()

    manager.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
