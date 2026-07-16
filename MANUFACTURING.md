# CrowdCount Counter - Manufacturing Guide

Complete guide for setting up and mass-producing CrowdCount counter devices on Raspberry Pi Zero 2W.

**Manufacturing flow:** Create master image once, then for each device: insert SD card, run one script, eject, boot. No SSH needed.

---

## Prerequisites

### Hardware Required
- Raspberry Pi Zero 2W
- Raspberry Pi Global Shutter Camera (or compatible camera)
- 16GB+ microSD card (32GB recommended)
- SD card reader for your Mac
- USB power supply (5V 2.5A recommended)

### Software Required on Your Mac
- Raspberry Pi Imager (https://www.raspberrypi.com/software/)
- `qrencode` — install with `brew install qrencode`

### Network Requirements
- WiFi network name and password
- Tailscale account with reusable auth key (https://login.tailscale.com/admin/settings/keys)
- MediaMTX server running on your network (note its Tailscale IP)

---

## Part 1: Creating the Master Image (One-Time Setup)

**Do this once. The result is `crowdcount-master.img.gz` — used to flash every device.**

### Step 1.1: Flash Raspberry Pi OS

1. Insert SD card into your computer
2. Open Raspberry Pi Imager
3. Select:
   - **Device**: Raspberry Pi Zero 2W
   - **OS**: Raspberry Pi OS Lite (64-bit) — under "Raspberry Pi OS (other)"
   - **Storage**: Your SD card

4. Click the gear icon for advanced options:
   - **Set hostname**: `crowdcount-base`
   - **Enable SSH**: Yes, with password authentication
   - **Set username**: `counter`
   - **Set password**: `temppass123` (temporary, overwritten per-device by firstboot)
   - **Configure WiFi**: Enter your WiFi credentials
   - **Set locale**: Your timezone

5. Click **Write** and wait for completion

### Step 1.2: First Boot & SSH In

1. Insert SD card into Pi, connect camera, power on
2. Wait 2-3 minutes for first boot
3. SSH in:
   ```bash
   ssh counter@crowdcount-base.local
   # Password: temppass123
   ```

### Step 1.3: Install CrowdCount Software

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git

cd /home/counter
git clone https://github.com/YOUR_ORG/crowdcount-counter.git
cd crowdcount-counter
./setup_all.sh
```

This installs everything: camera deps, Bluetooth, Tailscale, Python packages, and all systemd services (main, updater, firstboot).

### Step 1.4: Configure Shared Settings

Edit the device configuration (same for ALL devices):

```bash
nano /home/counter/crowdcount-counter/src/counter-stream/device-info.conf
```

```ini
SERVER_IP=100.72.64.80
RTSP_PORT=8554
WIDTH=640
HEIGHT=480
FPS=30
API_URL=https://api.crowdcount.tech
UPSTREAM_API_URL=https://api.upstreamcv.com
TAILSCALE_AUTH_KEY=tskey-auth-xxxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx
```

`UPSTREAM_API_URL` is the Upstream control plane, used only by devices that
resolve to SRT mode. It is safe to ship on every device: the per-device
credential that actually enables SRT (`UPSTREAM_API_TOKEN`) is stamped into
`device-identity.conf` per device, never here.

### Step 1.5: Set Up Deploy Key (for Private Repo Auto-Updates)

The updater service needs to `git pull` from a private GitHub repo. Generate a deploy key that will be baked into the master image.

**On the Pi:**

```bash
# Generate an SSH keypair (no passphrase)
ssh-keygen -t ed25519 -C "crowdcount-deploy" -f /home/counter/.ssh/crowdcount_deploy -N ""

# Configure SSH to use this key for GitHub
cat >> /home/counter/.ssh/config <<'EOF'
Host github.com
    HostName github.com
    User git
    IdentityFile /home/counter/.ssh/crowdcount_deploy
    IdentitiesOnly yes
EOF

chmod 600 /home/counter/.ssh/config

# Display the public key
cat /home/counter/.ssh/crowdcount_deploy.pub
```

**On GitHub:**

1. Go to your repo Settings > Deploy keys
2. Click "Add deploy key"
3. Title: `CrowdCount Devices`
4. Paste the public key from above
5. Leave "Allow write access" **unchecked** (read-only)
6. Click "Add key"

**Back on the Pi — switch remote to SSH:**

```bash
cd /home/counter/crowdcount-counter
git remote set-url origin git@github.com:YOUR_ORG/crowdcount-counter.git

# Test it works
git fetch origin main
```

### Step 1.6: Test Everything

```bash
# Test camera
libcamera-hello --timeout 5000

# Test Tailscale
sudo tailscale up

# Check services
sudo systemctl status crowdcount-main
sudo systemctl status crowdcount-updater
sudo systemctl status crowdcount-firstboot

# Test git pull (deploy key)
cd /home/counter/crowdcount-counter
git fetch origin main
```

### Step 1.7: Create the Master Image

```bash
# On the Pi: clean up

# Clear WiFi credentials (prevent clones auto-connecting to master's WiFi)
sudo rm -f /boot/firmware/wifi-credentials.conf
sudo rm -f /boot/wifi-credentials.conf

# Clear NetworkManager saved connections
sudo rm -f /etc/NetworkManager/system-connections/*

# Clear provisioning and firstboot markers
sudo rm -f /boot/firmware/.firstboot-done
sudo rm -f /boot/firmware/.ssh-hardened
sudo rm -f /boot/firmware/provisioned

sudo apt clean
sudo rm -rf /var/cache/apt/archives/*
history -c
sudo shutdown -h now
```

Remove the SD card, insert into your Mac:

```bash
# Find your SD card
diskutil list

# Create the master image (replace diskN with your disk)
sudo dd if=/dev/rdiskN bs=4m status=progress | gzip > crowdcount-master.img.gz

# Result: crowdcount-master.img.gz (~2GB)
```

Move `crowdcount-master.img.gz` into the `crowdcount-counter/` directory (the flash script looks there by default).

---

## Part 2: Manufacturing Devices (Per Device)

**For each device: one command, no SSH.**

### The One-Command Flow

```bash
cd crowdcount-counter
./manufacturing/flash_device.sh
```

The script will:
1. Prompt you for: Device ID, Bluetooth secret, SSH password, API password
2. Show you available disks, ask you to confirm the SD card
3. Flash the master image (~2 min)
4. Mount the boot partition and write `device-identity.conf`
5. Generate a QR code for the device
6. Eject the SD card

**That's it.** Insert the SD card into a Pi, power on, and it's fully operational:
- Hostname is auto-set to the Device ID
- Password is auto-set from identity file
- All services start automatically
- No SSH required

### What Happens on First Boot

The `crowdcount-firstboot` service runs once (before `crowdcount-main`) and:
1. Reads `/boot/firmware/device-identity.conf`
2. Sets the OS hostname to `DEVICE_ID`
3. Sets the `counter` user password to `DEVICE_PASSWORD`
4. Creates `/boot/firmware/.firstboot-done` marker (so it never runs again)

Then `crowdcount-main` starts normally — Tailscale auth, streaming, etc.

### Verify a Device (Optional)

After the Pi boots (~2-3 minutes):

```bash
ssh counter@T0005.local
# Password: (what you entered during flash)

sudo systemctl status crowdcount-main
sudo journalctl -u crowdcount-firstboot   # Should show hostname/password set
```

---

## Part 3: Quick Reference

### Manufacturing Checklist (Per Device)

- [ ] Insert SD card into Mac
- [ ] Run `./manufacturing/flash_device.sh`
- [ ] Enter device credentials when prompted
- [ ] Wait for flash + eject (~2 min)
- [ ] Insert SD card into Pi, power on
- [ ] Stick QR code label on device
- [ ] (Optional) Verify via SSH

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
DEVICE_SECRET=<bluetooth pairing secret>
DEVICE_PASSWORD=<ssh password for the counter user>
API_PASSWORD=<crowdcount api password>
MANUFACTURING_DATE=2025-01-15
MODEL=counter-v3
HARDWARE_VERSION=1.0
FIRMWARE_VERSION=1.0
SERIAL_NUMBER=SN20250115T0001

# Optional, written only when supplied:
UPSTREAM_API_TOKEN=<per-device upstream token>
UPDATE_BRANCH=<branch the auto-updater tracks>
```

This file is on the boot partition and survives OS reflashes.

**`UPSTREAM_API_TOKEN`** enables SRT streaming to Upstream (see
[Streaming Modes](README.md#streaming-modes)). It is minted per device with
`scope=device` and binds to that device's Upstream agent on first register
(trust-on-first-use), so a token stolen from one device cannot register as
another. A device without it always streams legacy RTSP, whatever its
`streaming_mode` flag says — this is the outer safety catch on the Upstream
cutover, so only stamp it on devices intended for Upstream. `flash_device.sh`
does not prompt for it; pass it as the 6th argument to `customize_sd_card.sh`
(see that script's usage).

**`UPDATE_BRANCH`** pins the auto-updater to a branch; absent means `main`,
the fleet deploy. Only bench/canary units should set it. **A device pinned to a
feature branch must be moved back to `main` *before* that branch is deleted** —
otherwise its updater fetch fails silently and it stops receiving updates
entirely.

### Files Overview

| File | Where It Runs | Purpose |
|------|---------------|---------|
| `manufacturing/flash_device.sh` | Your Mac | One-command flash + identity stamp + QR |
| `manufacturing/customize_sd_card.sh` | Your Mac | Standalone identity writer (used by flash_device.sh internally or solo) |
| `manufacturing/generate_qr_from_identity.sh` | Your Mac | Standalone QR generator |
| `crowdcount-firstboot.py` | Pi (first boot) | Auto-sets hostname + password from identity file |
| `crowdcount-firstboot.service` | Pi (systemd) | Runs firstboot.py once before main service |
| `install_firstboot_service.sh` | Pi (setup) | Installs the firstboot systemd service |

---

## Part 4: Troubleshooting

### Device Won't Boot

1. Check SD card is fully inserted
2. Check power supply (5V 2.5A minimum)
3. Try re-flashing the SD card

### Hostname Not Set After Boot

```bash
# Check firstboot service
sudo journalctl -u crowdcount-firstboot

# Check if identity file exists
cat /boot/firmware/device-identity.conf

# Check if marker was created prematurely
ls -la /boot/firmware/.firstboot-done

# To re-run firstboot:
sudo rm /boot/firmware/.firstboot-done
sudo systemctl restart crowdcount-firstboot
```

### Can't SSH Into Device

```bash
# Try the original hostname (if firstboot didn't run)
ssh counter@crowdcount-base.local

# Or try by IP
ping crowdcount-base.local
```

### Service Not Running

```bash
sudo systemctl status crowdcount-main
sudo journalctl -u crowdcount-main -f
sudo systemctl restart crowdcount-main
```

### Camera Not Detected

```bash
libcamera-hello --timeout 5000
dmesg | grep -i camera
```

### Auto-Updater Can't Pull (Deploy Key)

```bash
# Test SSH to GitHub
ssh -T git@github.com

# Check key exists
ls -la /home/counter/.ssh/crowdcount_deploy

# Check SSH config
cat /home/counter/.ssh/config

# Manual pull test
cd /home/counter/crowdcount-counter
git fetch origin main
```

### Reset Device to Re-Provision

```bash
# Remove provisioning flag
sudo rm /boot/firmware/provisioned

# To re-run firstboot (re-apply hostname/password)
sudo rm /boot/firmware/.firstboot-done

sudo reboot
```

---

## Part 5: Updating Deployed Devices

### Automatic Updates (Deploy Key)

The `crowdcount-updater` service runs automatically and will:
- Check for git updates periodically
- Pull new code and restart `crowdcount-main` if updated
- Works because the deploy key is baked into the master image

### Manual Update via SSH

```bash
ssh counter@T0001
cd ~/crowdcount-counter
git pull
sudo ./install_main_service.sh  # if service file changed
sudo reboot
```

### Full OS Reflash (Preserves Identity)

The identity file is on the boot partition, so it survives reflashing:

```bash
# Re-flash with new master image
./manufacturing/flash_device.sh
# The script will write a fresh identity file
```

---

## Part 6: Useful Commands

```bash
# Service management
sudo systemctl status crowdcount-main
sudo systemctl status crowdcount-firstboot
sudo systemctl status crowdcount-updater

# View logs
sudo journalctl -u crowdcount-main -f
sudo journalctl -u crowdcount-firstboot
sudo journalctl -u crowdcount-updater -n 50

# Check device identity
cat /boot/firmware/device-identity.conf

# Tailscale
tailscale status
tailscale ip

# Camera
libcamera-hello --timeout 5000

# Network
nmcli device status
ip addr
```
