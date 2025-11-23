#!/bin/bash
#
# Install CrowdCount systemd services
# Run this script on the Raspberry Pi after deploying code
#

set -e

echo "============================================================"
echo "Installing CrowdCount Services"
echo "============================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "✗ Please run as root (use sudo)"
    exit 1
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SERVICE_DIR="/etc/systemd/system"

# Install provisioning service
echo "Installing provisioning service..."
cp "$SCRIPT_DIR/crowdcount-provision.service" "$SERVICE_DIR/"
chmod 644 "$SERVICE_DIR/crowdcount-provision.service"
echo "✓ Installed crowdcount-provision.service"

# Install streaming service
echo "Installing streaming service..."
cp "$SCRIPT_DIR/crowdcount-stream.service" "$SERVICE_DIR/"
chmod 644 "$SERVICE_DIR/crowdcount-stream.service"
echo "✓ Installed crowdcount-stream.service"

# Reload systemd
echo ""
echo "Reloading systemd daemon..."
systemctl daemon-reload
echo "✓ Systemd reloaded"

# Enable services
echo ""
echo "Enabling services..."
systemctl enable crowdcount-provision.service
systemctl enable crowdcount-stream.service
echo "✓ Services enabled"

echo ""
echo "============================================================"
echo "Installation Complete!"
echo "============================================================"
echo ""
echo "Service Status:"
echo "  Provisioning: $(systemctl is-enabled crowdcount-provision.service)"
echo "  Streaming:    $(systemctl is-enabled crowdcount-stream.service)"
echo ""
echo "The services will start automatically on next boot."
echo ""
echo "To start services now:"
echo "  sudo systemctl start crowdcount-provision.service"
echo "  sudo systemctl start crowdcount-stream.service"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u crowdcount-provision.service -f"
echo "  sudo journalctl -u crowdcount-stream.service -f"
echo ""
