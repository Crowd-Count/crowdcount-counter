# CrowdCount Counter - Installation Guide

Complete installation guide for Raspberry Pi Zero 2W with Global Shutter Camera.

## Hardware Requirements

- **Raspberry Pi Zero 2W**
- **Raspberry Pi Global Shutter Camera** (or compatible camera module)
- **microSD card** (16GB minimum, 32GB recommended)
- **Power supply** (5V, 2.5A recommended)
- **WiFi network** for connectivity

## Software Requirements

- **Raspberry Pi OS** (Bookworm or later recommended)
- Python 3.9+
- FFmpeg for video encoding
- Tailscale for secure networking
- BlueZ for Bluetooth provisioning

## Installation Steps

### 1. Flash Raspberry Pi OS

1. Download Raspberry Pi OS (64-bit recommended for Pi Zero 2W)
2. Flash to microSD card using Raspberry Pi Imager
3. Boot the Pi and complete initial setup

### 2. Update System

```bash
sudo apt update
sudo apt upgrade -y
```

### 3. Install System Dependencies

#### Camera & Video Processing

```bash
# FFmpeg for video encoding
sudo apt install -y ffmpeg

# Picamera2 for camera interface (with hardware acceleration)
sudo apt install -y python3-picamera2

# OpenCV for video processing
sudo apt install -y python3-opencv
```

#### Bluetooth & Provisioning

```bash
# Bluetooth stack
sudo apt install -y bluetooth bluez

# D-Bus Python bindings
sudo apt install -y python3-dbus libdbus-1-dev

# GObject/GLib bindings
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 libglib2.0-dev
```

#### Networking

```bash
# NetworkManager for WiFi management
sudo apt install -y network-manager

# QR code generator for device provisioning
sudo apt install -y qrencode
```

#### Tailscale VPN

```bash
# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
```

### 4. Install Python Dependencies

```bash
cd /home/counter/crowdcount-counter

# Install Python packages
# Note: Many packages are already installed via apt,
# but this ensures any missing pip packages are installed
pip3 install -r requirements.txt
```

### 5. Clone/Copy Project Files

**Standard Installation Directory**: `/home/counter/crowdcount-counter`

**Note**: All CrowdCount devices use:
- Username: `counter`
- Hostname: Device ID (e.g., `T0002`)
- Format: `counter@T0002`

```bash
# If using git
git clone <repository-url> /home/counter/crowdcount-counter

# Or copy files manually via scp/rsync
# Make sure all files are in /home/counter/crowdcount-counter/
```

### 6. Create Device Identity File

During manufacturing or setup, create a device identity file:

```bash
sudo nano /boot/firmware/device-identity.conf
```

Add the following content (customize values):

```ini
[DEFAULT]
DEVICE_ID=CC-001
DEVICE_SECRET=your-random-secret-here
MANUFACTURING_DATE=2024-01-01
MODEL=counter-v2
```

For development/testing, you can skip this step and the system will use default values.

### 7. Enable Bluetooth

```bash
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
```

### 8. Install Main Service

```bash
cd /home/counter/crowdcount-counter
sudo ./install_main_service.sh
```

This will:
- Make the main orchestrator executable
- Install the systemd service
- Enable auto-start on boot

### 9. Test Installation

#### Test Camera

```bash
# Test if camera is detected
libcamera-hello --list-cameras

# Quick test capture
libcamera-still -o test.jpg
```

#### Test Bluetooth

```bash
# Check Bluetooth is running
sudo systemctl status bluetooth

# Check adapter
hciconfig
```

#### Test Network

```bash
# Check WiFi
iwgetid

# Check NetworkManager
nmcli device status
```

### 10. Start Service

```bash
# Start now
sudo systemctl start crowdcount-main

# Check status
sudo systemctl status crowdcount-main

# View logs
sudo journalctl -u crowdcount-main -f
```

### 11. Reboot to Test Auto-Start

```bash
sudo reboot
```

After reboot, the service should automatically start and:
- Enter provisioning mode if no WiFi
- Start streaming if WiFi is connected

## Verification

### Check Service Status

```bash
sudo systemctl status crowdcount-main
```

### View Logs

```bash
# Live logs
sudo journalctl -u crowdcount-main -f

# Recent logs
sudo journalctl -u crowdcount-main -n 100
```

### Check Camera

```bash
# List cameras
libcamera-hello --list-cameras

# Should show your Global Shutter Camera
```

### Check Tailscale

```bash
# Status
sudo tailscale status

# Your Tailscale IP
tailscale ip -4
```

## Troubleshooting

### Camera Not Detected

```bash
# Check camera connection
vcgencmd get_camera

# Should show: supported=1 detected=1

# Check libcamera
libcamera-hello --list-cameras
```

### Bluetooth Not Working

```bash
# Check Bluetooth service
sudo systemctl status bluetooth

# Check adapter
hciconfig

# Restart if needed
sudo systemctl restart bluetooth
```

### Service Not Starting

```bash
# Check logs for errors
sudo journalctl -u crowdcount-main -n 50

# Check file permissions
ls -la /home/pi/crowdcount-counter/crowdcount-main.py

# Should be executable (x flag)
```

### WiFi Not Connecting

```bash
# Check NetworkManager
sudo systemctl status NetworkManager

# List available networks
nmcli device wifi list

# Manually connect to test
sudo nmcli dev wifi connect "SSID" password "PASSWORD"
```

### Picamera2 Import Error

If you get "No module named 'picamera2'":

```bash
# Install via apt (preferred method)
sudo apt install -y python3-picamera2

# Verify installation
python3 -c "import picamera2; print(picamera2.__version__)"
```

### OpenCV Import Error

If you get "No module named 'cv2'":

```bash
# Install via apt (preferred method)
sudo apt install -y python3-opencv

# Or via pip (may require compilation)
pip3 install opencv-python
```

## Performance Optimization

### For Pi Zero 2W

The Pi Zero 2W has limited resources. These settings help:

1. **Use hardware H.264 encoding** (already configured in code)
2. **Lower resolution if needed**: Edit device-info.conf
   ```
   WIDTH=640
   HEIGHT=480
   FPS=30
   ```
3. **Disable unnecessary services**:
   ```bash
   sudo systemctl disable bluetooth  # If not using provisioning
   ```

### Global Shutter Camera Settings

The Global Shutter Camera benefits from:
- Fixed frame rate (configured in code)
- Hardware encoding (already enabled)
- Proper lighting (adjust exposure if needed)

## Uninstall

To remove the service:

```bash
sudo systemctl stop crowdcount-main
sudo systemctl disable crowdcount-main
sudo rm /etc/systemd/system/crowdcount-main.service
sudo systemctl daemon-reload
```

## Additional Resources

- [Picamera2 Documentation](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)
- [Tailscale Setup Guide](https://tailscale.com/kb/1017/install/)
- [NetworkManager Documentation](https://networkmanager.dev/)
- [BlueZ Documentation](http://www.bluez.org/)
