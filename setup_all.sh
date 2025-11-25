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
echo "Step 1/8: Updating package list..."
echo "============================================================"
sudo apt update

# Install camera & video dependencies
echo ""
echo "============================================================"
echo "Step 2/8: Installing camera & video dependencies..."
echo "============================================================"
sudo apt install -y \
    ffmpeg \
    python3-picamera2 \
    python3-opencv

echo "✓ Camera & video dependencies installed"

# Install Bluetooth dependencies
echo ""
echo "============================================================"
echo "Step 3/8: Installing Bluetooth dependencies..."
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
echo "Step 4/8: Installing networking dependencies..."
echo "============================================================"
sudo apt install -y \
    network-manager \
    qrencode

echo "✓ Networking dependencies installed"

# Install Tailscale
echo ""
echo "============================================================"
echo "Step 5/8: Installing Tailscale..."
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
echo "Step 6/8: Installing Python dependencies..."
echo "============================================================"

# Check if requirements.txt exists
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "Installing from requirements.txt..."
    pip3 install -r "$SCRIPT_DIR/requirements.txt" --break-system-packages 2>/dev/null || \
        pip3 install -r "$SCRIPT_DIR/requirements.txt"
    echo "✓ Python dependencies installed"
else
    echo "⚠ requirements.txt not found, skipping pip install"
fi

# Enable Bluetooth service
echo ""
echo "============================================================"
echo "Step 7/8: Enabling Bluetooth service..."
echo "============================================================"
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
echo "✓ Bluetooth service enabled and started"

# Check device identity
echo ""
echo "============================================================"
echo "Step 8/8: Checking device identity..."
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

# Installation complete
echo ""
echo "============================================================"
echo "✓ Setup Complete!"
echo "============================================================"
echo ""
echo "Next Steps:"
echo ""
echo "1. Install the main service:"
echo "   sudo ./install_main_service.sh"
echo ""
echo "2. (Optional) Create device identity file:"
echo "   sudo nano /boot/firmware/device-identity.conf"
echo ""
echo "3. Reboot to start the service:"
echo "   sudo reboot"
echo ""
echo "4. After reboot, check service status:"
echo "   sudo systemctl status crowdcount-main"
echo ""
echo "5. View logs:"
echo "   sudo journalctl -u crowdcount-main -f"
echo ""
echo "See INSTALL.md for detailed documentation."
echo ""
