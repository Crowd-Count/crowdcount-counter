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

from device_identity import DeviceIdentity
from bluetooth_server import BluetoothProvisioningServer
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
        for flag_path in [self.PROVISIONED_FLAG_ALT, self.PROVISIONED_FLAG]:
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

    def on_provisioning_complete(self, data):
        """Callback when all provisioning data is received"""
        print("\n" + "="*60)
        print("📦 PROVISIONING DATA RECEIVED")
        print("="*60)
        print(f"WiFi Network: {data.wifi_ssid}")
        print(f"Server IP: {data.server_ip}")
        print(f"Stream Name: {data.stream_name or self.device_identity.device_id}")
        print("="*60)
        print()

        # Step 1: Configure WiFi
        print("Step 1/4: Configuring WiFi...")
        if not self.network_setup.configure_wifi(data.wifi_ssid, data.wifi_password):
            print("✗ WiFi configuration failed!")
            print("   Please check credentials and try again.")
            self.bluetooth_server.stop()
            return

        # Step 2: Configure Tailscale
        print("\nStep 2/4: Joining Tailscale network...")
        stream_name = data.stream_name or self.device_identity.device_id
        if not self.network_setup.configure_tailscale(data.tailscale_auth_key, stream_name):
            print("✗ Tailscale configuration failed!")
            print("   Please check auth key and try again.")
            self.bluetooth_server.stop()
            return

        # Step 3: Write device configuration
        print("\nStep 3/4: Writing device configuration...")
        try:
            self.network_setup.write_device_config(data.server_ip, stream_name)
        except Exception as e:
            print(f"✗ Failed to write config: {e}")
            self.bluetooth_server.stop()
            return

        # Step 4: Register with server
        print("\nStep 4/4: Registering with server...")
        self.network_setup.register_with_server(data.server_ip, stream_name)

        # Mark as provisioned
        self.mark_provisioned()

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

        # Stop Bluetooth server
        time.sleep(2)
        self.bluetooth_server.stop()

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
            print("⚠ Device already provisioned!")
            print()
            print("To re-provision:")
            print("  1. Run: sudo rm /boot/provisioned")
            print("  2. Reboot the device")
            print()
            print("Or use the reset button on the device.")
            return False

        # Check WiFi status
        if self.is_wifi_connected():
            print("✓ WiFi already connected")
            print("  Skipping Bluetooth provisioning")
            print()

            # Check if device config exists
            device_config = Path("/home/counter/crowdcount-counter/src/counter-stream/device-info.conf")
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
