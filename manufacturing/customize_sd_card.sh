#!/bin/bash
#
# Customize SD Card with Device Identity
# Writes device-identity.conf to boot partition for manufacturing
# For Raspberry Pi Zero 2W
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================================"
echo "CrowdCount Device Identity Writer"
echo "SD Card Customization for Manufacturing (Pi Zero 2W)"
echo "============================================================"
echo ""

# Check arguments
if [ $# -lt 5 ]; then
    echo -e "${RED}✗ Error: Missing arguments${NC}"
    echo ""
    echo "Usage: $0 <device> <device_id> <device_secret> <device_password> <api_password> [upstream_api_token]"
    echo ""
    echo "Examples:"
    echo "  $0 /dev/sdb T0003 secret123 counter123 apipass123"
    echo "  $0 /dev/sdb T0003 secret123 counter123 apipass123 ups_live_XXXXXXXX_xxxxxxxxxxxxxxxxxxxxxx"
    echo ""
    echo "Arguments:"
    echo "  device            - SD card device (e.g., /dev/sdb, /dev/mmcblk0)"
    echo "  device_id         - Unique device ID/hostname (5 chars, e.g., T0003)"
    echo "  device_secret     - Device secret for Bluetooth provisioning"
    echo "  device_password   - Password for 'counter' user SSH access"
    echo "  api_password      - Password for CrowdCount API status updates"
    echo "  upstream_api_token - OPTIONAL per-device Upstream token (SRT dual-mode)."
    echo "                      Mint one per device with scope=device:"
    echo "                      upstream-api-server/scripts/mint_device_tokens.py"
    echo "                      Without it the device streams legacy RTSP only."
    echo ""
    echo "All fields except upstream_api_token are required."
    echo ""
    exit 1
fi

DEVICE=$1
DEVICE_ID=$2
DEVICE_SECRET=$3
DEVICE_PASSWORD=$4
API_PASSWORD=$5
UPSTREAM_API_TOKEN=${6:-}
MANUFACTURING_DATE=$(date +%Y-%m-%d)

# Safety check
if [ ! -e "$DEVICE" ]; then
    echo -e "${RED}✗ Error: $DEVICE does not exist${NC}"
    echo ""
    echo "Available devices:"
    if command -v lsblk &> /dev/null; then
        lsblk | grep disk
    else
        # macOS
        diskutil list | grep -E "(disk[0-9]+|Volume)"
    fi
    exit 1
fi

# Confirm with user
echo -e "${YELLOW}⚠ WARNING: This will modify the boot partition on $DEVICE${NC}"
echo ""
echo "Device to customize: $DEVICE"
echo "  Device ID (hostname):  $DEVICE_ID"
echo "  Device Secret:         $DEVICE_SECRET"
echo "  Device Password:       $DEVICE_PASSWORD"
echo "  API Password:          $API_PASSWORD"
if [ -n "$UPSTREAM_API_TOKEN" ]; then
    echo "  Upstream Token:        ${UPSTREAM_API_TOKEN:0:16}... (SRT dual-mode enabled)"
else
    echo "  Upstream Token:        (none - legacy RTSP only)"
fi
echo "  Manufacturing Date:    $MANUFACTURING_DATE"
echo ""
echo "Is this correct? (yes/no)"
read -r response

if [[ ! "$response" =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Determine partition name based on OS and device type
# Linux: /dev/sdb -> /dev/sdb1, /dev/mmcblk0 -> /dev/mmcblk0p1
# macOS: /dev/disk42 -> /dev/disk42s1
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    BOOT_PARTITION="${DEVICE}s1"
elif [[ "$DEVICE" == *"mmcblk"* ]] || [[ "$DEVICE" == *"loop"* ]]; then
    # Linux with mmcblk or loop devices
    BOOT_PARTITION="${DEVICE}p1"
else
    # Standard Linux devices
    BOOT_PARTITION="${DEVICE}1"
fi

echo ""
echo "Step 1/5: Checking boot partition..."
if [ ! -e "$BOOT_PARTITION" ]; then
    echo -e "${RED}✗ Error: Boot partition not found: $BOOT_PARTITION${NC}"
    echo ""
    echo "Partitions on $DEVICE:"
    if command -v lsblk &> /dev/null; then
        lsblk "$DEVICE"
    else
        # macOS
        diskutil list "$DEVICE"
    fi
    exit 1
fi
echo -e "${GREEN}✓${NC} Boot partition found: $BOOT_PARTITION"

# Create mount point
MOUNT_POINT="/tmp/crowdcount-boot-$$"
mkdir -p "$MOUNT_POINT"

echo ""
echo "Step 2/5: Mounting boot partition..."

# Check if already mounted (macOS auto-mounts)
EXISTING_MOUNT=""
if [[ "$OSTYPE" == "darwin"* ]]; then
    EXISTING_MOUNT=$(mount | grep "$BOOT_PARTITION" | awk '{print $3}')
    if [ -n "$EXISTING_MOUNT" ]; then
        echo "Note: Partition already mounted at: $EXISTING_MOUNT"
        MOUNT_POINT="$EXISTING_MOUNT"
        echo -e "${GREEN}✓${NC} Using existing mount: $MOUNT_POINT"
    else
        # Try to mount on macOS
        if ! sudo mount -t msdos "$BOOT_PARTITION" "$MOUNT_POINT" 2>/dev/null; then
            echo -e "${RED}✗ Error: Failed to mount boot partition${NC}"
            echo "Try: diskutil mount $BOOT_PARTITION"
            rmdir "$MOUNT_POINT"
            exit 1
        fi
        echo -e "${GREEN}✓${NC} Mounted to: $MOUNT_POINT"
    fi
else
    # Linux mount
    if ! sudo mount "$BOOT_PARTITION" "$MOUNT_POINT"; then
        echo -e "${RED}✗ Error: Failed to mount boot partition${NC}"
        rmdir "$MOUNT_POINT"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} Mounted to: $MOUNT_POINT"
fi

# Cleanup function
cleanup() {
    echo ""
    echo "Step 5/5: Cleaning up..."
    # Only unmount if we mounted it ourselves (not using existing mount)
    if [ -z "$EXISTING_MOUNT" ]; then
        sudo umount "$MOUNT_POINT" 2>/dev/null || true
        rmdir "$MOUNT_POINT" 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Unmounted and cleaned up"
    else
        echo -e "${GREEN}✓${NC} Left existing mount intact"
    fi
}
trap cleanup EXIT

# Check if it's actually a boot partition
if [ ! -f "$MOUNT_POINT/config.txt" ] && [ ! -f "$MOUNT_POINT/cmdline.txt" ]; then
    echo -e "${RED}✗ Error: This doesn't look like a Raspberry Pi boot partition${NC}"
    echo "  Expected to find config.txt or cmdline.txt"
    exit 1
fi

echo ""
echo "Step 3/5: Creating device-identity.conf..."

# Write device identity file
IDENTITY_FILE="$MOUNT_POINT/device-identity.conf"
sudo tee "$IDENTITY_FILE" > /dev/null <<EOF
# CrowdCount Device Identity
# This file is written during manufacturing to /boot/firmware/device-identity.conf
#
# DO NOT MODIFY THIS FILE - it contains factory-programmed device identity
# This file survives OS reflashes and contains all device-specific configuration

[DEFAULT]
# Unique device identifier (hostname - 5 characters)
# Used as: hostname, stream name, Bluetooth name
DEVICE_ID=$DEVICE_ID

# Device secret for Bluetooth provisioning pairing
DEVICE_SECRET=$DEVICE_SECRET

# Device password for 'counter' user SSH access
DEVICE_PASSWORD=$DEVICE_PASSWORD

# API password for status updates to CrowdCount API
API_PASSWORD=$API_PASSWORD

# Manufacturing information (auto-generated)
MANUFACTURING_DATE=$MANUFACTURING_DATE
MODEL=counter-v3
HARDWARE_VERSION=1.0
FIRMWARE_VERSION=1.0
SERIAL_NUMBER=SN${MANUFACTURING_DATE//-/}${DEVICE_ID}
EOF

# Upstream SRT dual-mode: per-device control-plane token (optional).
# The firmware only attempts SRT when this is present AND the device's
# streaming_mode flag on the CrowdCount API is set to "srt".
if [ -n "$UPSTREAM_API_TOKEN" ]; then
    sudo tee -a "$IDENTITY_FILE" > /dev/null <<EOF

# Per-device Upstream API token (SRT dual-mode). Minted with scope=device
# (trust-on-first-use: binds to this device's agent on first register).
UPSTREAM_API_TOKEN=$UPSTREAM_API_TOKEN
EOF
fi

echo -e "${GREEN}✓${NC} Created: $IDENTITY_FILE"

echo ""
echo "Step 4/5: Verifying file..."
if [ -f "$IDENTITY_FILE" ]; then
    echo -e "${GREEN}✓${NC} File exists and is readable"
    echo ""
    echo "Contents (secret values truncated to 16 chars):"
    echo "─────────────────────────────────────────────────────────"
    # Truncate the value of every secret-shaped key, matching the 16-char
    # truncation the confirmation prompt applies to UPSTREAM_API_TOKEN. The
    # key charset must cover digits, or a future KEY2_TOKEN prints in full.
    sed -E 's/^([A-Z0-9_]*(SECRET|PASSWORD|TOKEN))=(.{0,16}).*/\1=\3.../' "$IDENTITY_FILE"
    echo "─────────────────────────────────────────────────────────"
else
    echo -e "${RED}✗ Error: File was not created${NC}"
    exit 1
fi

# Sync to ensure write
sync

echo ""
echo "============================================================"
echo -e "${GREEN}✓ SUCCESS!${NC}"
echo "============================================================"
echo ""
echo "Device identity written to boot partition:"
echo "  Device ID (hostname):  $DEVICE_ID"
echo "  Device Secret:         $DEVICE_SECRET"
echo "  Device Password:       $DEVICE_PASSWORD"
echo "  API Password:          $API_PASSWORD"
echo "  Location: $IDENTITY_FILE"
echo ""
echo "Next steps:"
echo "  1. Safely eject SD card"
echo "  2. Insert into Raspberry Pi Zero 2W"
echo "  3. First boot - device will auto-configure with hostname $DEVICE_ID"
echo "  4. Set device password: echo 'counter:$DEVICE_PASSWORD' | sudo chpasswd"
echo "  5. Reboot - device will stream with ID $DEVICE_ID"
echo ""
echo "SSH access:"
echo "  Username: counter"
echo "  Password: $DEVICE_PASSWORD"
echo ""
echo "Verify after boot:"
echo "  sudo journalctl -u crowdcount-main -f | grep 'Device identity'"
echo "  Should show: Device identity: $DEVICE_ID"
echo ""
