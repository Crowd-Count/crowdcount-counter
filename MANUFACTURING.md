# CrowdCount Counter - Setup Guide

Complete guide for setting up a new CrowdCount counter device from a brand new Raspberry Pi Zero 2W.

---

## Prerequisites

### Hardware Required
- Raspberry Pi Zero 2W
- Raspberry Pi Global Shutter Camera (or compatible camera)
- 16GB+ microSD card (32GB recommended)
- SD card reader for your computer
- USB power supply (5V 2.5A recommended)
- (Optional) Mini HDMI adapter + keyboard for initial setup

### Software Required on Your Computer
- Raspberry Pi Imager (https://www.raspberrypi.com/software/)
- SSH client (built into macOS/Linux, PuTTY on Windows)

### Network Requirements
- WiFi network name and password
- Tailscale account with reusable auth key (https://login.tailscale.com/admin/settings/keys)
- MediaMTX server running on your network (note its Tailscale IP)

---

## Part 1: First-Time Setup (Creating Master Image)

**Do this once to create a reusable base image for all your devices.**

### Step 1.1: Flash Raspberry Pi OS

1. Insert SD card into your computer
2. Open Raspberry Pi Imager
3. Select:
   - **Device**: Raspberry Pi Zero 2W
   - **OS**: Raspberry Pi OS Lite (64-bit) - under "Raspberry Pi OS (other)"
   - **Storage**: Your SD card

4. Click the gear icon (⚙️) for advanced options:
   - **Set hostname**: `crowdcount-base`
   - **Enable SSH**: Yes, with password authentication
   - **Set username**: `counter`
   - **Set password**: `temppass123` (temporary, will be changed per-device)
   - **Configure WiFi**: Enter your WiFi credentials
   - **Set locale**: Your timezone

5. Click **Write** and wait for completion

### Step 1.2: First Boot

1. Insert SD card into Raspberry Pi Zero 2W
2. Connect camera ribbon cable
3. Power on the Pi
4. Wait 2-3 minutes for first boot

5. Find the Pi on your network:
   ```bash
   # On macOS/Linux:
   ping crowdcount-base.local

   # Or scan your network:
   arp -a | grep -i raspberry
   ```

6. SSH into the Pi:
   ```bash
   ssh counter@crowdcount-base.local
   # Password: temppass123
   ```

### Step 1.3: Install CrowdCount Software

Run these commands on the Pi:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install git
sudo apt install -y git

# Clone CrowdCount repository
cd /home/counter
git clone https://github.com/YOUR_ORG/crowdcount-counter.git

# Run the setup script (takes 10-15 minutes)
cd crowdcount-counter
./setup_all.sh
```

The setup script installs:
- FFmpeg, OpenCV, Picamera2 (video)
- Bluetooth/BlueZ (provisioning)
- NetworkManager (WiFi)
- Tailscale VPN
- All Python dependencies
- CrowdCount systemd services

### Step 1.4: Configure Shared Settings

Edit the device configuration (same for ALL devices):

```bash
nano /home/counter/crowdcount-counter/src/counter-stream/device-info.conf
```

Set these values:
```ini
# MediaMTX server Tailscale IP (get from: tailscale status on your server)
SERVER_IP=100.72.64.80

# Video settings (recommended for Pi Zero 2W)
RTSP_PORT=8554
WIDTH=640
HEIGHT=480
FPS=30

# CrowdCount API
API_URL=https://api.crowdcount.tech

# Tailscale auth key (get from: https://login.tailscale.com/admin/settings/keys)
# Create a "Reusable" key, it will work for 90 days
TAILSCALE_AUTH_KEY=tskey-auth-xxxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx
```

Save and exit (Ctrl+X, Y, Enter).

### Step 1.5: Test the Setup

Before creating the master image, test that everything works:

```bash
# Test camera
libcamera-hello --timeout 5000

# Test Tailscale (temporary auth for testing)
sudo tailscale up

# Check service status
sudo systemctl status crowdcount-main
```

### Step 1.6: Create Master Image

Once everything works, create your reusable master image:

```bash
# On the Pi: clean up and shutdown
sudo apt clean
sudo rm -rf /var/cache/apt/archives/*
history -c
sudo shutdown -h now
```

Remove the SD card and insert into your computer:

```bash
# On your computer (Linux/macOS):
# Find your SD card device (BE CAREFUL - wrong device will destroy data!)
lsblk  # or: diskutil list (macOS)

# Create the master image (replace sdX with your device)
sudo dd if=/dev/sdX of=crowdcount-master.img bs=4M status=progress

# Compress for storage (saves ~70% space)
gzip crowdcount-master.img

# Result: crowdcount-master.img.gz (~2GB)
```

**Save this file securely - it's your master image for all devices!**

---

## Part 2: Manufacturing New Devices

**Repeat this for each new counter device.**

### Step 2.1: Flash Master Image to New SD Card

```bash
# Insert blank SD card
# Find device name
lsblk  # Linux
diskutil list  # macOS

# Flash master image (replace /dev/sdX with your device)
gunzip -c crowdcount-master.img.gz | sudo dd of=/dev/sdX bs=4M status=progress

# Sync and wait
sync
```

### Step 2.2: Customize Device Identity

Each device needs a unique identity. Run the customization script:

```bash
cd crowdcount-counter/manufacturing

# Usage: ./customize_sd_card.sh <device> <hostname> <secret> <device_pass> <api_pass>
./customize_sd_card.sh /dev/sdX T0001 mysecret123 mypassword123 myapipass123
```

**Parameters:**
| Parameter | Description | Example |
|-----------|-------------|---------|
| `device` | SD card device | `/dev/sdb` or `/dev/mmcblk0` |
| `hostname` | 5-char device ID | `T0001`, `T0002`, etc. |
| `secret` | Bluetooth pairing secret | `mysecret123` |
| `device_pass` | SSH password for 'counter' user | `mypassword123` |
| `api_pass` | CrowdCount API password | `myapipass123` |

The script creates `/boot/firmware/device-identity.conf` with your values.

### Step 2.3: Eject SD Card

```bash
# Safely eject
sudo eject /dev/sdX  # Linux
diskutil eject /dev/diskN  # macOS

# Label the SD card or Pi case with: T0001
```

### Step 2.4: First Boot of New Device

1. Insert SD card into new Raspberry Pi Zero 2W
2. Connect camera
3. Power on
4. Wait 2-3 minutes for boot

5. SSH into the device:
   ```bash
   # Initially uses base hostname
   ssh counter@crowdcount-base.local
   # Password: temppass123 (from master image)
   ```

6. Set the device password and hostname:
   ```bash
   # Set device password (use same as device_pass from Step 2.2)
   echo 'counter:mypassword123' | sudo chpasswd

   # Set hostname to match device ID
   sudo hostnamectl set-hostname T0001

   # Reboot to apply
   sudo reboot
   ```

### Step 2.5: Verify Device

After reboot:

```bash
# SSH with new hostname
ssh counter@T0001.local
# Or via Tailscale: ssh counter@T0001

# Verify device identity
cat /boot/firmware/device-identity.conf

# Check service is running
sudo systemctl status crowdcount-main

# Watch live logs
sudo journalctl -u crowdcount-main -f
```

**Expected log output:**
```
✓ Loaded device identity: T0001
✓ Tailscale authenticated as T0001
STARTING STREAMING MODE
✓ Modern camera (libcamera) initialized: 640x480@30fps
▶ Streaming started
```

**Device is ready for deployment!**

---

## Part 3: Quick Reference

### Manufacturing Checklist

For each new device:

- [ ] Flash master image to SD card
- [ ] Run `customize_sd_card.sh` with unique values
- [ ] First boot and SSH in
- [ ] Set password: `echo 'counter:PASSWORD' | sudo chpasswd`
- [ ] Set hostname: `sudo hostnamectl set-hostname T0001`
- [ ] Reboot: `sudo reboot`
- [ ] Verify: `sudo systemctl status crowdcount-main`
- [ ] Label device with hostname

### Naming Convention

| Format | Use Case | Examples |
|--------|----------|----------|
| `T####` | Production devices | T0001, T0002, T0099 |
| `DEV##` | Development | DEV01, DEV02 |
| `TEST#` | Testing | TEST1, TEST2 |

### Device Identity File

Location: `/boot/firmware/device-identity.conf`

```ini
[DEFAULT]
DEVICE_ID=T0001
DEVICE_SECRET=mysecret123
DEVICE_PASSWORD=mypassword123
API_PASSWORD=myapipass123
MANUFACTURING_DATE=2024-12-09
MODEL=counter-v2
```

**This file survives OS reflashes** - it's on the boot partition.

---

## Part 4: Troubleshooting

### Device Won't Boot

1. Check SD card is fully inserted
2. Check power supply (5V 2.5A minimum)
3. Try re-flashing the SD card

### Can't SSH Into Device

```bash
# Check if device is on network
ping crowdcount-base.local  # or T0001.local after setup

# Check your WiFi credentials in Raspberry Pi Imager settings
# Try connecting monitor/keyboard directly
```

### Service Not Running

```bash
# Check status
sudo systemctl status crowdcount-main

# View logs
sudo journalctl -u crowdcount-main -f

# Common fixes:
sudo systemctl restart crowdcount-main
```

### Camera Not Detected

```bash
# Check camera connection
libcamera-hello --timeout 5000

# Check kernel messages
dmesg | grep -i camera

# Verify camera is enabled
sudo raspi-config  # Interface Options > Camera
```

### Tailscale Not Connecting

```bash
# Check Tailscale status
tailscale status

# Re-authenticate manually
sudo tailscale up

# Check auth key in device-info.conf
cat /home/counter/crowdcount-counter/src/counter-stream/device-info.conf | grep TAILSCALE
```

### Stream Not Showing on Server

```bash
# Check if stream is running
sudo journalctl -u crowdcount-main -f

# Verify server IP
cat /home/counter/crowdcount-counter/src/counter-stream/device-info.conf | grep SERVER_IP

# Test network connectivity
ping <SERVER_IP>
```

### Reset Device to Re-Provision

```bash
# Remove provisioning flag
sudo rm /boot/firmware/provisioned

# Reboot - device will enter provisioning mode
sudo reboot
```

---

## Part 5: Updating Deployed Devices

### Software Update (SSH)

```bash
ssh counter@T0001

cd ~/crowdcount-counter
git pull

# Reinstall service if needed
sudo ./install_main_service.sh

sudo reboot
```

### Full OS Reflash (Preserves Identity)

The device identity file is on the boot partition, so it survives reflashing:

```bash
# Flash new master image
gunzip -c crowdcount-master-v2.img.gz | sudo dd of=/dev/sdX bs=4M

# Device identity is preserved - no need to reconfigure!
```

---

## Part 6: Batch Manufacturing

For manufacturing multiple devices at once:

```bash
#!/bin/bash
# batch_manufacture.sh

for i in {1..10}; do
    DEVICE_ID=$(printf "T%04d" $i)
    SECRET="secret${i}"
    PASS="counter${i}"
    API="apipass${i}"

    echo "=== Manufacturing $DEVICE_ID ==="
    echo "Insert SD card and press Enter..."
    read

    # Flash
    gunzip -c crowdcount-master.img.gz | sudo dd of=/dev/sdb bs=4M status=progress

    # Customize
    ./customize_sd_card.sh /dev/sdb $DEVICE_ID $SECRET $PASS $API

    # Eject
    sudo eject /dev/sdb

    echo "Done! Label device: $DEVICE_ID"
    echo ""
done
```

---

## Part 7: Useful Commands

```bash
# Service management
sudo systemctl status crowdcount-main
sudo systemctl restart crowdcount-main
sudo systemctl stop crowdcount-main

# View logs
sudo journalctl -u crowdcount-main -f      # Live logs
sudo journalctl -u crowdcount-main -n 100  # Last 100 lines

# Check device identity
cat /boot/firmware/device-identity.conf

# Check Tailscale
tailscale status
tailscale ip

# Test camera
libcamera-hello --timeout 5000

# Manual stream test
cd ~/crowdcount-counter/src/counter-stream
./start_stream.sh

# Network status
nmcli device status
ip addr
```
