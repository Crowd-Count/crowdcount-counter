# QR Code Generation Guide

This guide explains how to generate QR codes for CrowdCount devices.

## Automatic Generation (Recommended)

The manufacturing script **automatically generates QR codes** when you customize SD cards:

```bash
./customize_sd_card.sh 1 /media/boot
```

This creates:
- Device identity file on SD card
- QR code PNG: `qr_codes/qr_CC-00001.png`
- Entry in manufacturing log

**QR codes are saved in:** `manufacturing/qr_codes/`

---

## Manual QR Code Generation

If you need to generate a QR code manually (e.g., for testing or if automatic generation failed):

### Step 1: Install qrencode

**On Linux/Raspberry Pi:**
```bash
sudo apt install qrencode
```

**On macOS:**
```bash
brew install qrencode
```

**On Windows:**
Download from: https://fukuchi.org/works/qrencode/

### Step 2: Get Device Information

Find your device ID and secret from `/boot/device-identity.conf`:

```bash
# On the Pi:
cat /boot/device-identity.conf

# Example output:
# DEVICE_ID=CC-00001
# DEVICE_SECRET=a1b2c3d4e5f6
```

### Step 3: Generate QR Code

**Basic command:**
```bash
qrencode -o qr_CC-00001.png "crowdcount://provision?id=CC-00001&secret=a1b2c3d4e5f6"
```

**With better quality (recommended for printing):**
```bash
qrencode -s 6 -o qr_CC-00001.png "crowdcount://provision?id=CC-00001&secret=a1b2c3d4e5f6"
```

**High resolution for professional printing:**
```bash
qrencode -s 10 -o qr_CC-00001.png "crowdcount://provision?id=CC-00001&secret=a1b2c3d4e5f6"
```

### Parameters Explained:
- `-s 6` - Size multiplier (6 = medium, 10 = large)
- `-o filename.png` - Output file
- The quoted string is the QR code data

---

## QR Code Format

The QR code must contain this exact format:

```
crowdcount://provision?id=<DEVICE_ID>&secret=<DEVICE_SECRET>
```

### Examples:

**Device 1:**
```
crowdcount://provision?id=CC-00001&secret=a1b2c3d4e5f6
```

**Device 2:**
```
crowdcount://provision?id=CC-00002&secret=f6e5d4c3b2a1
```

**Development device:**
```
crowdcount://provision?id=CC-DEV-001&secret=test-secret-123
```

---

## Batch QR Code Generation

Generate QR codes for multiple devices at once:

### From Manufacturing Log:

```bash
# Read from manufacturing_log.csv and generate QR codes
while IFS=, read -r device_id device_secret rest; do
    # Skip header
    if [ "$device_id" = "device_id" ]; then
        continue
    fi

    # Generate QR code
    qr_file="qr_codes/qr_${device_id}.png"
    qrencode -s 6 -o "$qr_file" "crowdcount://provision?id=${device_id}&secret=${device_secret}"

    echo "Generated: $qr_file"
done < manufacturing_log.csv
```

### For Sequential Devices:

```bash
# Generate QR codes for devices 1-10
for i in {1..10}; do
    DEVICE_ID=$(printf "CC-%05d" $i)
    # Get secret from your device (you'll need to read from /boot/device-identity.conf)
    # Or re-run customize_sd_card.sh which auto-generates QR codes

    echo "Generate QR for $DEVICE_ID"
done
```

---

## QR Code Verification

### Test on Your Phone:

**iOS:**
- Open Camera app
- Point at QR code
- Should see: "Open in CrowdCount" (once app is installed)

**Android:**
- Open Camera app or Google Lens
- Point at QR code
- Should show: `crowdcount://provision?id=...`

### Decode QR Code (verify contents):

```bash
# Install zbar-tools
sudo apt install zbar-tools

# Decode QR code
zbarimg qr_codes/qr_CC-00001.png

# Output should be:
# QR-Code:crowdcount://provision?id=CC-00001&secret=a1b2c3d4e5f6
```

---

## Printing QR Codes

### Label Printer (Recommended)

**For label printers (Dymo, Brother, etc.):**
```bash
# Print to default label printer
lpr -P LabelPrinter qr_codes/qr_CC-00001.png

# Print all QR codes
for qr in qr_codes/*.png; do
    lpr -P LabelPrinter "$qr"
done
```

### Standard Printer

**Print to regular printer:**
```bash
# Convert to PDF first (better quality)
convert qr_codes/qr_CC-00001.png qr_CC-00001.pdf
lpr qr_CC-00001.pdf
```

### Online Label Services

Upload PNG files to services like:
- Avery Design & Print
- Sticker Mule
- UPrinting
- VistaPrint

**Recommended label size:** 1" x 1" (25mm x 25mm) minimum

---

## QR Code from Existing Device

If you have a Pi with `/boot/device-identity.conf` and need to regenerate the QR code:

