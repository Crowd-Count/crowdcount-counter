# CrowdCount Provisioning System

Bluetooth-based provisioning system for CrowdCount camera devices using static QR codes.

## Overview

This provisioning system allows customers to set up their CrowdCount devices by:
1. Scanning a QR code on the device
2. Connecting via Bluetooth
3. Entering WiFi and Tailscale credentials
4. Automatic configuration and streaming startup

## Architecture

```
Customer's Phone (iOS App)
        ↓
   Scan QR Code
        ↓
   BLE Connection (authenticated with device secret)
        ↓
  Send WiFi + Tailscale credentials
        ↓
Raspberry Pi Provisioning Service
        ↓
   Configure WiFi (nmcli)
        ↓
   Join Tailscale network
        ↓
   Write device-info.conf
        ↓
   Register with server
        ↓
   Start streaming service
```

## Components

### Core Files

- **`device_identity.py`** - Reads device ID and secret from `/boot/device-identity.conf`
- **`bluetooth_server.py`** - BLE GATT server with authentication
- **`network_setup.py`** - WiFi and Tailscale configuration
- **`provision_manager.py`** - Main orchestrator (run this)

### System Integration

- **`crowdcount-provision.service`** - Systemd service for provisioning
- **`crowdcount-stream.service`** - Systemd service for streaming
- **`install_services.sh`** - Install systemd services

### Configuration

- **`/boot/device-identity.conf`** - Device identity (written during manufacturing)
- **`/boot/provisioned`** - Flag file indicating provisioning complete
- **`../counter-stream/device-info.conf`** - Auto-generated streaming config

## Bluetooth GATT Service

**Service UUID:** `e3e64d66-1db1-11ec-9621-0242ac130002`

### Characteristics

| Characteristic | UUID | Type | Description |
|---------------|------|------|-------------|
| Authentication | `e3e64d67-...` | Write | Device secret for authentication |
| WiFi SSID | `e3e64f08-...` | Write | WiFi network name |
| WiFi Password | `e3e6515a-...` | Write | WiFi password |
| Tailscale Key | `e3e65276-...` | Write | Tailscale auth key |
| Server IP | `e3e65398-...` | Write | MediaMTX server IP (Tailscale) |
| Stream Name | `e3e654ba-...` | Write | Optional stream name |

### Provisioning Flow

1. **Authentication**: Mobile app writes device secret to Auth characteristic
2. **Credentials**: If authenticated, app writes WiFi and Tailscale credentials
3. **Configuration**: Device configures network and writes config files
4. **Completion**: Device marks itself as provisioned and starts streaming

## Installation on Raspberry Pi

### Prerequisites

```bash
# Install system dependencies
sudo apt update
sudo apt install -y \
    bluetooth bluez \
    python3-pip \
    python3-dbus \
    python3-gi \
    network-manager \
    qrencode

# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
```

### Install Provisioning System

```bash
# Clone/copy code to Pi
cd ~/crowdcount-counter/src/provisioning

# Install Python dependencies
pip3 install -r requirements.txt

# Install systemd services
sudo ./install_services.sh
```

### Verify Installation

```bash
# Check services are enabled
systemctl is-enabled crowdcount-provision.service
systemctl is-enabled crowdcount-stream.service

# Check device identity exists
cat /boot/device-identity.conf

# Test provisioning (manual)
python3 provision_manager.py
```

## Usage

### First Boot (Factory Fresh)

On first boot, the provisioning service automatically starts:

```bash
# Check provisioning service status
sudo systemctl status crowdcount-provision.service

# View live logs
sudo journalctl -u crowdcount-provision.service -f
```

The device will:
1. Read `/boot/device-identity.conf`
2. Start advertising as `CrowdCount-CC-00001`
3. Wait for mobile app to connect
4. Process provisioning data
5. Mark as provisioned
6. Start streaming service

### Customer Experience

1. Unbox device and power on
2. Open CrowdCount app on phone
3. Tap "Add Device"
4. Scan QR code on device
5. Enter WiFi network and password
6. Enter Tailscale auth key (or auto-filled)
7. Tap "Connect"
8. Wait ~30 seconds for setup
9. See device online in app

