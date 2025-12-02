#!/bin/bash
#
# Raspberry Pi Camera Streamer Setup Script
# This script installs all necessary dependencies for streaming to MediaMTX
#

set -e  # Exit on error

echo "============================================================"
echo "Raspberry Pi Camera Streamer - Setup Script"
echo "============================================================"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Please do not run this script as root or with sudo."
    echo "The script will prompt for sudo when needed."
    exit 1
fi

# Update package list
echo "Step 1/4: Updating package list..."
sudo apt update

# Install FFmpeg
echo ""
echo "Step 2/4: Installing FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo "✓ FFmpeg is already installed ($(ffmpeg -version | head -n1))"
else
    sudo apt install -y ffmpeg
    echo "✓ FFmpeg installed successfully"
fi

# Install Tailscale
echo ""
echo "Step 3/4: Installing Tailscale..."
if command -v tailscale &> /dev/null; then
    echo "✓ Tailscale is already installed"
    tailscale version
else
    echo "Downloading and installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    echo "✓ Tailscale installed successfully"
fi

# Check Tailscale status
echo ""
echo "Step 4/4: Checking Tailscale connection..."
if sudo tailscale status &> /dev/null; then
    echo "✓ Tailscale is connected"
    echo ""
    echo "Your Tailscale IP: $(tailscale ip -4 2>/dev/null || echo 'Unable to get IP')"
    echo ""
    echo "Tailscale network devices:"
    sudo tailscale status
else
    echo "⚠ Tailscale is not connected yet."
    echo ""
    echo "To connect to Tailscale, run:"
    echo "  sudo tailscale up"
    echo ""
    echo "This will give you a URL to authenticate in your browser."
fi

# Check for picamera2 (optional)
echo ""
echo "Checking for camera support..."
if python3 -c "import picamera2" 2>/dev/null; then
    echo "✓ picamera2 is installed"
else
    echo "⚠ picamera2 is not installed"
    echo "  On Raspberry Pi OS (Bullseye or later), install with:"
    echo "  sudo apt install -y python3-picamera2"
fi

# Check for OpenCV (used by the streaming script)
if python3 -c "import cv2" 2>/dev/null; then
    echo "✓ OpenCV (cv2) is installed"
else
    echo "⚠ OpenCV is not installed"
    echo "  Install with:"
    echo "  sudo apt install -y python3-opencv"
fi

# Installation complete
echo ""
echo "============================================================"
echo "Setup Complete!"
echo "============================================================"
echo ""
echo "Next steps:"
echo "1. If Tailscale is not connected, run: sudo tailscale up"
echo "2. Find your MediaMTX server's Tailscale IP: tailscale status"
echo "3. Start streaming with:"
echo "   python3 stream_to_mediamtx.py <server-ip> <stream-name>"
echo ""
echo "Example:"
echo "   python3 stream_to_mediamtx.py 100.72.64.80 crowdcount1"
echo ""
