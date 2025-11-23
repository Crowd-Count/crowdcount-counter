#!/bin/bash
#
# Setup CrowdCount Provisioning System on Raspberry Pi
# Run this script on the Pi to install all provisioning dependencies
#

set -e

echo "============================================================"
echo "CrowdCount Provisioning System Setup"
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

# Update package list
echo "Updating package list..."
sudo apt update

# Install system dependencies
echo ""
echo "Installing system dependencies..."
sudo apt install -y \
    bluetooth \
    bluez \
    python3-pip \
    python3-dbus \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-3.0 \
    network-manager \
    libdbus-1-dev \
    libglib2.0-dev \
    qrencode

echo "✓ System dependencies installed"

# Install Tailscale if not already installed
if ! command -v tailscale &> /dev/null; then
    echo ""
    echo "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    echo "✓ Tailscale installed"
else
    echo "✓ Tailscale already installed"
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip3 install -r requirements.txt
echo "✓ Python dependencies installed"

# Enable Bluetooth service
echo ""
echo "Enabling Bluetooth service..."
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
echo "✓ Bluetooth enabled"

# Check if device identity file exists
echo ""
echo "Checking device identity..."
IDENTITY_FOUND=false

for identity_path in /boot/device-identity.conf /boot/firmware/device-identity.conf; do
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
    echo "For production devices, this file should be created during manufacturing."
    echo "For development, create one manually:"
    echo ""
    echo "  sudo nano /boot/device-identity.conf"
    echo ""
    echo "Template:"
    echo "  [DEFAULT]"
    echo "  DEVICE_ID=CC-DEV-001"
    echo "  DEVICE_SECRET=development-secret"
    echo "  MANUFACTURING_DATE=$(date +%Y-%m-%d)"
    echo "  MODEL=counter-v2"
    echo ""
fi

# Install systemd services
echo ""
echo "Do you want to install systemd services? (y/n)"
read -r install_services

if [[ "$install_services" =~ ^[Yy]$ ]]; then
    sudo ./install_services.sh
else
    echo "⚠ Skipping systemd service installation"
    echo "  Run './install_services.sh' later to install"
fi

echo ""
echo "============================================================"
echo "✓ Setup Complete!"
echo "============================================================"
echo ""
echo "Next Steps:"
echo ""
echo "1. Ensure device identity file exists:"
echo "   sudo cat /boot/device-identity.conf"
echo ""
echo "2. Test provisioning manually:"
echo "   python3 provision_manager.py"
echo ""
echo "3. Or reboot to start automatic provisioning:"
echo "   sudo reboot"
echo ""
echo "4. Check service status after reboot:"
echo "   sudo systemctl status crowdcount-provision.service"
echo ""
echo "5. View logs:"
echo "   sudo journalctl -u crowdcount-provision.service -f"
echo ""
