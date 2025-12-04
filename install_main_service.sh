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

# Standard installation directory for all counters
STANDARD_DIR="/home/counter/crowdcount-counter"

# Get the directory where this script is located (absolute path)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Verify we're in the standard location
if [ "$SCRIPT_DIR" != "$STANDARD_DIR" ]; then
    echo "⚠ Warning: Installation directory mismatch!"
    echo "  Current:  $SCRIPT_DIR"
    echo "  Expected: $STANDARD_DIR"
    echo ""
    echo "All CrowdCount counters should be installed at: $STANDARD_DIR"
    echo "Continue anyway? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

MAIN_SCRIPT="$SCRIPT_DIR/crowdcount-main.py"
SERVICE_TEMPLATE="$SCRIPT_DIR/crowdcount-main.service"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_FILE="$SYSTEMD_DIR/crowdcount-main.service"

echo "Configuration:"
echo "  User:             counter"
echo "  Script Directory: $SCRIPT_DIR"
echo "  Main Script:      $MAIN_SCRIPT"
echo "  Service Template: $SERVICE_TEMPLATE"
echo ""

# Verify files exist
if [ ! -f "$MAIN_SCRIPT" ]; then
    echo "✗ Error: Main script not found: $MAIN_SCRIPT"
    exit 1
fi

if [ ! -f "$SERVICE_TEMPLATE" ]; then
    echo "✗ Error: Service template not found: $SERVICE_TEMPLATE"
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

# Generate service file with correct paths
echo "Step 3/5: Installing systemd service..."
echo "Generating service file with paths:"
echo "  Working Directory: $SCRIPT_DIR"
echo "  Exec Start: $MAIN_SCRIPT"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CrowdCount Main Service (Provisioning + Streaming)
After=network-online.target bluetooth.target tailscaled.service
Wants=network-online.target bluetooth.target
Requires=tailscaled.service

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $MAIN_SCRIPT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Environment
Environment=PYTHONUNBUFFERED=1

# Allow time for network to come up
ExecStartPre=/bin/sleep 5

[Install]
WantedBy=multi-user.target
EOF

echo "✓ Service file installed to $SERVICE_FILE"
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
