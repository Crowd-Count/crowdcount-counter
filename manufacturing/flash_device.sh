#!/bin/bash
#
# CrowdCount One-Command Device Flasher
# Runs on macOS — flashes master image, stamps device identity, generates QR code
#
# Usage:
#   ./manufacturing/flash_device.sh
#   ./manufacturing/flash_device.sh --image /path/to/crowdcount-master.img.gz
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Default image location — override with --image flag
IMAGE_PATH="$REPO_DIR/crowdcount-master.img.gz"

# Parse flags
while [[ $# -gt 0 ]]; do
    case $1 in
        --image)
            IMAGE_PATH="$2"
            shift 2
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo ""
echo -e "${BOLD}============================================================${NC}"
echo -e "${BOLD}  CrowdCount One-Command Device Flasher${NC}"
echo -e "${BOLD}  Insert SD card -> Run this -> Eject -> Boot -> Done${NC}"
echo -e "${BOLD}============================================================${NC}"
echo ""

# ─────────────────────────────────────────────────────────────
# Step 1: Verify master image exists
# ─────────────────────────────────────────────────────────────
echo -e "${CYAN}[1/7] Checking master image...${NC}"

if [ ! -f "$IMAGE_PATH" ]; then
    echo -e "${RED}Master image not found: $IMAGE_PATH${NC}"
    echo ""
    echo "Expected location: $IMAGE_PATH"
    echo "Or specify with: $0 --image /path/to/crowdcount-master.img.gz"
    echo ""
    echo "To create a master image, see MANUFACTURING.md Part 1."
    exit 1
fi

IMAGE_SIZE=$(du -h "$IMAGE_PATH" | cut -f1)
echo -e "${GREEN}Found: $IMAGE_PATH ($IMAGE_SIZE)${NC}"
echo ""

# ─────────────────────────────────────────────────────────────
# Step 2: Collect device credentials
# ─────────────────────────────────────────────────────────────
echo -e "${CYAN}[2/7] Device credentials${NC}"
echo ""

read -rp "  Device ID (e.g. T0005): " DEVICE_ID
if [ -z "$DEVICE_ID" ]; then
    echo -e "${RED}Device ID is required.${NC}"
    exit 1
fi

read -rp "  Device secret (Bluetooth pairing): " DEVICE_SECRET
if [ -z "$DEVICE_SECRET" ]; then
    echo -e "${RED}Device secret is required.${NC}"
    exit 1
fi

read -rsp "  Device password (SSH): " DEVICE_PASSWORD
echo ""
if [ -z "$DEVICE_PASSWORD" ]; then
    echo -e "${RED}Device password is required.${NC}"
    exit 1
fi

read -rsp "  API password: " API_PASSWORD
echo ""
if [ -z "$API_PASSWORD" ]; then
    echo -e "${RED}API password is required.${NC}"
    exit 1
fi

MANUFACTURING_DATE=$(date +%Y-%m-%d)

echo ""
echo -e "${BOLD}  Device ID:       $DEVICE_ID${NC}"
echo -e "${BOLD}  Device Secret:   $DEVICE_SECRET${NC}"
echo -e "${BOLD}  Device Password: (set)${NC}"
echo -e "${BOLD}  API Password:    (set)${NC}"
echo -e "${BOLD}  Mfg Date:        $MANUFACTURING_DATE${NC}"
echo ""

# ─────────────────────────────────────────────────────────────
# Step 3: Detect SD card
# ─────────────────────────────────────────────────────────────
echo -e "${CYAN}[3/7] Detecting SD card...${NC}"
echo ""

# Show external/removable disks on macOS
echo "Available disks:"
echo "─────────────────────────────────────────────────────────"
diskutil list external
echo "─────────────────────────────────────────────────────────"
echo ""

read -rp "  Enter disk device (e.g. disk4): " DISK_NAME

# Normalize — strip /dev/ prefix if provided
DISK_NAME="${DISK_NAME#/dev/}"
DEVICE="/dev/$DISK_NAME"
RAW_DEVICE="/dev/r$DISK_NAME"

if [ ! -e "$DEVICE" ]; then
    echo -e "${RED}Device $DEVICE does not exist.${NC}"
    exit 1
fi

# Get disk info for confirmation
DISK_INFO=$(diskutil info "$DEVICE" 2>/dev/null | grep -E "(Device / Media Name|Disk Size|Removable Media)" || true)
echo ""
echo "$DISK_INFO"
echo ""

echo -e "${YELLOW}WARNING: ALL DATA on $DEVICE will be erased!${NC}"
read -rp "  Type 'yes' to confirm: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# ─────────────────────────────────────────────────────────────
# Step 4: Unmount & flash
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[4/7] Flashing master image to $DEVICE...${NC}"
echo ""

echo "Unmounting all partitions on $DEVICE..."
diskutil unmountDisk "$DEVICE"

echo ""
echo "Writing image (this takes ~2 minutes)..."
echo "Using raw device $RAW_DEVICE for speed..."
echo ""

# Use gzip -dc to decompress and dd to write. bs=4m for macOS.
gzip -dc "$IMAGE_PATH" | sudo dd of="$RAW_DEVICE" bs=4m status=progress 2>&1

sync
echo ""
echo -e "${GREEN}Flash complete.${NC}"

# ─────────────────────────────────────────────────────────────
# Step 5: Mount boot partition & write identity
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[5/7] Stamping device identity...${NC}"
echo ""

# Give macOS a moment to detect partitions
sleep 2

# On a freshly flashed Pi image, the boot partition is partition 1
BOOT_PARTITION="${DEVICE}s1"

# Try to mount it — macOS may auto-mount after dd
echo "Mounting boot partition ($BOOT_PARTITION)..."

# Check if already mounted
MOUNT_POINT=$(diskutil info "$BOOT_PARTITION" 2>/dev/null | grep "Mount Point" | awk -F: '{print $2}' | xargs)

if [ -z "$MOUNT_POINT" ] || [ "$MOUNT_POINT" = "" ]; then
    diskutil mount "$BOOT_PARTITION"
    sleep 1
    MOUNT_POINT=$(diskutil info "$BOOT_PARTITION" 2>/dev/null | grep "Mount Point" | awk -F: '{print $2}' | xargs)
fi

if [ -z "$MOUNT_POINT" ] || [ ! -d "$MOUNT_POINT" ]; then
    echo -e "${RED}Could not mount boot partition.${NC}"
    echo "Try manually: diskutil mount ${BOOT_PARTITION}"
    exit 1
fi

echo -e "${GREEN}Boot partition mounted at: $MOUNT_POINT${NC}"

# Verify it's a Pi boot partition
if [ ! -f "$MOUNT_POINT/config.txt" ] && [ ! -f "$MOUNT_POINT/cmdline.txt" ]; then
    echo -e "${RED}This doesn't look like a Raspberry Pi boot partition.${NC}"
    echo "Expected config.txt or cmdline.txt"
    exit 1
fi

# Write device-identity.conf
IDENTITY_FILE="$MOUNT_POINT/device-identity.conf"

cat > "$IDENTITY_FILE" <<EOF
# CrowdCount Device Identity
# Written during manufacturing — DO NOT MODIFY
# Location on Pi: /boot/firmware/device-identity.conf

[DEFAULT]
DEVICE_ID=$DEVICE_ID
DEVICE_SECRET=$DEVICE_SECRET
DEVICE_PASSWORD=$DEVICE_PASSWORD
API_PASSWORD=$API_PASSWORD
MANUFACTURING_DATE=$MANUFACTURING_DATE
MODEL=counter-v3
HARDWARE_VERSION=1.0
FIRMWARE_VERSION=1.0
SERIAL_NUMBER=SN${MANUFACTURING_DATE//-/}${DEVICE_ID}
EOF

echo -e "${GREEN}Wrote: $IDENTITY_FILE${NC}"

# Remove any stale firstboot marker so firstboot runs on this card
rm -f "$MOUNT_POINT/.firstboot-done" 2>/dev/null || true

echo ""
echo "Identity file contents:"
echo "─────────────────────────────────────────────────────────"
cat "$IDENTITY_FILE"
echo "─────────────────────────────────────────────────────────"

# ─────────────────────────────────────────────────────────────
# Step 6: Generate QR code
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[6/7] Generating QR code...${NC}"

QR_DIR="$SCRIPT_DIR/qr_codes"
mkdir -p "$QR_DIR"

QR_DATA="crowdcount://provision?id=${DEVICE_ID}&secret=${DEVICE_SECRET}"

if command -v qrencode &> /dev/null; then
    QR_FILE="$QR_DIR/qr_${DEVICE_ID}.png"
    qrencode -s 6 -o "$QR_FILE" "$QR_DATA"
    echo -e "${GREEN}QR code saved: $QR_FILE${NC}"

    # Also print QR to terminal if possible
    qrencode -t UTF8 "$QR_DATA" 2>/dev/null || true
else
    echo -e "${YELLOW}qrencode not installed — skipping QR image generation.${NC}"
    echo "  Install with: brew install qrencode"
    echo "  QR data: $QR_DATA"
fi

# Save QR data as text too
echo "$QR_DATA" > "$QR_DIR/qr_${DEVICE_ID}.txt"

# ─────────────────────────────────────────────────────────────
# Step 7: Unmount & eject
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[7/7] Ejecting SD card...${NC}"

sync
diskutil eject "$DEVICE"

echo ""
echo -e "${GREEN}${BOLD}============================================================${NC}"
echo -e "${GREEN}${BOLD}  DONE! Device $DEVICE_ID is ready.${NC}"
echo -e "${GREEN}${BOLD}============================================================${NC}"
echo ""
echo "  1. Remove SD card from reader"
echo "  2. Insert into Raspberry Pi"
echo "  3. Power on — fully operational, no SSH needed"
echo ""
echo "  Hostname:  $DEVICE_ID"
echo "  SSH:       ssh counter@${DEVICE_ID}.local"
echo "  Password:  (as entered above)"
echo ""
echo -e "${CYAN}Ready for next device — insert new SD card and re-run.${NC}"
echo ""
