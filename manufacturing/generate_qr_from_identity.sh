#!/bin/bash
#
# Generate QR Code from Existing Device Identity
# This script reads an existing device-identity.conf file and generates a QR code
#
# Usage: ./generate_qr_from_identity.sh [path_to_device_identity_conf]
# Example: ./generate_qr_from_identity.sh /boot/device-identity.conf
#          ./generate_qr_from_identity.sh ~/crowdcount-counter/boot/device-identity.conf
#

set -e

# Default locations to search for device-identity.conf
DEFAULT_LOCATIONS=(
    "/boot/device-identity.conf"
    "/boot/firmware/device-identity.conf"
    "$HOME/crowdcount-counter/boot/device-identity.conf"
    "$(dirname "$0")/../boot/device-identity.conf"
)

# Get identity file path from argument or search defaults
IDENTITY_FILE="$1"

if [ -z "$IDENTITY_FILE" ]; then
    echo "No file specified, searching default locations..."
    for location in "${DEFAULT_LOCATIONS[@]}"; do
        if [ -f "$location" ]; then
            IDENTITY_FILE="$location"
            echo "Found: $IDENTITY_FILE"
            break
        fi
    done
fi

# Check if file exists
if [ ! -f "$IDENTITY_FILE" ]; then
    echo "✗ Device identity file not found: $IDENTITY_FILE"
    echo ""
    echo "Usage: $0 [path_to_device_identity_conf]"
    echo ""
    echo "Searched locations:"
    for location in "${DEFAULT_LOCATIONS[@]}"; do
        echo "  - $location"
    done
    exit 1
fi

echo "============================================================"
echo "CrowdCount QR Code Generator"
echo "============================================================"
echo "Reading from: $IDENTITY_FILE"
echo "============================================================"
echo ""

# Parse device identity using grep and cut
# The config file format is: DEVICE_ID=CC-00001
DEVICE_ID=$(grep "^DEVICE_ID=" "$IDENTITY_FILE" | cut -d'=' -f2)
DEVICE_SECRET=$(grep "^DEVICE_SECRET=" "$IDENTITY_FILE" | cut -d'=' -f2)

# Validate we got the values
if [ -z "$DEVICE_ID" ]; then
    echo "✗ DEVICE_ID not found in $IDENTITY_FILE"
    exit 1
fi

if [ -z "$DEVICE_SECRET" ]; then
    echo "✗ DEVICE_SECRET not found in $IDENTITY_FILE"
    exit 1
fi

echo "Device ID:     $DEVICE_ID"
echo "Device Secret: $DEVICE_SECRET"
echo ""

# Generate QR code
QR_DIR="qr_codes"
mkdir -p "$QR_DIR"
QR_FILE="$QR_DIR/qr_${DEVICE_ID}_${DEVICE_SECRET}.png"

# QR code contains: crowdcount://provision?id=CC-00001&secret=a1b2c3d4e5f6
QR_DATA="crowdcount://provision?id=${DEVICE_ID}&secret=${DEVICE_SECRET}"

echo "Generating QR code..."

if command -v qrencode &> /dev/null; then
    qrencode -s 6 -o "$QR_FILE" "$QR_DATA"
    echo "✓ QR code generated: $QR_FILE"
    echo ""
    echo "QR Code Data:"
    echo "  $QR_DATA"
    echo ""

    # Also save QR data to a text file
    TXT_FILE="$QR_DIR/qr_${DEVICE_ID}_${DEVICE_SECRET}.txt"
    echo "$QR_DATA" > "$TXT_FILE"
    echo "✓ QR data saved: $TXT_FILE"
else
    echo "✗ qrencode not found - cannot generate QR code"
    echo "  Install with: sudo apt install qrencode"
    echo ""
    echo "QR Code Data (manual generation required):"
    echo "  $QR_DATA"
    exit 1
fi

echo ""
echo "============================================================"
echo "✓ QR Code Generation Complete!"
echo "============================================================"
echo ""
echo "Next Steps:"
echo "  1. Print QR code: $QR_FILE"
echo "  2. Apply QR code sticker to device $DEVICE_ID"
echo ""
