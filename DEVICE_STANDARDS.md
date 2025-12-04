# CrowdCount Counter - Device Standards

## Standard Configuration

**All CrowdCount counter devices MUST follow this standard configuration:**

### User Account
- **Username**: `counter` (fixed, never changes)
- **Home Directory**: `/home/counter`

### Hostname
- **Format**: Device ID (e.g., `T0002`, `T0001`, `CC-001`, etc.)
- **Example**: If device ID is `T0002`, hostname should be `T0002`

### Device Format
- **SSH Format**: `counter@T0002`
- **Full Example**: `ssh counter@T0002` or `counter@192.168.1.100`

### Installation Directory
- **Path**: `/home/counter/crowdcount-counter` (fixed)
- **All devices**: Same path on every device for consistency

## Why This Standard?

1. **Consistency**: Every device is configured identically
2. **Easy Deployment**: Same scripts work on all devices
3. **Simplified Troubleshooting**: Always know where to look
4. **Manufacturing**: Can be automated with standard image
5. **Remote Management**: Predictable paths for remote updates

## Directory Structure

```
/home/counter/
└── crowdcount-counter/
    ├── crowdcount-main.py          # Main orchestrator
    ├── crowdcount-main.service     # Systemd service template
    ├── install_main_service.sh     # Service installer
    ├── setup_all.sh                # One-command setup
    ├── boot/                       # Boot configuration
    ├── src/
    │   ├── provisioning/           # WiFi provisioning via Bluetooth
    │   └── counter-stream/         # Video streaming
    │       ├── stream_to_mediamtx.py
    │       ├── start_stream.sh
    │       └── device-info.conf    # Device-specific config
    └── manufacturing/              # Manufacturing tools
```

## Device Identity File

**Location**: `/boot/firmware/device-identity.conf` (persists across SD card reflashes)

**Format**:
```ini
[DEFAULT]
DEVICE_ID=T0002
DEVICE_SECRET=randomly-generated-secret-here
MANUFACTURING_DATE=2024-12-04
MODEL=counter-v2
```

**Purpose**:
- Created during manufacturing
- Persists in boot partition
- Used for device identification and authentication

## Device Configuration File

**Location**: `/home/counter/crowdcount-counter/src/counter-stream/device-info.conf`

**Required Settings**:
```ini
DEVICE_ID=T0002
SERVER_IP=100.72.64.80
PASSWORD=device_api_password
```

**Purpose**:
- Runtime configuration
- Streaming settings
- API credentials

## Service Configuration

**Service File**: `/etc/systemd/system/crowdcount-main.service`

**Key Settings**:
```ini
User=root
WorkingDirectory=/home/counter/crowdcount-counter
ExecStart=/usr/bin/python3 /home/counter/crowdcount-counter/crowdcount-main.py
```

**Enabled Services**:
- `tailscaled.service` - VPN connectivity
- `bluetooth.service` - WiFi provisioning
- `crowdcount-main.service` - Main application

## Network Configuration

### Tailscale
- All devices join the same Tailnet
- Each device gets a unique Tailscale IP (100.x.x.x)
- Hostname visible in Tailscale admin console

### WiFi
- Configured via Bluetooth provisioning on first boot (if no WiFi)
- Or pre-configured during manufacturing
- Managed by NetworkManager

## Device Naming Convention

### Hostname/Device ID Format

**Production Devices**:
- Format: `T####` (e.g., `T0001`, `T0002`, `T0123`)
- `T` = "Tracker" or device type prefix
- `####` = Sequential number (zero-padded to 4 digits)

**Development Devices**:
- Format: `DEV-####` or `TEST-####`
- Clearly distinguishable from production

**Special Purpose**:
- Format: `CC-####` for CrowdCount branded devices
- Custom formats as needed

## Manufacturing Process

### Standard SD Card Image

1. **Base Image**:
   - Raspberry Pi OS (Bookworm or later)
   - Username: `counter`
   - Hostname: `crowdcount-default` (to be changed)

2. **Pre-installed**:
   - All dependencies via `setup_all.sh`
   - Services enabled
   - Directory structure in place

3. **Per-Device Customization**:
   ```bash
   # Set hostname to device ID
   sudo hostnamectl set-hostname T0002

   # Create device identity
   sudo nano /boot/firmware/device-identity.conf

   # Configure device settings
   nano /home/counter/crowdcount-counter/src/counter-stream/device-info.conf
   ```

4. **First Boot**:
   - Tailscale authentication
   - WiFi provisioning (if needed)
   - Device automatically starts streaming

## Deployment Checklist

- [ ] Username is `counter`
- [ ] Hostname matches device ID
- [ ] Files installed at `/home/counter/crowdcount-counter`
- [ ] Device identity file created in `/boot/firmware/`
- [ ] Device config file configured with correct SERVER_IP and PASSWORD
- [ ] `setup_all.sh` has been run successfully
- [ ] All services enabled: `tailscaled`, `bluetooth`, `crowdcount-main`
- [ ] Tailscale authenticated
- [ ] Device boots and auto-starts streaming

## Verification Commands

```bash
# Verify user
whoami
# Should output: counter

# Verify hostname
hostname
# Should output: T0002 (or your device ID)

# Verify installation directory
ls /home/counter/crowdcount-counter/crowdcount-main.py
# Should exist

# Verify services
sudo systemctl is-enabled tailscaled bluetooth crowdcount-main
# All should output: enabled

# Verify service status
sudo systemctl status crowdcount-main
# Should be: active (running)

# Verify Tailscale
tailscale status
# Should show connected status and Tailnet peers
```

## Non-Standard Configurations

**Not Recommended**: Different username, different paths, different service names

**If Absolutely Required**:
- Update all references in service files
- Update install scripts
- Document deviations clearly
- Test thoroughly

**Standard configuration is strongly recommended for:**
- Easier support
- Simplified updates
- Manufacturing consistency
- Remote management

## Support

For devices following this standard:
- Support is streamlined
- Scripts work out of the box
- Documentation is accurate
- Troubleshooting is predictable

For non-standard devices:
- Custom troubleshooting required
- Scripts may need modification
- Documentation may not apply
