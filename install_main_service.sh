#!/bin/bash
#
# CrowdCount Main Service Installation
# Sets up the device to automatically provision or stream on boot
#

set -e  # Exit on error

echo "============================================================"
echo "CrowdCount Main Service Installation"
echo "============================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "✗ This script must be run as root"
    echo "  Please run: sudo $0"
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MAIN_SCRIPT="$SCRIPT_DIR/crowdcount-main.py"
SERVICE_FILE="$SCRIPT_DIR/crowdcount-main.service"
SYSTEMD_DIR="/etc/systemd/system"

echo "Configuration:"
echo "  Script Directory: $SCRIPT_DIR"
echo "  Main Script:      $MAIN_SCRIPT"
echo "  Service File:     $SERVICE_FILE"
echo ""

# Verify files exist
if [ ! -f "$MAIN_SCRIPT" ]; then
    echo "✗ Error: Main script not found: $MAIN_SCRIPT"
    exit 1
fi

if [ ! -f "$SERVICE_FILE" ]; then
    echo "✗ Error: Service file not found: $SERVICE_FILE"
    exit 1
fi

# Make main script executable
echo "Step 1/5: Making main script executable..."
chmod +x "$MAIN_SCRIPT"
echo "✓ Script is executable"
echo ""

# Disable old individual services if they exist
echo "Step 2/5: Disabling old individual services (if present)..."
for service in crowdcount-provision.service crowdcount-stream.service; do
    if systemctl list-unit-files | grep -q "$service"; then
        echo "  Disabling $service..."
        systemctl disable "$service" 2>/dev/null || true
        systemctl stop "$service" 2>/dev/null || true
    fi
done
echo "✓ Old services disabled"
echo ""

# Copy service file to systemd directory
echo "Step 3/5: Installing systemd service..."
cp "$SERVICE_FILE" "$SYSTEMD_DIR/crowdcount-main.service"
echo "✓ Service file installed to $SYSTEMD_DIR"
echo ""

# Reload systemd daemon
echo "Step 4/5: Reloading systemd daemon..."
systemctl daemon-reload
echo "✓ Systemd daemon reloaded"
echo ""

# Enable and start service
echo "Step 5/5: Enabling service to start on boot..."
systemctl enable crowdcount-main.service
echo "✓ Service enabled"
echo ""

# Show status
echo "============================================================"
echo "Installation Complete!"
echo "============================================================"
echo ""
echo "The CrowdCount main service is now installed and enabled."
echo ""
echo "Service will automatically start on boot and will:"
echo "  • Start provisioning if WiFi is not connected"
echo "  • Start streaming if WiFi is connected and device is provisioned"
echo ""
echo "Useful commands:"
echo "  Start now:    sudo systemctl start crowdcount-main"
echo "  Stop:         sudo systemctl stop crowdcount-main"
echo "  Status:       sudo systemctl status crowdcount-main"
echo "  View logs:    sudo journalctl -u crowdcount-main -f"
echo "  Disable:      sudo systemctl disable crowdcount-main"
echo ""
echo "To start the service now, run:"
echo "  sudo systemctl start crowdcount-main"
echo ""
echo "Or reboot to test automatic startup:"
echo "  sudo reboot"
echo ""
echo "============================================================"
