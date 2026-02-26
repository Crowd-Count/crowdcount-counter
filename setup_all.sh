#!/bin/bash
#
# CrowdCount Counter - Complete Setup Script
# Installs all dependencies for Raspberry Pi Zero 2W with Global Shutter Camera
#

set -e  # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

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

# Pull latest code before doing anything else
echo "============================================================"
echo "Step 0/10: Pulling latest code..."
echo "============================================================"
if [ -d "$SCRIPT_DIR/.git" ]; then
    git -C "$SCRIPT_DIR" pull origin main || echo "⚠ Git pull failed — continuing with current code"
else
    echo "⚠ Not a git repo — skipping pull"
fi
echo ""

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
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "Installing from requirements.txt..."
    echo "Note: Heavy packages (picamera2, dbus, pygobject) already installed via apt"
    echo "      Only installing lightweight packages (requests, etc.)"
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
    # Enable Tailscale SSH if authenticated (additive — does NOT disable regular SSH)
    # NOTE: Regular SSH is intentionally left enabled in the master image.
    # SSH hardening (disabling regular SSH) happens at runtime in crowdcount-main.py
    # AFTER Tailscale authentication succeeds on each individual device.
    # This ensures devices always have SSH fallback access if Tailscale auth fails.
    echo "Checking if Tailscale is authenticated..."
    if sudo tailscale status &> /dev/null; then
        echo "✓ Tailscale is authenticated"
        echo "Enabling Tailscale SSH..."
        sudo tailscale set --ssh || echo "⚠ Failed to enable Tailscale SSH"
        echo "✓ Tailscale SSH enabled (regular SSH stays enabled in master image)"
    else
        echo "⚠ Tailscale not authenticated yet — Tailscale SSH will be enabled at runtime"
    fi
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
    echo "  MODEL=counter-v3"
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
    sudo chmod +x "$SCRIPT_DIR/install_updater_service.sh"
    sudo "$SCRIPT_DIR/install_updater_service.sh"
else
    echo "⚠ Warning: install_updater_service.sh not found"
    echo "   You'll need to manually install the updater service later."
fi

# Install first-boot service
echo ""
echo "============================================================"
echo "Installing CrowdCount First-Boot Service..."
echo "============================================================"
echo ""
echo "This will install the one-shot service that auto-configures"
echo "hostname and password from device-identity.conf on first boot."
echo ""

if [ -f "$SCRIPT_DIR/install_firstboot_service.sh" ]; then
    sudo chmod +x "$SCRIPT_DIR/install_firstboot_service.sh"
    sudo "$SCRIPT_DIR/install_firstboot_service.sh"
else
    echo "⚠ Warning: install_firstboot_service.sh not found"
    echo "   You'll need to manually install the first-boot service later."
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
echo "  ✓ CrowdCount First-Boot Service - Auto hostname + password from identity file"
echo ""
echo "============================================================"
echo "NEXT STEPS:"
echo "============================================================"
echo ""
echo "If this is the MASTER IMAGE (one-time setup):"
echo "  1. Test that everything works (camera, Tailscale, etc.)"
echo "  2. Set up deploy key for private repo (see MANUFACTURING.md)"
echo "  3. Create master image: sudo dd if=/dev/mmcblk0 | gzip > crowdcount-master.img.gz"
echo ""
echo "If this is a PRODUCTION DEVICE:"
echo "  The device identity should already be on the boot partition"
echo "  (written by manufacturing/flash_device.sh)."
echo "  Just reboot — hostname and password will be auto-configured."
echo ""
echo "============================================================"
echo "ZERO-TOUCH MANUFACTURING:"
echo "============================================================"
echo ""
echo "On your Mac, use the one-command flasher:"
echo "  ./manufacturing/flash_device.sh"
echo ""
echo "It handles: flash + identity stamp + QR code + eject."
echo "Boot the Pi — fully operational, no SSH needed."
echo ""
echo "============================================================"
echo ""
