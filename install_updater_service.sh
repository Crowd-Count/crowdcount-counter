#!/bin/bash
#
# CrowdCount Updater Service Installation
# Sets up the auto-updater to periodically git pull and report version
#

set -e  # Exit on error

echo "============================================================"
echo "CrowdCount Updater Service Installation"
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

UPDATER_SCRIPT="$SCRIPT_DIR/crowdcount-updater.py"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_FILE="$SYSTEMD_DIR/crowdcount-updater.service"

echo "Configuration:"
echo "  Script Directory: $SCRIPT_DIR"
echo "  Updater Script:   $UPDATER_SCRIPT"
echo ""

# Verify files exist
if [ ! -f "$UPDATER_SCRIPT" ]; then
    echo "✗ Error: Updater script not found: $UPDATER_SCRIPT"
    exit 1
fi

# Make updater script executable
echo "Step 1/4: Making updater script executable..."
chmod +x "$UPDATER_SCRIPT"
echo "✓ Script is executable"
echo ""

# Generate service file with correct paths
echo "Step 2/4: Installing systemd service..."

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CrowdCount Auto-Updater (git pull + version reporting)
After=network-online.target crowdcount-firstboot.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $UPDATER_SCRIPT
Restart=always
RestartSec=60
StartLimitIntervalSec=0
StandardOutput=journal
StandardError=journal

# Environment
Environment=PYTHONUNBUFFERED=1
# Point root's git at the counter user's SSH world. The updater sets this
# itself in _git_env(), but having it on the unit means a device is correct
# even before that code runs — and makes the dependency visible to anyone
# reading the unit rather than buried in Python.
#
# NOTE: no -i here. The counter config uses `IdentityFile ~/.ssh/...` and
# OpenSSH expands ~ from the PASSWD DATABASE, not \$HOME, so as root it
# resolves to /root and the key is not found. _git_env() resolves identities
# to absolute paths at runtime; this line is the coarse fallback.
Environment=GIT_SSH_COMMAND=ssh -F /home/counter/.ssh/config -o UserKnownHostsFile=/home/counter/.ssh/known_hosts -o StrictHostKeyChecking=accept-new

# Allow time for network + firstboot SSH key setup
ExecStartPre=/bin/sleep 15

[Install]
WantedBy=multi-user.target
EOF

echo "✓ Service file installed to $SERVICE_FILE"
echo ""

# Reload systemd daemon
echo "Step 3/4: Reloading systemd daemon..."
systemctl daemon-reload
echo "✓ Systemd daemon reloaded"
echo ""

# Enable service
echo "Step 4/4: Enabling service to start on boot..."
systemctl enable crowdcount-updater.service
echo "✓ Service enabled"
echo ""

# Show status
echo "============================================================"
echo "Installation Complete!"
echo "============================================================"
echo ""
echo "The CrowdCount updater service is now installed and enabled."
echo ""
echo "Service will automatically start on boot and will:"
echo "  • Report current version to the API on startup"
echo "  • Check for git updates every 6 hours"
echo "  • Pull new code and restart crowdcount-main if updated"
echo ""
echo "Useful commands:"
echo "  Start now:    sudo systemctl start crowdcount-updater"
echo "  Stop:         sudo systemctl stop crowdcount-updater"
echo "  Status:       sudo systemctl status crowdcount-updater"
echo "  View logs:    sudo journalctl -u crowdcount-updater -f"
echo "  Disable:      sudo systemctl disable crowdcount-updater"
echo ""
echo "To start the service now, run:"
echo "  sudo systemctl start crowdcount-updater"
echo ""
echo "============================================================"
