#!/usr/bin/env python3
"""
Device Identity Manager
Reads device ID and secret from boot partition for QR code provisioning
"""

import os
import configparser
from pathlib import Path

# Possible locations for device identity file
# Get the real user's home directory even when running with sudo
_real_user = os.environ.get('SUDO_USER') or os.environ.get('USER')
_user_home = os.path.expanduser(f'~{_real_user}') if _real_user else os.path.expanduser('~')

IDENTITY_PATHS = [
    '/boot/firmware/device-identity.conf',  # Primary: Boot partition (Pi Zero 2W) - survives reflash
    '/boot/device-identity.conf',           # Secondary: Legacy boot partition (older models, just in case)
    f'{_user_home}/crowdcount-counter/boot/device-identity.conf',  # Fallback: Project directory (development)
]

class DeviceIdentity:
    """Manages device identity for provisioning"""

    def __init__(self):
        self.device_id = None
        self.device_secret = None
        self.manufacturing_date = None
        self.model = "counter-v2"
        self._load_identity()

    def _load_identity(self):
        """Load device identity from config file"""
        for path in IDENTITY_PATHS:
            if os.path.exists(path):
                self._read_identity_file(path)
                print(f"✓ Loaded device identity from {path}")
                return

        print("⚠ Warning: No device identity file found. Using defaults.")
        self.device_id = "CC-DEV-001"
        self.device_secret = "development-secret"

    def _read_identity_file(self, path):
        """Read identity from config file"""
        config = configparser.ConfigParser()
        config.read(path)

        # Support both [DEFAULT] section and no section
        if 'DEFAULT' in config:
            section = config['DEFAULT']
        else:
            section = config[config.sections()[0]] if config.sections() else {}

        self.device_id = section.get('DEVICE_ID', 'CC-UNKNOWN')
        self.device_secret = section.get('DEVICE_SECRET', '')
        self.manufacturing_date = section.get('MANUFACTURING_DATE', 'unknown')
        self.model = section.get('MODEL', 'counter-v2')

    def get_bluetooth_name(self):
        """Get the Bluetooth advertised name"""
        return f"CrowdCount: {self.device_id}"

    def validate_secret(self, provided_secret):
        """Validate the provided secret matches device secret"""
        return self.device_secret == provided_secret

    def __str__(self):
        return f"Device {self.device_id} (manufactured {self.manufacturing_date})"


if __name__ == "__main__":
    # Test the identity reader
    identity = DeviceIdentity()
    print(f"Device ID: {identity.device_id}")
    print(f"Bluetooth Name: {identity.get_bluetooth_name()}")
    print(f"Model: {identity.model}")
    print(f"Manufacturing Date: {identity.manufacturing_date}")
