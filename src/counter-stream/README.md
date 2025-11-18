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

### Basic Usage

```bash
python3 stream_to_mediamtx.py <SERVER_IP> <STREAM_NAME>
```

**Example:**
```bash
# Stream to MediaMTX server at Tailscale IP 100.64.1.2 with stream name 'camera1'
python3 stream_to_mediamtx.py 100.64.1.2 camera1
```

### Advanced Options

```bash
# Custom resolution (720p)
python3 stream_to_mediamtx.py 100.64.1.2 camera2 --width 1280 --height 720

# Custom frame rate
python3 stream_to_mediamtx.py 100.64.1.2 entrance --fps 25

# Custom RTSP port
python3 stream_to_mediamtx.py 100.64.1.2 counter1 --port 8555
```

### Full Options

- `server_ip`: Tailscale IP of your MediaMTX server (required)
- `stream_name`: Unique identifier for this camera (required)
- `--width`: Video width in pixels (default: 640)
- `--height`: Video height in pixels (default: 480)
- `--fps`: Frames per second (default: 30)
- `--port`: RTSP port on server (default: 8554)

## Setup Instructions

### 1. Copy Script to Raspberry Pi

```bash
# From your PC, copy the script to each Raspberry Pi
scp stream_to_mediamtx.py pi@<PI_IP>:~/
```

### 2. Find Your MediaMTX Server's Tailscale IP

On your PC (where MediaMTX will run):
```bash
tailscale ip -4
```

This will show something like `100.64.1.2` - use this as your `SERVER_IP`.

### 3. Start Streaming from Raspberry Pi

```bash
# On the Raspberry Pi
python3 stream_to_mediamtx.py 100.64.1.2 camera1
```

Replace `100.64.1.2` with your actual Tailscale IP.

### 4. Run on Boot (Optional)

To automatically start streaming when the Pi boots:

1. Create a systemd service file:
   ```bash
   sudo nano /etc/systemd/system/camera-stream.service
   ```

2. Add this content (adjust paths and parameters):
   ```ini
   [Unit]
   Description=Camera Stream to MediaMTX
   After=network-online.target tailscaled.service
   Wants=network-online.target

   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi
   ExecStart=/usr/bin/python3 /home/pi/stream_to_mediamtx.py 100.64.1.2 camera1
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

3. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable camera-stream.service
   sudo systemctl start camera-stream.service
   ```

4. Check status:
   ```bash
   sudo systemctl status camera-stream.service
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
