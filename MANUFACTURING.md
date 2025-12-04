# CrowdCount Counter - Manufacturing Guide

Complete guide for manufacturing CrowdCount counter devices using Raspberry Pi Zero 2W.

---

## Quick Start

**For each new device, you only change 4 things:**
1. **Hostname** (5 characters, e.g., `T0001`)
2. **Device Secret** (for Bluetooth pairing)
3. **Device Password** (for SSH access to 'counter' user)
4. **API Password** (for CrowdCount API status updates)

Everything else is identical across all devices!

---

## Hardware Requirements

- **Computer**: Raspberry Pi Zero 2W
- **Camera**: Raspberry Pi Global Shutter Camera
- **Storage**: 16GB+ microSD card (32GB recommended)
- **SD Card Reader**: For flashing from your computer

---

## Manufacturing Process

### Step 1: Create Master Image (One-Time Setup)

**Do this once to create a reusable base image:**

#### 1.1 Flash Base OS
```bash
# Flash Raspberry Pi OS Lite (64-bit) to SD card
# Use Raspberry Pi Imager or:
sudo dd if=raspios-lite-arm64.img of=/dev/sdX bs=4M status=progress
```

#### 1.2 Initial Setup
Boot the Pi and configure:
```bash
# Create 'counter' user
sudo adduser counter
sudo usermod -aG sudo counter

# Set temporary hostname
sudo hostnamectl set-hostname crowdcount-base

# Enable SSH
sudo systemctl enable ssh
sudo systemctl start ssh
```

#### 1.3 Install CrowdCount Software
```bash
# Login as counter user
su - counter

# Clone repository
cd /home/counter
git clone <your-repo-url> crowdcount-counter

# Run complete setup
cd crowdcount-counter
./setup_all.sh
```

This installs:
- Tailscale VPN
- Bluetooth provisioning
- Camera streaming software
- All dependencies
- Systemd services

#### 1.4 Configure Shared Settings

Edit the shared device configuration:
```bash
nano /home/counter/crowdcount-counter/src/counter-stream/device-info.conf
```

Set these values (same for ALL devices):
```ini
SERVER_IP=100.72.64.80           # Your MediaMTX server Tailscale IP
RTSP_PORT=8554
WIDTH=640
HEIGHT=480
FPS=30
API_URL=https://api.crowdcount.tech
```

#### 1.5 Configure Tailscale Auth Key

Add your Tailscale reusable auth key to the device config:
```bash
nano /home/counter/crowdcount-counter/src/counter-stream/device-info.conf
```

