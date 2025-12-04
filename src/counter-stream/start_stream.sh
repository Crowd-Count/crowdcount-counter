#!/bin/bash
#
# Start Camera Stream with Device Configuration
# Reads settings from device-info.conf and starts streaming
#

set -e  # Exit on error

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONFIG_FILE="$SCRIPT_DIR/device-info.conf"
STREAM_SCRIPT="$SCRIPT_DIR/stream_to_mediamtx.py"

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

# Function to read config value
get_config_value() {
    local key="$1"
    local default="$2"
    # Read from config, ignore comments and empty lines, get value after =
    local value=$(grep "^${key}=" "$CONFIG_FILE" | cut -d'=' -f2- | tr -d ' ' | head -n1)

    if [ -z "$value" ]; then
        echo "$default"
    else
        echo "$value"
    fi
}

# Read configuration
DEVICE_ID=$(get_config_value "DEVICE_ID" "")
SERVER_IP=$(get_config_value "SERVER_IP" "")
RTSP_PORT=$(get_config_value "RTSP_PORT" "8554")
WIDTH=$(get_config_value "WIDTH" "640")
HEIGHT=$(get_config_value "HEIGHT" "480")
FPS=$(get_config_value "FPS" "30")
PASSWORD=$(get_config_value "PASSWORD" "")
API_URL=$(get_config_value "API_URL" "https://api.crowdcount.tech")

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
if [ -n "$PASSWORD" ]; then
    echo "  Password:     ****"
fi
echo "============================================================"
echo ""

# Build command
# Note: $DEVICE_ID is used as both stream_name (positional arg) and device_id (defaults to stream_name if not specified)
CMD="python3 $STREAM_SCRIPT $SERVER_IP $DEVICE_ID --width $WIDTH --height $HEIGHT --fps $FPS --port $RTSP_PORT"

# Add password if provided
if [ -n "$PASSWORD" ]; then
    CMD="$CMD --password $PASSWORD"
fi

# Add API URL if provided
if [ -n "$API_URL" ]; then
    CMD="$CMD --api-url $API_URL"
fi

# Start streaming
echo "Starting stream..."
echo ""
exec $CMD
