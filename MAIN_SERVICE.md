# CrowdCount Main Service

The CrowdCount Main Service is an orchestrator that automatically manages device provisioning and streaming based on network connectivity.

## Overview

The main service intelligently decides whether to run provisioning or streaming mode:

- **No WiFi Connection** → Starts Bluetooth provisioning and waits for configuration
- **WiFi Connected + Provisioned** → Starts camera streaming to server
- **WiFi Connected + Not Provisioned** → Completes provisioning setup

## Architecture

### Files

- **`crowdcount-main.py`** - Main orchestrator script
- **`crowdcount-main.service`** - Systemd service definition
- **`install_main_service.sh`** - Installation script

### How It Works

```
Boot
  ↓
Main Service Starts
  ↓
Check WiFi Connected?
  ↓
NO → Start Provisioning (Bluetooth)
  ↓     ↓
  ↓   Wait for User to Configure
  ↓     ↓
  ↓   WiFi Configured
  ↓     ↓
  ←-----┘
YES
  ↓
Check Provisioned?
  ↓
YES → Start Streaming
  ↓
Stream Runs Continuously
```

## Installation

Run the installation script on your Raspberry Pi:

```bash
cd /home/pi/crowdcount-counter
sudo ./install_main_service.sh
```

This will:
1. Make the main script executable
2. Disable old individual services (if present)
3. Install the systemd service
4. Enable auto-start on boot

## Usage

### Start the Service

```bash
sudo systemctl start crowdcount-main
```

### Check Status

```bash
sudo systemctl status crowdcount-main
```

### View Live Logs

```bash
sudo journalctl -u crowdcount-main -f
```

### Stop the Service

```bash
sudo systemctl stop crowdcount-main
```

### Disable Auto-Start

```bash
sudo systemctl disable crowdcount-main
```

## Behavior

### First Boot (No WiFi)

1. Main service starts
2. Detects no WiFi connection
3. Starts Bluetooth provisioning
4. Waits for user to provide WiFi credentials via app
5. Once provisioned, automatically switches to streaming

### Subsequent Boots (WiFi Available)

1. Main service starts
2. Detects WiFi connection
3. Verifies device is provisioned
4. Starts camera streaming immediately

### Re-Provisioning

To re-provision a device:

```bash
# Remove provisioning flag
sudo rm /boot/provisioned /boot/firmware/provisioned 2>/dev/null || true

# Remove device config
sudo rm /home/pi/crowdcount-counter/src/counter-stream/device-info.conf

# Restart service
sudo systemctl restart crowdcount-main
```

Or disconnect from WiFi and restart the service.

## Troubleshooting

### Service Won't Start

Check logs:
```bash
sudo journalctl -u crowdcount-main -n 50
```

Verify files exist:
```bash
ls -la /home/pi/crowdcount-counter/crowdcount-main.py
ls -la /etc/systemd/system/crowdcount-main.service
```

### Provisioning Loop

If device keeps entering provisioning mode:
1. Check WiFi credentials are correct
2. Verify provisioning completed successfully
3. Check for provisioning flag: `ls /boot/provisioned /boot/firmware/provisioned`
4. Check for device config: `ls /home/pi/crowdcount-counter/src/counter-stream/device-info.conf`

### Streaming Won't Start

Ensure:
1. Device is provisioned: `ls /boot/provisioned /boot/firmware/provisioned`
2. Device config exists: `cat /home/pi/crowdcount-counter/src/counter-stream/device-info.conf`
3. WiFi is connected: `iwgetid`
4. Server is reachable: `ping <server-ip>`

## Comparison with Individual Services

### Old Approach (Manual)

```
crowdcount-provision.service  → Only runs if NOT provisioned
crowdcount-stream.service     → Only runs if provisioned
```

**Limitation**: Static conditions, doesn't handle dynamic WiFi changes

### New Approach (Main Service)

```
crowdcount-main.service     → Runs always, decides dynamically
  ↓
  ├─ Provisioning (when needed)
  └─ Streaming (when ready)
```

**Advantages**:
- Single service to manage
- Dynamic decision-making
- Handles WiFi changes automatically
- Cleaner service management
- Automatic retry on failure

## Integration with Existing Components

The main service uses the existing provisioning and streaming components:

- **Provisioning**: `src/provisioning/provision_manager.py`
- **Streaming**: `src/counter-stream/start_stream.sh`

No changes needed to these components - the main service acts as a wrapper.
