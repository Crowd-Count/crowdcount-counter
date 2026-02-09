#!/bin/bash
#
# CrowdCount Counter - Complete Setup Script
# Installs all dependencies for Raspberry Pi Zero 2W with Global Shutter Camera
#

set -e  # Exit on error

echo "============================================================"
echo "CrowdCount Counter - Complete Setup"
echo "Raspberry Pi Zero 2W + Global Shutter Camera"
echo "============================================================"
echo ""

# Check if running on Raspberry Pi
if [ ! -f /proc/device-tree/model ]; then
    echo "⚠ Warning: This doesn't appear to be a Raspberry Pi"
    echo "  Continue anyway? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Display Raspberry Pi model
if [ -f /proc/device-tree/model ]; then
    echo "Detected: $(cat /proc/device-tree/model)"
    echo ""
fi

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Please do not run this script as root or with sudo."
    echo "The script will prompt for sudo when needed."
    exit 1
fi

# Update package list
echo "============================================================"
echo "Step 1/10: Updating package list..."
echo "============================================================"
sudo apt update

# Install camera & video dependencies
echo ""
echo "============================================================"
echo "Step 2/10: Installing camera & video dependencies..."
echo "============================================================"
sudo apt install -y \
    ffmpeg \
    python3-picamera2 \
    python3-opencv \
    libcamera-apps

echo "✓ Camera & video dependencies installed"

# Install Bluetooth dependencies
echo ""
echo "============================================================"
echo "Step 3/10: Installing Bluetooth dependencies..."
echo "============================================================"
sudo apt install -y \
    bluetooth \
    bluez \
    python3-dbus \
    libdbus-1-dev \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-3.0 \
    libglib2.0-dev

echo "✓ Bluetooth dependencies installed"

# Install networking dependencies
echo ""
echo "============================================================"
echo "Step 4/10: Installing networking dependencies..."
echo "============================================================"
sudo apt install -y \
    network-manager \
    qrencode

echo "✓ Networking dependencies installed"

# Install Tailscale
echo ""
echo "============================================================"
echo "Step 5/10: Installing Tailscale..."
echo "============================================================"
if command -v tailscale &> /dev/null; then
    echo "✓ Tailscale is already installed"
    tailscale version
else
    echo "Downloading and installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    echo "✓ Tailscale installed successfully"
fi

# Install Python dependencies
echo ""
echo "============================================================"
echo "Step 6/10: Installing Python dependencies..."
echo "============================================================"

sudo apt install -y python3-pip
# Check if requirements.txt exists
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "Installing from requirements.txt..."
    echo "Note: Heavy packages (opencv, picamera2, dbus, pygobject) already installed via apt"
    echo "      Only installing lightweight packages (requests, configparser, etc.)"
    echo "      Using --break-system-packages for Raspberry Pi OS"
    sudo pip3 install -r "$SCRIPT_DIR/requirements.txt" --break-system-packages
    echo "✓ Python dependencies installed"
else
    echo "⚠ requirements.txt not found, skipping pip install"
fi

# Enable Bluetooth service
echo ""
echo "============================================================"
echo "Step 7/10: Enabling Bluetooth service..."
echo "============================================================"
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
echo "✓ Bluetooth service enabled and started"

# Enable Tailscale service
echo ""
echo "============================================================"
echo "Step 8/10: Enabling Tailscale to start on boot..."
echo "============================================================"
if command -v tailscale &> /dev/null; then
    sudo systemctl enable tailscaled
    sudo systemctl start tailscaled
    echo "✓ Tailscale service enabled and started"
    echo ""
    echo "⚠ NOTE: You need to authenticate Tailscale with:"
    echo "   sudo tailscale up"
    echo ""
    echo "Or if you want to authenticate later, it will be done during first boot."
else
    echo "⚠ Tailscale not installed, skipping"
fi

# Check device identity
echo ""
echo "============================================================"
echo "Step 9/10: Checking device identity..."
echo "============================================================"

