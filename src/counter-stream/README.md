# Raspberry Pi Camera Streaming to MediaMTX

This directory contains the code for streaming camera footage from Raspberry Pi devices to a MediaMTX server over Tailscale.

## Requirements

### On Raspberry Pi

1. **Python 3** (usually pre-installed)
2. **OpenCV for Python**:
   ```bash
   sudo apt update
   sudo apt install python3-opencv
   ```

3. **FFmpeg** (for RTSP streaming):
   ```bash
   sudo apt install ffmpeg
   ```

4. **Camera support** (one of these):
   - **picamera2** (modern, recommended for Pi 5):
     ```bash
     sudo apt install python3-picamera2
     ```
   - **OR legacy camera support** (OpenCV VideoCapture - automatic fallback)

5. **Tailscale** (if not already installed):
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

### On Your PC (MediaMTX Server)

You'll need MediaMTX running on your PC - setup instructions will be provided separately.

## Usage

### Recommended: Using Configuration File

The easiest way to start streaming is using the device configuration file:

```bash
# 1. Copy the template configuration file
cp device-info.conf.template device-info.conf

# 2. Edit with your device settings
nano device-info.conf

# 3. Start streaming
./start_stream.sh
```

**Configuration file (`device-info.conf`):**
```ini
DEVICE_ID=crowdcount1        # Unique name for this camera
SERVER_IP=100.72.64.80       # Your MediaMTX server's Tailscale IP
RTSP_PORT=8554               # RTSP port (default: 8554)
WIDTH=640                     # Video width
HEIGHT=480                    # Video height
FPS=30                        # Frames per second
```

This method is ideal for:
- Setting up multiple Raspberry Pi cameras (each with its own config)
- Running streams automatically on boot
- Quick deployment without remembering command-line arguments

### Basic Usage (Command Line)

You can also run the stream script directly:

```bash
python3 stream_to_mediamtx.py <SERVER_IP> <STREAM_NAME>
```

**Example:**
```bash
# Stream to MediaMTX server at Tailscale IP with stream name 'camera1'
python3 stream_to_mediamtx.py 100.72.64.80 camera1
```

### Advanced Options

```bash
# Custom resolution (720p)
python3 stream_to_mediamtx.py 100.72.64.80 camera2 --width 1280 --height 720

# Custom frame rate
python3 stream_to_mediamtx.py 100.72.64.80 entrance --fps 25

# Custom RTSP port
python3 stream_to_mediamtx.py 100.72.64.80 counter1 --port 8555
```

### Full Options

- `server_ip`: Tailscale IP of your MediaMTX server (required)
- `stream_name`: Unique identifier for this camera (required)
- `--width`: Video width in pixels (default: 640)
- `--height`: Video height in pixels (default: 480)
- `--fps`: Frames per second (default: 30)
- `--port`: RTSP port on server (default: 8554)

## Setup Instructions

### Quick Setup (Automated)

The easiest way to set up your Raspberry Pi is using the automated setup script:

```bash
# 1. Copy the entire counter-stream directory to your Pi
scp -r counter-stream pi@<PI_IP>:~/

# 2. SSH into your Pi
ssh pi@<PI_IP>

# 3. Run the setup script
cd counter-stream
bash setup_pi.sh
```

This will automatically install:
- FFmpeg
- Tailscale
- Check for camera support (picamera2/OpenCV)

After the script completes, authenticate with Tailscale:
```bash
sudo tailscale up
```

Then you're ready to start streaming!

### Manual Setup

If you prefer to install dependencies manually:

#### 1. Copy Script to Raspberry Pi

```bash
# From your PC, copy the script to each Raspberry Pi
scp stream_to_mediamtx.py pi@<PI_IP>:~/
```

#### 2. Find Your MediaMTX Server's Tailscale IP

On your PC (where MediaMTX will run):
```bash
tailscale ip -4
```

This will show something like `100.72.64.80` - use this as your `SERVER_IP`.

#### 3. Start Streaming from Raspberry Pi

```bash
# On the Raspberry Pi
python3 stream_to_mediamtx.py 100.72.64.80 camera1
```

Replace `100.72.64.80` with your actual Tailscale IP.

## Run on Boot (Optional)

To automatically start streaming when the Pi boots:

1. First, make sure your `device-info.conf` is configured correctly

2. Create a systemd service file:
   ```bash
   sudo nano /etc/systemd/system/camera-stream.service
   ```

3. Add this content (adjust the path to your counter-stream directory):
   ```ini
   [Unit]
   Description=Camera Stream to MediaMTX
   After=network-online.target tailscaled.service
   Wants=network-online.target

   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/counter-stream
   ExecStart=/home/pi/counter-stream/start_stream.sh
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

4. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable camera-stream.service
   sudo systemctl start camera-stream.service
   ```

5. Check status:
   ```bash
   sudo systemctl status camera-stream.service
   ```

6. View logs:
   ```bash
   sudo journalctl -u camera-stream.service -f
   ```

## Troubleshooting

### Camera Not Found
- **For picamera2**: Make sure camera is enabled in `sudo raspi-config` > Interface Options > Camera
- **For legacy camera**: Check if camera device exists: `ls /dev/video*`

### FFmpeg Not Found
```bash
sudo apt install ffmpeg
```

### Can't Connect to Server
- Verify Tailscale is running on both Pi and PC: `tailscale status`
- Check server IP: `tailscale ip -4`
- Make sure MediaMTX is running on your PC
- Try pinging the server: `ping <SERVER_IP>`

### Stream Disconnects
- Check network stability
- Reduce resolution or fps if bandwidth is limited
- Check MediaMTX logs on the server

## Stream URLs

Once streaming, you can view the stream at:
- **RTSP**: `rtsp://<SERVER_IP>:8554/<STREAM_NAME>`
- **HLS** (via browser): `http://<SERVER_IP>:8554/<STREAM_NAME>/`
- **WebRTC**: Available if MediaMTX has WebRTC enabled

## Camera Settings Reference

| Resolution | Width | Height | Typical Use Case |
|------------|-------|--------|------------------|
| VGA        | 640   | 480    | Default, low bandwidth |
| 480p       | 854   | 480    | Widescreen low |
| 720p       | 1280  | 720    | HD quality |
| 1080p      | 1920  | 1080   | Full HD (high bandwidth) |

**Recommended for 10 streams**: 640x480 @ 30fps (uses ~2-3 Mbps per stream)
