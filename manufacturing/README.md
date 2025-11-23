# Manufacturing Process

This directory contains scripts and tools for manufacturing CrowdCount devices.

## Overview

Each CrowdCount device requires:
1. A base SD card image with the software
2. A unique device identity file
3. A printed QR code for provisioning

## Manufacturing Workflow

### 1. Prepare Base SD Card Image

Flash the base Raspberry Pi OS image and install CrowdCount software:

```bash
# On a reference Pi, run:
cd ~/crowdcount-counter/src/counter-stream
./setup_pi.sh

# Install provisioning services
cd ~/crowdcount-counter/src/provisioning
sudo ./install_services.sh

# Create image backup
sudo dd if=/dev/mmcblk0 of=crowdcount-base-image.img bs=4M status=progress
```

### 2. Customize SD Cards for Each Device

For each device you manufacture:

```bash
# Flash base image to SD card
sudo dd if=crowdcount-base-image.img of=/dev/sdX bs=4M status=progress

# Mount the boot partition
sudo mount /dev/sdX1 /media/boot

# Customize with unique identity (device number 1, 2, 3, ...)
./customize_sd_card.sh 1 /media/boot

# Unmount
sudo umount /media/boot
```

This script will:
- Generate a unique device ID (CC-00001, CC-00002, etc.)
- Generate a random device secret
- Write `/boot/device-identity.conf`
- Generate a QR code PNG file
- Log to `manufacturing_log.csv`

### 3. Print QR Code Labels

QR codes are generated in the `qr_codes/` directory:

```bash
ls qr_codes/
# qr_CC-00001.png
# qr_CC-00002.png
# ...
```

Print these as labels using a label printer:

```bash
# Print all QR codes
for qr in qr_codes/*.png; do
    lpr -P LabelPrinter "$qr"
done
```

Or use a service like Avery labels, Dymo, etc.

**Label specifications:**
- Size: 1" x 1" minimum
- Waterproof/durable material
- High contrast (black on white)

### 4. Assembly

For each device:
1. Insert customized SD card into Raspberry Pi
2. Apply QR code sticker to device case
3. Include backup QR card in product box
4. Perform quality check (boot test)
5. Package and ship

## Manufacturing Log

All manufactured devices are logged in `manufacturing_log.csv`:

```csv
device_id,device_secret,manufacturing_date,serial_number,qr_file
CC-00001,a1b2c3d4e5f6,2024-01-15,SN20240115000001,qr_codes/qr_CC-00001.png
CC-00002,b2c3d4e5f6a7,2024-01-15,SN20240115000002,qr_codes/qr_CC-00002.png
```

**Keep this file secure** - it contains device secrets.

## Quality Assurance

Before shipping, test each device:

```bash
# 1. Boot the device
# 2. Check Bluetooth is advertising
sudo bluetoothctl
scan on
# Should see: CrowdCount-CC-00001

# 3. Scan QR code with test phone
# 4. Provision with test WiFi
# 5. Verify streaming works
# 6. Reset for customer

# Reset provisioning state
sudo rm /boot/provisioned
sudo reboot
```

## Batch Manufacturing

To manufacture multiple devices at once:

```bash
# Customize 10 devices (CC-00001 through CC-00010)
for i in {1..10}; do
    # Mount SD card i
    echo "Insert SD card for device $i, then press Enter"
    read

    # Customize
    ./customize_sd_card.sh $i /media/boot

    # Print QR
    lpr -P LabelPrinter "qr_codes/qr_CC-$(printf '%05d' $i).png"

    # Unmount
    sudo umount /media/boot
done
```

## Security Notes

- Device secrets are randomly generated (128-bit entropy)
- QR codes should be kept with the physical device
- Manufacturing log contains all secrets - **store securely**
- Consider encrypting `manufacturing_log.csv` for long-term storage

## Troubleshooting

**QR code not generating:**
```bash
sudo apt install qrencode
```

**SD card customization fails:**
- Check SD card is mounted: `mount | grep boot`
- Check permissions: `ls -la /media/boot`
- Try manual mount: `sudo mount /dev/sdX1 /media/boot`

**Bluetooth not advertising:**
- Check service is enabled: `systemctl is-enabled crowdcount-provision`
- Check logs: `sudo journalctl -u crowdcount-provision -f`
- Verify identity file exists: `ls -la /boot/device-identity.conf`