### Re-provisioning

To re-provision a device:

```bash
# Option 1: Command line
sudo python3 provision_manager.py --reset
sudo reboot

# Option 2: Manual
sudo rm /boot/provisioned
sudo reboot

# Option 3: Physical button (if implemented)
# Hold provision button for 5 seconds during boot
```

## Development & Testing

### Test Provisioning Locally

```bash
# Run provisioning manager
python3 provision_manager.py

# In another terminal, check Bluetooth
sudo bluetoothctl
scan on
# Should see: CrowdCount-CC-00001
```

### Test with Mock Device Identity

Create `~/device-identity.conf` for development:

```ini
[DEFAULT]
DEVICE_ID=CC-DEV-001
DEVICE_SECRET=development-secret
MANUFACTURING_DATE=2024-01-01
MODEL=counter-v2
```

### Manual Testing

```python
# Test device identity
python3 device_identity.py

# Test network setup (no actual changes)
python3 network_setup.py

# Test Bluetooth server (requires D-Bus)
python3 bluetooth_server.py
```

## Security

### Authentication

- Device secret is randomly generated during manufacturing (128-bit)
- BLE characteristics require authentication before accepting data
- Physical proximity required (BLE range ~10 meters)

### One-Time Provisioning

- After successful provisioning, `/boot/provisioned` flag is created
- Provisioning service won't start if flag exists
- Re-provisioning requires manual reset

### Data Protection

- Device secrets stored in `/boot/device-identity.conf` (root-owned)
- WiFi credentials stored by NetworkManager (encrypted)
- Tailscale uses secure authentication keys

### Recommendations

1. **Physical button**: Add button to enable re-provisioning
2. **Encrypted secrets**: Use systemd credentials for sensitive data
3. **BLE bonding**: Implement pairing/bonding for added security
4. **Rate limiting**: Limit authentication attempts

## Troubleshooting

### Provisioning Service Not Starting

```bash
# Check service status
sudo systemctl status crowdcount-provision.service

# Check if already provisioned
ls -la /boot/provisioned

# Check device identity
cat /boot/device-identity.conf
```

### Bluetooth Not Advertising

```bash
# Check Bluetooth is powered
sudo bluetoothctl
power on

# Check D-Bus service
systemctl status dbus

# Check for errors
sudo journalctl -u crowdcount-provision.service -n 50
```

### WiFi Connection Fails

```bash
# Check NetworkManager
systemctl status NetworkManager

# Check WiFi radio
nmcli radio wifi
nmcli radio wifi on

# List available networks
nmcli dev wifi list
```

### Tailscale Connection Fails

```bash
# Check Tailscale status
tailscale status

# Check auth key is valid
# (Auth keys expire after use or 90 days)

# Try manual connection
sudo tailscale up --authkey=<key>
```

### Device Not Registering with Server

```bash
# Check Tailscale connectivity
ping <server_tailscale_ip>

# Check server is running
curl http://<server_ip>:5000/health

# Check logs
sudo journalctl -u crowdcount-provision.service -n 100
```

## File Locations

| File | Location | Purpose |
|------|----------|---------|
| Device Identity | `/boot/device-identity.conf` | Factory-programmed ID and secret |
| Provisioned Flag | `/boot/provisioned` | Marks device as provisioned |
| Device Config | `~/crowdcount-counter/src/counter-stream/device-info.conf` | Auto-generated streaming config |
| WiFi Config | Managed by NetworkManager | WiFi credentials |
| Service Logs | `journalctl -u crowdcount-provision` | Provisioning logs |

## Integration with Existing System

The provisioning system integrates seamlessly with your existing streaming system:

1. **Provisioning creates `device-info.conf`** in the expected format
2. **Streaming service waits** for provisioning to complete
3. **Service dependencies** ensure correct startup order
4. **No changes needed** to existing `stream_to_mediamtx.py`

## License

Part of the CrowdCount project.
