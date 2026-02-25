#!/bin/bash
#
# CrowdCount First-Boot Service Installation
# Installs the one-shot service that auto-configures hostname & password on first boot
#

set -e

echo "============================================================"
echo "CrowdCount First-Boot Service Installation"
echo "============================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root."
    echo "  Please run: sudo $0"
    exit 1
fi

# Standard installation directory
STANDARD_DIR="/home/counter/crowdcount-counter"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

if [ "$SCRIPT_DIR" != "$STANDARD_DIR" ]; then
    echo "Warning: Installation directory mismatch!"
    echo "  Current:  $SCRIPT_DIR"
    echo "  Expected: $STANDARD_DIR"
    echo ""
    echo "Continue anyway? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

FIRSTBOOT_SCRIPT="$SCRIPT_DIR/crowdcount-firstboot.py"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_FILE="$SYSTEMD_DIR/crowdcount-firstboot.service"

# Verify script exists
if [ ! -f "$FIRSTBOOT_SCRIPT" ]; then
    echo "Error: First-boot script not found: $FIRSTBOOT_SCRIPT"
    exit 1
fi

# Make executable
echo "Step 1/4: Making first-boot script executable..."
chmod +x "$FIRSTBOOT_SCRIPT"
echo "Done."
echo ""

# Generate service file with correct paths
echo "Step 2/4: Installing systemd service..."

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CrowdCount First-Boot Configuration (hostname + password)
Before=crowdcount-main.service
After=local-fs.target
ConditionPathExists=!/boot/firmware/.firstboot-done

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $FIRSTBOOT_SCRIPT
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "Service file installed to $SERVICE_FILE"
echo ""

# Reload and enable
echo "Step 3/4: Reloading systemd daemon..."
systemctl daemon-reload
echo "Done."
echo ""

echo "Step 4/4: Enabling first-boot service..."
systemctl enable crowdcount-firstboot.service
echo "Done."
echo ""

echo "============================================================"
echo "First-Boot Service Installation Complete!"
echo "============================================================"
echo ""
echo "The first-boot service will run once on next boot and:"
echo "  - Read /boot/firmware/device-identity.conf"
echo "  - Set hostname to DEVICE_ID"
echo "  - Set 'counter' user password to DEVICE_PASSWORD"
echo "  - Create marker file so it never runs again"
echo ""
echo "It runs before crowdcount-main.service."
echo ""
echo "Useful commands:"
echo "  Status:     sudo systemctl status crowdcount-firstboot"
echo "  View logs:  sudo journalctl -u crowdcount-firstboot"
echo "  Re-run:     sudo rm /boot/firmware/.firstboot-done && sudo reboot"
echo ""
