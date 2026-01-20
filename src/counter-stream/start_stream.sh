#!/bin/bash
#
# Start Camera Stream with Device Configuration
# Reads device identity from boot partition and settings from device-info.conf
#

set -e  # Exit on error

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONFIG_FILE="$SCRIPT_DIR/device-info.conf"
STREAM_SCRIPT="$SCRIPT_DIR/stream_to_mediamtx.py"

# Device identity file locations (priority order)
# Priority 1: Boot partition (production - survives OS reflash)
# Priority 2: Legacy boot partition (older Pi models)
# Priority 3: Project directory (development fallback)
IDENTITY_LOCATIONS=(
    "/boot/firmware/device-identity.conf"
    "/boot/device-identity.conf"
    "$SCRIPT_DIR/../../boot/device-identity.conf"
)

echo "============================================================"
echo "Starting Camera Stream"
echo "============================================================"

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "✗ Error: Configuration file not found: $CONFIG_FILE"
    echo ""
    if [ -f "$SCRIPT_DIR/device-info.conf.template" ]; then
        echo "To create your configuration file, run:"
        echo "  cp $SCRIPT_DIR/device-info.conf.template $CONFIG_FILE"
        echo "  nano $CONFIG_FILE"
        echo ""
        echo "Then edit the settings for your device."
    else
        echo "Please create device-info.conf with your device settings."
    fi
    exit 1
fi

# Check if stream script exists
if [ ! -f "$STREAM_SCRIPT" ]; then
    echo "✗ Error: Stream script not found: $STREAM_SCRIPT"
    exit 1
fi

# Function to read config value from a file
get_config_value() {
    local key="$1"
    local default="$2"
    local file="${3:-$CONFIG_FILE}"
    # Read from config, ignore comments and empty lines, get value after =
    local value=$(grep "^${key}=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d ' ' | head -n1)

    if [ -z "$value" ]; then
        echo "$default"
    else
        echo "$value"
    fi
}

# Find and read device identity file (priority order)
IDENTITY_FILE=""
DEVICE_ID=""

for location in "${IDENTITY_LOCATIONS[@]}"; do
    if [ -f "$location" ]; then
        DEVICE_ID=$(get_config_value "DEVICE_ID" "" "$location")
        if [ -n "$DEVICE_ID" ]; then
            IDENTITY_FILE="$location"
            echo "✓ Device identity: $DEVICE_ID"
            echo "  Source: $IDENTITY_FILE"
            break
        fi
    fi
done

# Fallback to device-info.conf if no identity file found
if [ -z "$DEVICE_ID" ]; then
    echo "⚠ Warning: No device identity file found"
    echo "  Checked: ${IDENTITY_LOCATIONS[*]}"
    echo "  Device will not work without proper identity configuration!"
    exit 1
fi

# Read API password from device identity file
API_PASSWORD=$(get_config_value "API_PASSWORD" "" "$IDENTITY_FILE")

# Read remaining configuration from device-info.conf
SERVER_IP=$(get_config_value "SERVER_IP" "")
USE_DEV_SERVER=$(get_config_value "USE_DEV_SERVER" "false")
WIDTH=$(get_config_value "WIDTH" "640")
HEIGHT=$(get_config_value "HEIGHT" "480")
FPS=$(get_config_value "FPS" "30")
API_URL=$(get_config_value "API_URL" "https://api.crowdcount.tech")

# Set ports based on USE_DEV_SERVER toggle
# Production: RTSP 8554, API 5000
# Development: RTSP 8555, API 5001
if [ "$USE_DEV_SERVER" = "true" ]; then
    RTSP_PORT=8555
    ORCHESTRATOR_PORT=5001
    echo "Using DEVELOPMENT server (ports: RTSP=$RTSP_PORT, API=$ORCHESTRATOR_PORT)"
else
    RTSP_PORT=8554
    ORCHESTRATOR_PORT=5000
    echo "Using PRODUCTION server (ports: RTSP=$RTSP_PORT, API=$ORCHESTRATOR_PORT)"
fi

# Validate required settings
if [ -z "$DEVICE_ID" ]; then
    echo "✗ Error: DEVICE_ID is not set in $CONFIG_FILE"
    exit 1
fi

if [ -z "$SERVER_IP" ]; then
    echo "✗ Error: SERVER_IP is not set in $CONFIG_FILE"
    exit 1
fi

# Display configuration
echo "Configuration:"
echo "  Device ID:    $DEVICE_ID"
echo "  Server IP:    $SERVER_IP"
echo "  RTSP Port:    $RTSP_PORT"
echo "  Resolution:   ${WIDTH}x${HEIGHT}"
echo "  Frame Rate:   ${FPS} fps"
if [ -n "$API_PASSWORD" ]; then
    echo "  API Password: ****"
fi
echo "============================================================"
echo ""

# Build command
# Note: $DEVICE_ID is used as both stream_name (positional arg) and device_id (defaults to stream_name if not specified)
CMD="python3 $STREAM_SCRIPT $SERVER_IP $DEVICE_ID --width $WIDTH --height $HEIGHT --fps $FPS --port $RTSP_PORT --orchestrator-port $ORCHESTRATOR_PORT"

# Add API password if provided
if [ -n "$API_PASSWORD" ]; then
    CMD="$CMD --password $API_PASSWORD"
fi

# Add API URL if provided
if [ -n "$API_URL" ]; then
    CMD="$CMD --api-url $API_URL"
fi

# Start streaming
echo "Starting stream..."
echo ""
exec $CMD
