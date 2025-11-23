#!/bin/bash
#
# SD Card Customization Script for Manufacturing
# This script customizes an SD card with unique device identity
#
# Usage: ./customize_sd_card.sh <device_number> <mount_point>
# Example: ./customize_sd_card.sh 1 /media/boot
#

set -e

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 <device_number> [mount_point]"
    echo ""
    echo "Example: $0 1 /media/boot"
    echo "         $0 42"
    echo ""
    exit 1
fi

DEVICE_NUMBER=$1
MOUNT_POINT=${2:-"/media/boot"}

# Format device ID with leading zeros
DEVICE_ID=$(printf "CC-%05d" $DEVICE_NUMBER)

# Generate random secret (16 hex characters)
DEVICE_SECRET=$(openssl rand -hex 8)

# Get current date
MANUFACTURING_DATE=$(date +%Y-%m-%d)

echo "============================================================"
echo "CrowdCount SD Card Customization"
echo "============================================================"
echo "Device Number: $DEVICE_NUMBER"
echo "Device ID:     $DEVICE_ID"
echo "Device Secret: $DEVICE_SECRET"
echo "Mount Point:   $MOUNT_POINT"
echo "Date:          $MANUFACTURING_DATE"
echo "============================================================"
echo ""

# Check if mount point exists
if [ ! -d "$MOUNT_POINT" ]; then
    echo "✗ Mount point does not exist: $MOUNT_POINT"
    echo "  Please mount the SD card boot partition first."
    exit 1
fi

# Write device identity file
IDENTITY_FILE="$MOUNT_POINT/device-identity.conf"

echo "Writing device identity to $IDENTITY_FILE..."

cat > "$IDENTITY_FILE" <<EOF
# CrowdCount Device Identity
# Factory programmed on $MANUFACTURING_DATE
# DO NOT MODIFY

[DEFAULT]
DEVICE_ID=$DEVICE_ID
DEVICE_SECRET=$DEVICE_SECRET
MANUFACTURING_DATE=$MANUFACTURING_DATE
MODEL=counter-v2
HARDWARE_VERSION=1.0
FIRMWARE_VERSION=1.0
SERIAL_NUMBER=SN$(date +%Y%m%d)$(printf "%05d" $DEVICE_NUMBER)
EOF

echo "✓ Device identity written"

# Generate QR code
QR_DIR="qr_codes"
mkdir -p "$QR_DIR"
QR_FILE="$QR_DIR/qr_${DEVICE_ID}.png"

# QR code contains: crowdcount://provision?id=CC-00001&secret=a1b2c3d4e5f6
QR_DATA="crowdcount://provision?id=${DEVICE_ID}&secret=${DEVICE_SECRET}"

echo ""
echo "Generating QR code..."

if command -v qrencode &> /dev/null; then
    qrencode -s 6 -o "$QR_FILE" "$QR_DATA"
    echo "✓ QR code generated: $QR_FILE"
else
    echo "⚠ qrencode not found - skipping QR code generation"
    echo "  Install with: sudo apt install qrencode"
    echo "  QR data: $QR_DATA"
fi

# Log to manufacturing database
LOG_FILE="manufacturing_log.csv"

if [ ! -f "$LOG_FILE" ]; then
    echo "device_id,device_secret,manufacturing_date,serial_number,qr_file" > "$LOG_FILE"
fi

echo "$DEVICE_ID,$DEVICE_SECRET,$MANUFACTURING_DATE,SN$(date +%Y%m%d)$(printf '%05d' $DEVICE_NUMBER),$QR_FILE" >> "$LOG_FILE"

echo "✓ Logged to $LOG_FILE"

echo ""
echo "============================================================"
echo "✓ SD Card Customization Complete!"
echo "============================================================"
echo ""
echo "Next Steps:"
echo "  1. Unmount the SD card: umount $MOUNT_POINT"
echo "  2. Print QR code label: $QR_FILE"
echo "  3. Apply QR code sticker to device"
echo "  4. Insert SD card into Raspberry Pi"
echo "  5. Ship device"
echo ""
echo "QR Code Data (for printing):"
echo "  $QR_DATA"
echo ""