IDENTITY_FOUND=false
for identity_path in /boot/firmware/device-identity.conf /boot/device-identity.conf; do
    if [ -f "$identity_path" ]; then
        echo "✓ Device identity found: $identity_path"
        cat "$identity_path"
        IDENTITY_FOUND=true
        break
    fi
done

if [ "$IDENTITY_FOUND" = false ]; then
    echo "⚠ Warning: No device identity file found"
    echo ""
    echo "For production, create: /boot/firmware/device-identity.conf"
    echo ""
    echo "Template:"
    echo "  [DEFAULT]"
    echo "  DEVICE_ID=CC-001"
    echo "  DEVICE_SECRET=your-random-secret"
    echo "  MANUFACTURING_DATE=$(date +%Y-%m-%d)"
    echo "  MODEL=counter-v2"
    echo ""
    echo "For development, the system will use default values."
fi

# Setup device configuration
echo ""
echo "============================================================"
echo "Step 10/10: Setting up device configuration..."
echo "============================================================"

DEVICE_CONFIG_DIR="$SCRIPT_DIR/src/counter-stream"
DEVICE_CONFIG="$DEVICE_CONFIG_DIR/device-info.conf"
DEVICE_CONFIG_TEMPLATE="$DEVICE_CONFIG_DIR/device-info.conf.template"

if [ -f "$DEVICE_CONFIG" ]; then
    echo "✓ Device configuration already exists: $DEVICE_CONFIG"
    echo ""
    echo "Current configuration:"
    cat "$DEVICE_CONFIG"
else
    if [ -f "$DEVICE_CONFIG_TEMPLATE" ]; then
        echo "Creating device configuration from template..."
        cp "$DEVICE_CONFIG_TEMPLATE" "$DEVICE_CONFIG"
        echo "✓ Created: $DEVICE_CONFIG"
        echo ""
        echo "⚠ IMPORTANT: Verify this file has the correct shared settings:"
        echo "   nano $DEVICE_CONFIG"
        echo ""
        echo "Shared settings (same for all devices):"
        echo "  - SERVER_IP (your MediaMTX server's Tailscale IP)"
        echo "  - TAILSCALE_AUTH_KEY (reusable key for all devices)"
        echo "  - RTSP_PORT, video settings, API_URL"
        echo ""
        echo "Note: Device-specific settings (ID, passwords) go in"
        echo "      /boot/firmware/device-identity.conf (set during manufacturing)"
    else
        echo "⚠ Warning: Template not found: $DEVICE_CONFIG_TEMPLATE"
    fi
fi

# Verification
echo ""
echo "============================================================"
echo "Verifying Installation..."
echo "============================================================"

# Check camera
echo ""
echo "Camera:"
if python3 -c "import picamera2" 2>/dev/null; then
    echo "  ✓ picamera2 available"
else
    echo "  ✗ picamera2 NOT available"
fi

# Check OpenCV
if python3 -c "import cv2" 2>/dev/null; then
    echo "  ✓ opencv (cv2) available"
else
    echo "  ✗ opencv NOT available"
fi

# Check FFmpeg
if command -v ffmpeg &> /dev/null; then
    echo "  ✓ ffmpeg available"
else
    echo "  ✗ ffmpeg NOT available"
fi

# Check Bluetooth
echo ""
echo "Bluetooth:"
if systemctl is-active --quiet bluetooth; then
    echo "  ✓ Bluetooth service running"
else
    echo "  ✗ Bluetooth service NOT running"
fi

# Check D-Bus
if python3 -c "import dbus" 2>/dev/null; then
    echo "  ✓ dbus-python available"
else
    echo "  ✗ dbus-python NOT available"
fi

# Check PyGObject
if python3 -c "import gi" 2>/dev/null; then
    echo "  ✓ PyGObject available"
else
    echo "  ✗ PyGObject NOT available"
fi

# Check Networking
echo ""
echo "Networking:"
if systemctl is-active --quiet NetworkManager; then
    echo "  ✓ NetworkManager running"
else
    echo "  ✗ NetworkManager NOT running"
fi

# Check Tailscale
if command -v tailscale &> /dev/null; then
    echo "  ✓ Tailscale installed"