```bash
#!/bin/bash
# generate_qr_from_device.sh

# Read device identity
source /boot/device-identity.conf

# Generate QR code
qrencode -s 6 -o "qr_${DEVICE_ID}.png" \
    "crowdcount://provision?id=${DEVICE_ID}&secret=${DEVICE_SECRET}"

echo "QR code saved to: qr_${DEVICE_ID}.png"
```

Usage:
```bash
chmod +x generate_qr_from_device.sh
./generate_qr_from_device.sh
```

---

## Creating QR Code Sheets (Multiple per Page)

Generate a printable sheet with multiple QR codes:

### Using ImageMagick:

```bash
# Install ImageMagick
sudo apt install imagemagick

# Create a 2x2 grid of QR codes
montage qr_codes/qr_CC-00001.png \
        qr_codes/qr_CC-00002.png \
        qr_codes/qr_CC-00003.png \
        qr_codes/qr_CC-00004.png \
        -tile 2x2 -geometry +10+10 \
        -background white \
        qr_sheet_1-4.png

# Print the sheet
lpr qr_sheet_1-4.png
```

### Add Device ID Text Below QR Code:

```bash
# Generate QR with label
qrencode -s 6 -o temp_qr.png "crowdcount://provision?id=CC-00001&secret=a1b2c3d4e5f6"

# Add text label
convert temp_qr.png -gravity south -pointsize 20 -annotate +0+5 "CC-00001" qr_CC-00001_labeled.png

rm temp_qr.png
```

---

## Troubleshooting

### QR Code Too Small to Scan

Increase size multiplier:
```bash
qrencode -s 10 -o qr_large.png "crowdcount://provision?id=CC-00001&secret=..."
```

### QR Code Too Large (File Size)

Use lower size multiplier:
```bash
qrencode -s 4 -o qr_small.png "crowdcount://provision?id=CC-00001&secret=..."
```

### QR Code Won't Scan

**Check:**
1. Sufficient contrast (black on white)
2. Not blurry or pixelated
3. No damage/smudges
4. Camera focused properly
5. Good lighting

**Regenerate with higher quality:**
```bash
qrencode -s 8 -l H -o qr_high_quality.png "crowdcount://provision?id=..."
```
(`-l H` = High error correction level)

### Wrong Data in QR Code

**Verify contents:**
```bash
zbarimg qr_codes/qr_CC-00001.png
```

If wrong, regenerate with correct device ID and secret.

---

## Security Considerations

### QR Code Storage

- ✅ **Do:** Keep QR code PNGs in secure location
- ✅ **Do:** Back up `manufacturing_log.csv` (contains all secrets)
- ❌ **Don't:** Share QR codes publicly
- ❌ **Don't:** Post QR codes online
- ❌ **Don't:** Email QR codes unencrypted

### Lost QR Code

If a device's QR code is lost:

1. **If you have access to the device:**
   ```bash
   ssh pi@device-ip
   cat /boot/device-identity.conf
   # Use values to regenerate QR code
   ```

2. **If you have manufacturing log:**
   ```bash
   grep "CC-00001" manufacturing_log.csv
   # Get secret and regenerate QR code
   ```

3. **If neither:**
   - Device cannot be provisioned via Bluetooth
   - Must manually configure via SSH/keyboard

---

## Quick Reference

| Task | Command |
|------|---------|
| Generate QR | `qrencode -s 6 -o qr.png "crowdcount://provision?id=CC-00001&secret=abc123"` |
| Verify QR | `zbarimg qr.png` |
| Print QR | `lpr -P LabelPrinter qr.png` |
| Batch generate | `./customize_sd_card.sh <number>` (auto-generates) |
| Add text label | `convert qr.png -annotate +0+5 "CC-00001" qr_labeled.png` |

---

## Examples

### Example 1: Single Device

```bash
# Generate QR for device CC-00001
qrencode -s 6 -o qr_CC-00001.png \
    "crowdcount://provision?id=CC-00001&secret=a1b2c3d4e5f6"

# Verify
zbarimg qr_CC-00001.png

# Print
lpr -P LabelPrinter qr_CC-00001.png
```

### Example 2: Development Device

```bash
# Generate test QR
qrencode -s 6 -o qr_dev.png \
    "crowdcount://provision?id=CC-DEV-001&secret=test-secret-123"

# Display on screen to scan with phone
open qr_dev.png  # macOS
xdg-open qr_dev.png  # Linux
```

### Example 3: Production Batch

```bash
# Customize 100 SD cards (auto-generates QR codes)
for i in {1..100}; do
    echo "=== Device $i ==="

    # Wait for SD card insertion
    echo "Insert SD card for device $i, then press Enter"
    read

    # Customize (generates QR automatically)
    ./customize_sd_card.sh $i /media/boot

    # Unmount
    sudo umount /media/boot
done

# All QR codes are now in qr_codes/ directory
ls qr_codes/
```

---

## Additional Resources

- **qrencode documentation:** `man qrencode`
- **QR Code standards:** ISO/IEC 18004
- **Test QR codes online:** https://www.qr-code-generator.com/
- **Decode QR online:** https://zxing.org/w/decode.jspx