Add the auth key (get from https://login.tailscale.com/admin/settings/keys):
```ini
TAILSCALE_AUTH_KEY=tskey-auth-k24oPPsZWg11CNTRL-AQ41WXnhW5eTyyNK8DaC5ezEe5ZkYNri4
```

**How it works:**
- Each device will auto-authenticate on first boot
- The key expires in 90 days (you can't auth NEW devices after expiry)
- Already-authenticated devices continue working forever
- Each device gets its own hostname in Tailscale (T0001, T0002, etc.)

**When the key expires (90 days):**
1. Generate a new reusable key at https://login.tailscale.com/admin/settings/keys
2. Update device-info.conf in your next master image
3. Old devices keep working, new devices use the new key

#### 1.6 Create Master Image
```bash
# Shutdown the Pi
sudo shutdown -h now

# Remove SD card and insert into your computer
# Create the master image:
sudo dd if=/dev/sdX of=crowdcount-master.img bs=4M status=progress

# Compress for storage
gzip crowdcount-master.img

# Result: crowdcount-master.img.gz (reusable for all devices)
```

**Save this file securely - it's your golden master image!**

---

### Step 2: Manufacture New Devices (Repeat for Each Device)

**This is the only process you repeat for each new device:**

#### 2.1 Flash Master Image
```bash
# Insert blank SD card into your computer
# Flash the master image:
gunzip -c crowdcount-master.img.gz | sudo dd of=/dev/sdX bs=4M status=progress
```

#### 2.2 Customize Device Identity

This is the **ONLY** thing that changes per device:

```bash
cd crowdcount-counter/manufacturing

# Run customization script with device-specific values:
./customize_sd_card.sh <device> <hostname> <secret> <device_pass> <api_pass>
```

**Example:**
```bash
./customize_sd_card.sh /dev/sdb T0001 secret123 counter123 apipass123
```

**Parameters:**
- `<device>` - SD card device (e.g., `/dev/sdb`, `/dev/mmcblk0`)
- `<hostname>` - 5-character device ID (e.g., `T0001`, `T0002`)
- `<secret>` - Device secret for Bluetooth provisioning
- `<device_pass>` - SSH password for 'counter' user
- `<api_pass>` - Password for CrowdCount API status updates

The script will:
1. Mount the boot partition
2. Write `/boot/firmware/device-identity.conf` with your values
3. Verify the file
4. Unmount safely

#### 2.3 Eject and Label
```bash
# Safely eject SD card
sudo eject /dev/sdX

# Label the device with its hostname (T0001)
# Print label and attach to Pi case
```

#### 2.4 First Boot Setup
```bash
# Insert SD card into Raspberry Pi Zero 2W
# Power on and wait for boot (about 60 seconds)

# SSH into the device (use your local network or connect display/keyboard)
ssh counter@crowdcount-base  # Still has temporary hostname

# Set the device password (from your customize script)
echo 'counter:counter123' | sudo chpasswd

# Set the correct hostname (from device identity)
sudo hostnamectl set-hostname T0001

# Reboot to apply hostname
sudo reboot
```

#### 2.5 Verify Device
```bash
# After reboot, SSH with new hostname
ssh counter@T0001

# Verify device identity
cat /boot/firmware/device-identity.conf
# Should show: DEVICE_ID=T0001

# Check service is running
sudo systemctl status crowdcount-main

# View live stream logs
sudo journalctl -u crowdcount-main -f
# Should show: "Device identity: T0001"
# Should show: "Streaming started"
```

**Device is ready for deployment!**

---

## Device Identity File Format

Located at: `/boot/firmware/device-identity.conf`

```ini
[DEFAULT]
# Unique device identifier (hostname - 5 characters)
DEVICE_ID=T0001

# Device secret for Bluetooth provisioning pairing
DEVICE_SECRET=secret123

# Device password for 'counter' user SSH access
DEVICE_PASSWORD=counter123

# API password for status updates to CrowdCount API
API_PASSWORD=apipass123

# Manufacturing information (auto-generated)
MANUFACTURING_DATE=2024-12-03
MODEL=counter-v2
HARDWARE_VERSION=1.0
FIRMWARE_VERSION=1.0
SERIAL_NUMBER=SN20241203T0001
```

**This file survives OS reflashes!** This is the key benefit of the boot partition approach.

---

## Device Naming Convention

### Production Devices
**Format**: `T####` (5 characters)
- `T` = Tracker/Counter device type
- `####` = Sequential number, zero-padded

**Examples:**
- `T0001` - First production device
- `T0002` - Second production device
- `T0099` - 99th device
- `T1000` - 1000th device

### Development Devices
Use different prefixes:
- `DEV01` - Development device 1
- `TEST1` - Test device 1

---

## Batch Manufacturing Script

For manufacturing multiple devices at once:

```bash
#!/bin/bash
# batch_manufacture.sh - Manufacture devices T0001 through T0010

for i in {1..10}; do
    DEVICE_ID=$(printf "T%04d" $i)

    echo ""
    echo "================================================"
    echo "Manufacturing device: $DEVICE_ID"
    echo "================================================"
    echo "Insert SD card for $DEVICE_ID and press Enter"
    read

    # Flash master image
    gunzip -c crowdcount-master.img.gz | sudo dd of=/dev/sdb bs=4M status=progress

    # Customize (update passwords as needed)
    ./customize_sd_card.sh /dev/sdb $DEVICE_ID secret${i} counter${i} apipass${i}

    # Eject
    sudo eject /dev/sdb

    echo ""
    echo "Device $DEVICE_ID complete!"
    echo "Remove SD card and label with: $DEVICE_ID"
    echo ""
done
```

---

## Updating Deployed Devices

### Software Updates (Easy!)

Since device identity is on the boot partition, software updates are simple:

```bash
# SSH into device
ssh counter@T0001

# Pull latest code
cd ~/crowdcount-counter
git pull

# Reinstall service if needed
sudo ./install_main_service.sh

# Reboot
sudo reboot
```

**Device identity is preserved!**

### Full OS Reflash (Still Easy!)

Even a complete OS reflash preserves device identity:

```bash
# 1. Remove SD card from device
# 2. Flash new master image
gunzip -c crowdcount-master-v2.img.gz | sudo dd of=/dev/sdX bs=4M

# 3. Boot partition already has device-identity.conf!
#    No need to recustomize - identity survived the reflash!

# 4. Insert and boot - device keeps its identity (T0001)
```

---

## Verification Checklist

Before shipping each device, verify:

- [ ] SD card flashed with master image
- [ ] Device identity written to `/boot/firmware/device-identity.conf`
- [ ] Device password set with `chpasswd`
- [ ] Hostname matches DEVICE_ID
- [ ] Device boots successfully
- [ ] Service auto-starts: `sudo systemctl status crowdcount-main`
- [ ] Correct device ID in logs: `sudo journalctl -u crowdcount-main | grep "Device identity"`
- [ ] Stream appears on MediaMTX server with correct name
- [ ] Camera feed is visible and working
- [ ] Device labeled with hostname

---

## Troubleshooting Manufacturing

### SD Card Won't Mount
```bash
# List available devices
lsblk

# For SD card on /dev/sdb:
# - Partition 1 (/dev/sdb1) = boot (FAT32)
# - Partition 2 (/dev/sdb2) = root (ext4)

# Manual mount if needed:
sudo mkdir -p /mnt/boot
sudo mount /dev/sdb1 /mnt/boot
```

### Device Identity Not Found
```bash
# Check from running Pi
ls -la /boot/firmware/device-identity.conf

# If missing, check alternate locations
ls -la /boot/device-identity.conf

# Fix permissions if needed
sudo chmod 644 /boot/firmware/device-identity.conf
```

### Wrong Hostname After Boot
```bash
# Check current hostname
hostname

# Check what identity file says
cat /boot/firmware/device-identity.conf

# Manually set hostname to match
sudo hostnamectl set-hostname T0001
sudo reboot
```

### Device Not Streaming
```bash
# Check service status
sudo systemctl status crowdcount-main

# View detailed logs
sudo journalctl -u crowdcount-main -f

# Common issues:
# - Tailscale not connected: sudo tailscale status
# - WiFi not connected: nmcli device status
# - Camera not detected: dmesg | grep -i camera
```

---

## Master Image Maintenance

**Update your master image quarterly** with latest software:

1. Boot a device with current master image
2. Update all software:
   ```bash
   cd ~/crowdcount-counter
   git pull
   ./setup_all.sh
   sudo apt update && sudo apt upgrade -y
   ```
3. Create new master image:
   ```bash
   sudo dd if=/dev/mmcblk0 of=crowdcount-master-v2.img bs=4M
   gzip crowdcount-master-v2.img
   ```
4. Test with one device before rolling out to all

---

## Best Practices

1. ✅ Keep master image backed up in multiple locations
2. ✅ Use sequential device IDs for inventory tracking
3. ✅ Document all device passwords in secure database
4. ✅ Test each device before shipping (boot + stream test)
5. ✅ Label devices clearly with hostname
6. ✅ Keep Tailscale auth key for master image creation
7. ✅ Update master image regularly with security patches

---

## Quick Reference Card

**To manufacture one device:**

```bash
# 1. Flash master
gunzip -c crowdcount-master.img.gz | sudo dd of=/dev/sdX bs=4M

# 2. Customize
cd manufacturing
./customize_sd_card.sh /dev/sdX T0001 secret123 counter123 apipass123

# 3. Eject
sudo eject /dev/sdX

# 4. First boot
ssh counter@crowdcount-base
echo 'counter:counter123' | sudo chpasswd
sudo hostnamectl set-hostname T0001
sudo reboot

# 5. Done!
```

---

## Support

For manufacturing issues, check:
- Service logs: `sudo journalctl -u crowdcount-main -f`
- Boot partition: `ls -la /boot/firmware/`
- Device identity: `cat /boot/firmware/device-identity.conf`
- Test identity loading: `cd ~/crowdcount-counter/src/provisioning && python3 device_identity.py`