else
    echo "  ✗ Tailscale NOT installed"
fi

# Check requests
if python3 -c "import requests" 2>/dev/null; then
    echo "  ✓ requests library available"
else
    echo "  ✗ requests library NOT available"
fi

# Install main service
echo ""
echo "============================================================"
echo "Installing CrowdCount Main Service..."
echo "============================================================"
echo ""
echo "This will install and enable the service to auto-start on boot."
echo ""

if [ -f "$SCRIPT_DIR/install_main_service.sh" ]; then
    sudo "$SCRIPT_DIR/install_main_service.sh"
else
    echo "⚠ Warning: install_main_service.sh not found"
    echo "   You'll need to manually install the service later."
fi

# Install updater service
echo ""
echo "============================================================"
echo "Installing CrowdCount Updater Service..."
echo "============================================================"
echo ""
echo "This will install the auto-updater to check for git updates."
echo ""

if [ -f "$SCRIPT_DIR/install_updater_service.sh" ]; then
    sudo "$SCRIPT_DIR/install_updater_service.sh"
else
    echo "⚠ Warning: install_updater_service.sh not found"
    echo "   You'll need to manually install the updater service later."
fi

# Installation complete
echo ""
echo "============================================================"
echo "✓✓✓ SETUP COMPLETE! ✓✓✓"
echo "============================================================"
echo ""
echo "All services are now installed and configured to auto-start on boot:"
echo ""
echo "  ✓ Tailscale - VPN connectivity"
echo "  ✓ Bluetooth - For WiFi provisioning"
echo "  ✓ CrowdCount Main Service - Provisioning + Streaming"
echo "  ✓ CrowdCount Updater Service - Auto git pull + version reporting"
echo ""
echo "============================================================"
echo "NEXT STEPS (Manual Setup):"
echo "============================================================"
echo ""
echo "1. Create device identity file with YOUR device-specific values:"
echo "   sudo nano /boot/firmware/device-identity.conf"
echo ""
echo "   Example content (CHANGE ALL VALUES for your device):"
echo "   [DEFAULT]"
echo "   DEVICE_ID=T0001              # Replace: Your 5-char hostname"
echo "   DEVICE_SECRET=secret123      # Replace: Your Bluetooth secret"
echo "   DEVICE_PASSWORD=counter123   # Replace: Your SSH password"
echo "   API_PASSWORD=apipass123      # Replace: Your API password"
echo "   MANUFACTURING_DATE=$(date +%Y-%m-%d)"
echo "   MODEL=counter-v2"
echo "   HARDWARE_VERSION=1.0"
echo "   FIRMWARE_VERSION=1.0"
echo "   SERIAL_NUMBER=SN$(date +%Y%m%d)001  # Replace last 3 digits"
echo ""
echo "2. Set device password (use same as DEVICE_PASSWORD above):"
echo "   echo 'counter:YOUR_PASSWORD' | sudo chpasswd"
echo ""
echo "3. Set hostname (use same as DEVICE_ID above):"
echo "   sudo hostnamectl set-hostname YOUR_DEVICE_ID"
echo ""
echo "4. Reboot:"
echo "   sudo reboot"
echo ""
echo "============================================================"
echo "AFTER REBOOT:"
echo "============================================================"
echo ""
echo "Device will automatically:"
echo "  • Authenticate to Tailscale VPN with device hostname"
echo "  • Check WiFi connectivity"
echo "  • Start Bluetooth provisioning (if no WiFi)"
echo "  • Start camera streaming (if WiFi connected)"
echo ""
echo "Verify:"
echo "  ssh counter@YOUR_DEVICE_ID"
echo "  sudo systemctl status crowdcount-main"
echo "  sudo journalctl -u crowdcount-main -f"
echo ""
echo "Expected in logs:"
echo "  ✓ Loaded device identity: YOUR_DEVICE_ID"
echo "  ✓ Tailscale authenticated as YOUR_DEVICE_ID"
echo "  ✓ Streaming started"
echo ""
echo "============================================================"
echo ""
