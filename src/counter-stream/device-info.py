"""
Device Information Configuration File
Contains credentials and identifiers for API and server connections
"""

import uuid
from dataclasses import dataclass
from typing import Optional

@dataclass
class DeviceInfo:
    """Device information and credentials container"""
    
    # User credentials
    username: str = "your_username_here"
    password: str = "your_secure_password_here"
    
    # Device identification
    device_id: str = "device_001"
    device_name: str = "MyDevice"
    device_type: str = "IoT_Sensor"
    
    # API connection settings
    api_endpoint: str = "https://api.example.com/v1"
    api_key: str = "your_api_key_here"
    api_version: str = "1.0"
    
    # Server connection settings
    server_host: str = "localhost"
    server_port: int = 8080
    server_protocol: str = "https"
    
    # Bluetooth credentials (UUIDs)
    bluetooth_service_uuid: str = "12345678-1234-5678-9abc-123456789abc"
    bluetooth_characteristic_uuid: str = "87654321-4321-8765-cba9-987654321098"
    bluetooth_descriptor_uuid: str = "11111111-2222-3333-4444-555555555555"
    
    # Additional Bluetooth settings
    bluetooth_device_name: str = "MyBLEDevice"
    bluetooth_manufacturer_id: int = 0x004C  # Apple's manufacturer ID as example
    
    # Security settings
    encryption_key: str = "your_encryption_key_here"
    certificate_path: Optional[str] = None
    private_key_path: Optional[str] = None
    
    # Additional connection parameters
    connection_timeout: int = 30
    retry_attempts: int = 3
    heartbeat_interval: int = 60

# Create global instance
device_info = DeviceInfo()

# Alternative dictionary format for easy access
DEVICE_CONFIG = {
    "credentials": {
        "username": device_info.username,
        "password": device_info.password,
        "api_key": device_info.api_key,
        "encryption_key": device_info.encryption_key
    },
    "device": {
        "id": device_info.device_id,
        "name": device_info.device_name,
        "type": device_info.device_type
    },
    "api": {
        "endpoint": device_info.api_endpoint,
        "version": device_info.api_version
    },
    "server": {
        "host": device_info.server_host,
        "port": device_info.server_port,
        "protocol": device_info.server_protocol
    },
    "bluetooth": {
        "service_uuid": device_info.bluetooth_service_uuid,
        "characteristic_uuid": device_info.bluetooth_characteristic_uuid,
        "descriptor_uuid": device_info.bluetooth_descriptor_uuid,
        "device_name": device_info.bluetooth_device_name,
        "manufacturer_id": device_info.bluetooth_manufacturer_id
    },
    "connection": {
        "timeout": device_info.connection_timeout,
        "retry_attempts": device_info.retry_attempts,
        "heartbeat_interval": device_info.heartbeat_interval
    }
}

def get_device_info():
    """Return the device info instance"""
    return device_info

def get_config():
    """Return the configuration dictionary"""
    return DEVICE_CONFIG

def update_credentials(username=None, password=None, api_key=None):
    """Update credentials dynamically"""
    if username:
        device_info.username = username
        DEVICE_CONFIG["credentials"]["username"] = username
    if password:
        device_info.password = password
        DEVICE_CONFIG["credentials"]["password"] = password
    if api_key:
        device_info.api_key = api_key
        DEVICE_CONFIG["credentials"]["api_key"] = api_key

def generate_new_device_id():
    """Generate a new unique device ID"""
    new_id = str(uuid.uuid4())
    device_info.device_id = new_id
    DEVICE_CONFIG["device"]["id"] = new_id
    return new_id

def get_bluetooth_uuids():
    """Return all Bluetooth UUIDs as a tuple"""
    return (
        device_info.bluetooth_service_uuid,
        device_info.bluetooth_characteristic_uuid,
        device_info.bluetooth_descriptor_uuid
    )

# Example usage and validation
if __name__ == "__main__":
    print("Device Configuration:")
    print(f"Device ID: {device_info.device_id}")
    print(f"Username: {device_info.username}")
    print(f"API Endpoint: {device_info.api_endpoint}")
    print(f"Bluetooth UUIDs: {get_bluetooth_uuids()}")
    
    # Validate UUIDs
    try:
        for uuid_str in get_bluetooth_uuids():
            uuid.UUID(uuid_str)
        print("✓ All UUIDs are valid")
    except ValueError as e:
        print(f"✗ Invalid UUID found: {e}")