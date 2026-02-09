#!/usr/bin/env python3
"""
Raspberry Pi Camera to MediaMTX RTSP Streamer
Streams camera footage from Raspberry Pi to MediaMTX server via RTSP over Tailscale
"""

import cv2
import subprocess
import time
import sys
import argparse
import signal
import threading
import hashlib
import hmac as hmac_mod
import uuid

try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False
    print("picamera2 not available, will use legacy camera")

# Import video config - try relative import first, then absolute
try:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from video_config import VIDEO_FPS, VIDEO_WIDTH, VIDEO_HEIGHT
except ImportError:
    # Fallback defaults if config not found
    VIDEO_FPS = 15
    VIDEO_WIDTH = 640
    VIDEO_HEIGHT = 480


class RTSPCameraStreamer:
    def __init__(self, server_ip, stream_name, width=VIDEO_WIDTH, height=VIDEO_HEIGHT, fps=VIDEO_FPS, rtsp_port=8554, orchestrator_port=5000, device_id=None, password=None, api_url=None, dev_mode=False):
        """
        Initialize the RTSP camera streamer

        Args:
            server_ip: Tailscale IP of the MediaMTX server (e.g., '100.x.x.x')
            stream_name: Unique name for this camera stream (e.g., 'camera1')
            width: Video width in pixels
            height: Video height in pixels
            fps: Frames per second
            rtsp_port: RTSP port on MediaMTX server (default: 8554)
            orchestrator_port: Orchestrator API port (default: 5000, use 5001 for dev)
            device_id: Optional device identifier
            password: Optional password for authentication
            api_url: Optional CrowdCount API URL for status updates
        """
        self.server_ip = server_ip
        self.stream_name = stream_name
        self.device_id = device_id if device_id else stream_name
        self.password = password if password else ""
        self.width = width
        self.height = height
        self.fps = fps
        self.rtsp_port = rtsp_port
        self.orchestrator_port = orchestrator_port
        # Use RTSP for publishing - no authentication (secured by Tailscale VPN)
        # Format: rtsp://server:port/stream_name
        self.publish_url = f"rtsp://{server_ip}:{rtsp_port}/{stream_name}"
        self.rtsp_url = f"rtsp://{server_ip}:{rtsp_port}/{stream_name}"
        self.orchestrator_url = f"http://{server_ip}:{orchestrator_port}"
        self.api_url = api_url if api_url else "https://api.crowdcount.tech"

        self.picam2 = None
        self.cap = None
        self.ffmpeg_process = None
        self.running = False
        self.use_legacy_camera = False
        self.reconnection_enabled = True
        self.reconnection_delay = 5  # seconds
        self.shutdown_requested = False
        self.last_health_check = 0
        self.health_check_interval = 30  # seconds between health checks
        self.initial_health_check_delay = 30  # seconds before first health check (give stream time to establish)
        self.consecutive_health_failures = 0
        self.max_health_failures = 5  # failures before restart (5 failures * 30s = 2.5 min to restart)
        self.ip_refresh_interval = 30  # seconds between IP refresh attempts
        self.last_ip_refresh = 0

        # FFmpeg connection monitoring
        self.ffmpeg_connection_lost = False
        self.ffmpeg_stderr_thread = None
        self.ffmpeg_last_error = None

        # MediaMTX API port (for checking stream status)
        # Dev server uses port 9998, prod uses 9997
        self.dev_mode = dev_mode
        if dev_mode:
            self.mediamtx_api_port = 9998  # Dev server
        else:
            self.mediamtx_api_port = 9997  # Prod server (default)

    def _sign_request(self, method, url, body):
        """Compute HMAC-SHA256 signature headers for API requests."""
        if not self.password:
            return {}
        from urllib.parse import urlparse
        signing_key = hashlib.sha256(f"{self.device_id}:{self.password}".encode()).digest()
        path = urlparse(url).path
        timestamp = str(int(time.time()))
        nonce = str(uuid.uuid4())
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        string_to_sign = f"{method}\n{path}\n{body_hash}\n{timestamp}\n{nonce}"
        signature = hmac_mod.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        return {
            'X-CC-Signature': signature,
            'X-CC-Timestamp': timestamp,
            'X-CC-Nonce': nonce,
            'X-CC-Device-Id': self.device_id,
            'X-CC-Sig-Version': '1',
        }

    def check_libcamera_cameras(self):
        """Check if any cameras are available with libcamera"""
        if not PICAMERA2_AVAILABLE:
            return False

        try:
            # Try to create a Picamera2 instance to check for cameras
            test_cam = Picamera2()
            camera_info = test_cam.global_camera_info()
            test_cam.close()
            return len(camera_info) > 0
        except Exception:
            return False

    def setup_camera(self):
        """Initialize the Pi Camera - try libcamera first, then legacy"""
        # First try libcamera (picamera2) with hardware H.264 encoding
        if self.check_libcamera_cameras():
            try:
                self.picam2 = Picamera2()
                # Configure camera for H.264 video encoding
                # The hardware encoder handles everything - no CPU encoding needed!
                config = self.picam2.create_video_configuration(
                    main={"size": (self.width, self.height)},
                    controls={
                        "FrameRate": self.fps,
                        "FrameDurationLimits": (int(1000000 / self.fps), int(1000000 / self.fps))  # Enforce exact FPS
                    },
                    buffer_count=4  # Increased from 2 for better stability
                )
                self.picam2.configure(config)
                self.picam2.start()
                time.sleep(1)  # Give camera time to stabilize
                self.use_legacy_camera = False
                print(f"✓ Modern camera (libcamera) initialized: {self.width}x{self.height}@{self.fps}fps")
                print("  Using hardware H.264 encoder (VideoCore IV GPU)")
                return True
            except Exception as e:
                print(f"Error initializing modern camera: {e}")
                if self.picam2:
                    try:
                        self.picam2.close()
                    except Exception:
                        pass
                    self.picam2 = None

        # If libcamera failed or no cameras detected, try legacy camera
        print("No libcamera cameras found, trying legacy camera...")

        # Try different video device indices (Pi 5 uses higher numbers)
        video_devices = [0, 1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35]

        for device_id in video_devices:
            try:
                print(f"Trying video device {device_id}...")
                self.cap = cv2.VideoCapture(device_id)
                if self.cap.isOpened():
                    # Test if we can actually read a frame
                    ret, test_frame = self.cap.read()
                    if ret and test_frame is not None:
                        # Set resolution and fps
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
                        self.use_legacy_camera = True
                        print(f"✓ Legacy camera initialized on /dev/video{device_id}: {self.width}x{self.height}@{self.fps}fps")
                        return True
                    else:
                        self.cap.release()
                        self.cap = None
                else:
                    if self.cap:
                        self.cap.release()
                        self.cap = None
            except Exception as e:
                if self.cap:
                    self.cap.release()
                    self.cap = None
                continue

        print("✗ Error: Could not open any video device")
        return False

    def setup_ffmpeg(self):
        """Setup ffmpeg process to stream via RTSP"""
        try:
            # Test RTSP port connectivity before starting FFmpeg
            import socket
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((self.server_ip, self.rtsp_port))
                sock.close()
                if result == 0:
                    print(f"✓ RTSP port {self.rtsp_port} reachable on {self.server_ip}")
                else:
                    print(f"⚠ WARNING: RTSP port {self.rtsp_port} not reachable on {self.server_ip} (error {result})")
                    print("  FFmpeg may fail to connect. Check if MediaMTX is running.")
            except Exception as e:
                print(f"⚠ Could not test RTSP connectivity: {e}")

            if self.use_legacy_camera:
                # Legacy camera: Use MJPEG encoding (software, but lightweight)
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-f', 'rawvideo',
                    '-vcodec', 'rawvideo',
                    '-pix_fmt', 'bgr24',
                    '-s', f'{self.width}x{self.height}',
                    '-r', str(self.fps),
                    '-i', '-',
                    '-c:v', 'mjpeg',
                    '-pix_fmt', 'yuvj422p',
                    '-q:v', '5',
                    '-fflags', '+genpts',     # Generate PTS (changed from nobuffer for consistency)
                    '-flags', 'low_delay',
                    '-f', 'rtsp',
                    '-rtsp_transport', 'tcp',
                    self.publish_url
                ]
                print("Using MJPEG encoding over RTSP (legacy camera)")
            else:
                # Modern camera: Use hardware H.264 encoding (Picamera2 → FFmpeg copy)
                # FFmpeg just wraps the pre-encoded H.264 stream in RTSP - no re-encoding!
                bitrate = 1200000  # 1.2 Mbps for 640p @ 15fps (optimized for Pi Zero 2 W)
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-loglevel', 'verbose',  # More detailed logging for debugging
                    # Input options (must come before -i)
                    '-fflags', '+genpts',  # Generate PTS (input needs timestamps)
                    '-analyzeduration', '500000',  # 0.5s analysis (faster startup)
                    '-probesize', '500000',  # 500KB probe (faster startup)
                    '-f', 'h264',  # Input is H.264 elementary stream
                    '-r', str(self.fps),  # Input framerate hint
                    '-i', '-',  # Read from stdin
                    # Output options
                    '-c:v', 'copy',  # NO re-encoding! Just copy the H.264 stream
                    '-flags', 'low_delay',  # Low delay mode
                    '-f', 'rtsp',  # RTSP format
                    '-rtsp_transport', 'tcp',  # Use TCP for reliability over Tailscale
                    self.publish_url
                ]
                # Removed: duplicate -r output, -vsync cfr (caused frame drops), nobuffer (caused jitter issues)
                print(f"Using hardware H.264 encoding ({bitrate/1000000:.1f} Mbps)")
                print("FFmpeg is just handling RTSP transport (no re-encoding)")

            # Print URL and command for debugging
            display_url = f"rtsp://{self.server_ip}:{self.rtsp_port}/{self.stream_name}"
            print(f"Publishing stream to: {display_url}")
            # Print the full FFmpeg command (hide passwords if any)
            cmd_str = ' '.join(ffmpeg_cmd).replace(self.publish_url, display_url)
            print(f"FFmpeg command: {cmd_str}")

            # Start ffmpeg process
            # Buffer reduced from 100MB to 5MB - large buffers hide connection failures
            # and cause latency buildup. 5MB = ~30 seconds of 1.2Mbps video, enough for jitter
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=5 * 1024 * 1024  # 5MB buffer
            )

            print("✓ FFmpeg process started")

            # Start stderr monitoring thread to detect connection failures early
            self.ffmpeg_connection_lost = False
            self.ffmpeg_last_error = None
            self.ffmpeg_stderr_thread = threading.Thread(target=self._monitor_ffmpeg_stderr, daemon=True)
            self.ffmpeg_stderr_thread.start()

            return True

        except Exception as e:
            print(f"✗ Error setting up ffmpeg: {e}")
            return False

    def _monitor_ffmpeg_stderr(self):
        """Monitor FFmpeg stderr for connection errors in a background thread.

        Detects connection failures that don't cause FFmpeg to exit immediately
        (e.g., TCP connection reset, timeouts, broken pipe).
        """
        connection_error_patterns = [
            b'Connection refused',
            b'Connection reset',
            b'Connection timed out',
            b'Broken pipe',
            b'No route to host',
            b'Network is unreachable',
            b'Connection closed',
            b'Error writing trailer',
            b'av_interleaved_write_frame',
            b'muxing overhead',  # Often appears before connection loss
            b'Socket',              # Socket errors
            b'Timeout',             # Uppercase timeout
            b'EAGAIN',              # Socket would block
            b'ECONNRESET',          # Connection reset by peer
            b'End of file',         # End of stream (more specific than EOF)
            b'failed to connect',   # Connection failure (more specific)
        ]

        # Print first 50 lines of FFmpeg output for debugging
        lines_printed = 0
        max_debug_lines = 50

        try:
            while self.ffmpeg_process and self.ffmpeg_process.poll() is None and self.running:
                # Read stderr line by line (non-blocking would be better but this is simpler)
                line = self.ffmpeg_process.stderr.readline()
                if not line:
                    break

                # Print initial FFmpeg output to help debug connection issues
                if lines_printed < max_debug_lines:
                    line_str = line.decode('utf-8', errors='ignore').strip()
                    if line_str:  # Skip empty lines
                        print(f"[FFmpeg] {line_str}")
                        lines_printed += 1

                # Check for connection error patterns
                for pattern in connection_error_patterns:
                    if pattern in line:
                        self.ffmpeg_last_error = line.decode('utf-8', errors='ignore').strip()
                        self.ffmpeg_connection_lost = True
                        print(f"⚠ FFmpeg connection error detected: {self.ffmpeg_last_error}")
                        return

        except Exception as e:
            # Thread cleanup on error
            pass

    def stream_frames(self):
        """Capture frames and pipe them to ffmpeg"""
        start_time = time.time()
        # Initialize health check timer - delay first check to give stream time to establish
        # By setting last_health_check to (start_time - interval + initial_delay),
        # the first check happens after initial_health_check_delay seconds
        self.last_health_check = start_time + self.initial_health_check_delay - self.health_check_interval
        self.consecutive_health_failures = 0  # Reset failures on new stream
        self.stream_start_time = start_time  # Track when stream started for API check grace period
        self.stream_was_healthy = False  # Track if stream was ever confirmed healthy

        try:
            if not self.use_legacy_camera:
                # Modern camera: Use hardware H.264 encoder
                # Import encoder classes
                try:
                    from picamera2.encoders import H264Encoder
                    from picamera2.outputs import FileOutput
                except ImportError:
                    print("✗ Error: picamera2 encoder not available")
                    return

                # Create H.264 encoder with appropriate bitrate and keyframe interval
                # For Pi Zero 2 W: 1.2 Mbps is optimal for 640x480@15fps (balanced quality/performance)
                bitrate = 1200000
                # iperiod=15 means keyframe every 1 second at 15fps
                # This allows faster recovery from packet loss (was default ~60 = 4 seconds)
                encoder = H264Encoder(bitrate=bitrate, framerate=self.fps, iperiod=15)

                # Output directly to FFmpeg stdin
                output = FileOutput(self.ffmpeg_process.stdin)

                # Start the encoder - this handles everything automatically!
                self.picam2.start_encoder(encoder, output)
                print(f"✓ Hardware encoder started ({bitrate/1000000:.1f} Mbps)")

                # Monitor the stream (encoder runs in background)
                last_status_time = time.time()
                while self.running and not self.shutdown_requested:
                    # Check if FFmpeg is still alive
                    if self.ffmpeg_process.poll() is not None:
                        print("✗ FFmpeg process died")
                        stderr = self.ffmpeg_process.stderr.read().decode('utf-8', errors='ignore')
                        if stderr:
                            print("FFmpeg error output:")
                            print(stderr[-1000:])
                        break

                    # Check if FFmpeg connection was lost (detected by stderr monitor)
                    if self.ffmpeg_connection_lost:
                        print(f"✗ FFmpeg connection lost: {self.ffmpeg_last_error}")
                        break

                    current_time = time.time()

                    # Periodic comprehensive health checks
                    if current_time - self.last_health_check >= self.health_check_interval:
                        all_passed, results, critical_failures = self.perform_health_checks()

                        if not all_passed:
                            self.consecutive_health_failures += 1
                            print(f"\n⚠ Health check FAILED ({self.consecutive_health_failures}/{self.max_health_failures})")
                            for failure in critical_failures:
                                print(f"  ✗ {failure}")

                            # If API reports device offline AND stream was previously working,
                            # immediately restart. If stream was never healthy, let the normal
                            # failure count handle it (immediate restart would just loop).
                            if any("API reports device offline" in f for f in critical_failures):
                                if self.stream_was_healthy:
                                    print(f"\n✗ Server reports device offline - immediately restarting pipeline...")
                                    break
                                else:
                                    print(f"  (stream was never healthy - waiting for normal failure threshold)")

                            # If too many consecutive failures, break and restart
                            if self.consecutive_health_failures >= self.max_health_failures:
                                print(f"\n✗ Too many consecutive health failures - restarting stream...")
                                break
                        else:
                            if not self.stream_was_healthy:
                                print(f"\n✓ Stream confirmed healthy")
                                self.stream_was_healthy = True
                            if self.consecutive_health_failures > 0:
                                print(f"\n✓ Health check recovered after {self.consecutive_health_failures} failures")
                                for name, (ok, msg) in results.items():
                                    print(f"  ✓ {name}: {msg}")
                            self.consecutive_health_failures = 0

                        self.last_health_check = current_time

                    # Print status every 10 seconds (less spam)
                    if current_time - last_status_time >= 10:
                        elapsed = current_time - start_time
                        print(f"Streaming: {elapsed:.1f}s elapsed, encoder running at {self.fps} fps")
                        last_status_time = current_time

                    time.sleep(1)

                # Don't call stop_encoder() here - cleanup() handles it
                # after killing FFmpeg first (to avoid hanging on broken pipe)

            else:
                # Legacy camera: Capture frames manually and encode with MJPEG
                frame_count = 0
                last_health_check_frame = 0
                frames_per_health_check = self.fps * self.health_check_interval

                while self.running and not self.shutdown_requested:
                    ret, frame = self.cap.read()
                    if not ret:
                        print("Failed to read frame from legacy camera")
                        time.sleep(0.1)
                        continue

                    # Resize if needed
                    if frame.shape[1] != self.width or frame.shape[0] != self.height:
                        frame = cv2.resize(frame, (self.width, self.height))

                    try:
                        # Write frame to ffmpeg stdin
                        self.ffmpeg_process.stdin.write(frame.tobytes())
                        frame_count += 1

                        # Print periodic status (every 10 seconds)
                        if frame_count % (self.fps * 10) == 0:
                            elapsed = time.time() - start_time
                            actual_fps = frame_count / elapsed if elapsed > 0 else 0
                            print(f"Streaming: {frame_count} frames | {actual_fps:.1f} fps")

                        # Periodic health checks
                        if frame_count - last_health_check_frame >= frames_per_health_check:
                            all_passed, results, critical_failures = self.perform_health_checks()

                            if not all_passed:
                                self.consecutive_health_failures += 1
                                print(f"\n⚠ Health check FAILED ({self.consecutive_health_failures}/{self.max_health_failures})")
                                for failure in critical_failures:
                                    print(f"  ✗ {failure}")

                                # If API reports device offline AND stream was previously working,
                                # immediately restart. If stream was never healthy, let the normal
                                # failure count handle it (immediate restart would just loop).
                                if any("API reports device offline" in f for f in critical_failures):
                                    if self.stream_was_healthy:
                                        print(f"\n✗ Server reports device offline - immediately restarting pipeline...")
                                        break
                                    else:
                                        print(f"  (stream was never healthy - waiting for normal failure threshold)")

                                if self.consecutive_health_failures >= self.max_health_failures:
                                    print(f"\n✗ Too many consecutive health failures - restarting stream...")
                                    break
                            else:
                                if not self.stream_was_healthy:
                                    print(f"\n✓ Stream confirmed healthy")
                                    self.stream_was_healthy = True
                                if self.consecutive_health_failures > 0:
                                    print(f"\n✓ Health check recovered after {self.consecutive_health_failures} failures")
                                self.consecutive_health_failures = 0

                            last_health_check_frame = frame_count

                    except BrokenPipeError:
                        print("✗ FFmpeg pipe broken - stream may have disconnected")
                        if self.ffmpeg_process and self.ffmpeg_process.poll() is not None:
                            stderr = self.ffmpeg_process.stderr.read().decode('utf-8', errors='ignore')
                            if stderr:
                                print("FFmpeg error output:")
                                print(stderr[-1000:])
                        break
                    except Exception as e:
                        print(f"✗ Error writing frame: {e}")
                        break

        except KeyboardInterrupt:
            print("\nReceived interrupt signal...")
        except Exception as e:
            print(f"✗ Error streaming frames: {e}")
        finally:
            elapsed = time.time() - start_time
            print(f"\nStreaming stopped after {elapsed:.1f}s")

    def check_tailscale_connectivity(self):
        """Check if Tailscale VPN is connected and can reach the server"""
        try:
            # Check Tailscale status
            result = subprocess.run(
                ['tailscale', 'status', '--json'],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode != 0:
                return False, "Tailscale not running"

            import json
            status = json.loads(result.stdout)
            backend_state = status.get('BackendState', '')
            if backend_state != 'Running':
                return False, f"Tailscale state: {backend_state}"

            return True, "Tailscale connected"
        except Exception as e:
            return False, f"Tailscale check error: {e}"

    def check_server_reachable(self):
        """
        Quick TCP check to verify server is reachable before starting FFmpeg.
        This prevents FFmpeg from hanging on connection attempts.
        """
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)  # 3 second timeout
            result = sock.connect_ex((self.server_ip, self.rtsp_port))
            sock.close()
            if result == 0:
                return True, f"Server {self.server_ip}:{self.rtsp_port} reachable"
            else:
                return False, f"Server {self.server_ip}:{self.rtsp_port} not reachable (error {result})"
        except socket.timeout:
            return False, f"Server {self.server_ip}:{self.rtsp_port} connection timeout"
        except Exception as e:
            return False, f"Server check error: {e}"

    def check_mediamtx_stream_status(self):
        """Check if our stream is actually registered and active on MediaMTX server

        MediaMTX API returns info about active streams at /v3/paths/list
        """
        try:
            import requests

            # MediaMTX API endpoint (no authentication - secured by Tailscale)
            api_url = f"http://{self.server_ip}:{self.mediamtx_api_port}/v3/paths/list"

            response = requests.get(api_url, timeout=10)  # Increased timeout for stability

            if response.status_code == 200:
                data = response.json()
                items = data.get('items') or []

                # Look for our stream in the list
                for item in items:
                    if item.get('name') == self.stream_name:
                        # Stream exists - consider it OK even if not fully "ready" yet
                        # The stream needs time to establish, and "ready" can be delayed
                        ready = item.get('ready', False)
                        source = item.get('source')

                        if ready:
                            return True, f"Stream '{self.stream_name}' ready on MediaMTX"
                        elif source:
                            return True, f"Stream '{self.stream_name}' publishing to MediaMTX"
                        else:
                            # Stream exists but not ready yet - this is OK, give it time
                            return True, f"Stream '{self.stream_name}' exists on MediaMTX (initializing)"

                # Stream not found at all - this is a real problem
                return False, f"Stream '{self.stream_name}' not found on MediaMTX"
            else:
                # API error - don't fail health check for API issues
                return True, f"MediaMTX API returned {response.status_code} (skipping check)"
        except Exception as e:
            # Connection error to MediaMTX API - don't fail for this
            return True, f"MediaMTX API check skipped: {e}"

    def check_api_device_status(self):
        """Check our device status from the CrowdCount API (read-only)

        Queries /connection_status to see if the server considers us online.
        If the API thinks we're offline but we think we're streaming,
        something is wrong and we should restart the pipeline.

        Skips the check for the first 90 seconds after stream start to give the
        orchestrator time to detect the stream and update the API status.
        """
        # Grace period: skip API offline check for first 90s after stream starts
        # The orchestrator needs time to detect the stream (~15s health check interval)
        # and call update_status('online') on the API
        api_check_grace_period = 90  # seconds
        if hasattr(self, 'stream_start_time') and (time.time() - self.stream_start_time) < api_check_grace_period:
            elapsed = time.time() - self.stream_start_time
            print(f"[Health] Skipping API status check (grace period: {elapsed:.0f}s / {api_check_grace_period}s)")
            return True, f"API check skipped (grace period: {elapsed:.0f}s / {api_check_grace_period}s)"

        try:
            import requests

            # Check device status via /connection_status endpoint
            status_url = f"{self.api_url}/connection_status"
            payload = {
                'device_id': self.device_id
            }

            import json
            body_str = json.dumps(payload)
            sig_headers = self._sign_request('POST', status_url, body_str)

            print(f"[Health] Checking API device status: {status_url} (device_id={self.device_id})")
            response = requests.post(status_url, json=payload, headers=sig_headers, timeout=5)

            if response.status_code == 200:
                data = response.json()
                status = data.get('status', 'unknown')
                print(f"[Health] API reports device status: {status}")
                if status == 'offline':
                    return False, "API reports device offline"
                return True, f"API status: {status}"
            elif response.status_code == 404:
                # Device not found on server
                print(f"[Health] API returned 404 - device not found")
                return True, "Device not found on API (skipping check)"
            else:
                print(f"[Health] API returned unexpected status code: {response.status_code}")
                return True, f"API returned {response.status_code}"
        except Exception as e:
            # API errors shouldn't break streaming - but log them so we can debug
            print(f"[Health] API check failed with exception: {e}")
            return True, f"API check skipped: {e}"

    def check_network_connectivity(self):
        """Basic network connectivity check to the server

        NOTE: Disabled socket connection check to avoid interfering with active RTSP stream.
        On Pi Zero 2 W, opening additional connections can cause issues.
        We rely on FFmpeg process status and MediaMTX stream status instead.
        """
        # Skip socket check - FFmpeg already has the connection, don't interfere
        return True, "Network check skipped (relying on FFmpeg/MediaMTX status)"

    def perform_health_checks(self):
        """Perform comprehensive health checks to verify stream is actually working

        Optimized for Pi Zero 2 W - quick TCP check + MediaMTX API check.

        Returns:
            tuple: (all_passed: bool, results: dict, critical_failures: list)
        """
        results = {}
        critical_failures = []

        # Check 1: Quick TCP connection test (fast, detects server down immediately)
        ok, msg = self.check_server_reachable()
        results['server_tcp'] = (ok, msg)
        if not ok:
            critical_failures.append(f"Server: {msg}")
            # If server is unreachable, skip MediaMTX API check (it will also fail)
            return False, results, critical_failures

        # Check 2: MediaMTX stream status (CRITICAL - this tells us if server is receiving)
        # This is the only check we really need - if MediaMTX sees our stream, everything is working
        ok, msg = self.check_mediamtx_stream_status()
        results['mediamtx'] = (ok, msg)
        if not ok:
            critical_failures.append(f"MediaMTX: {msg}")

        # Check 3: API device status (CRITICAL - if server thinks we're offline, restart pipeline)
        # This catches cases where the orchestrator marked us offline but we think we're still streaming
        ok, msg = self.check_api_device_status()
        results['api_status'] = (ok, msg)
        if not ok:
            critical_failures.append(f"API Status: {msg}")

        # Check 4: FFmpeg process alive (implicit - checked in main loop)

        # Determine overall health
        all_passed = len(critical_failures) == 0

        return all_passed, results, critical_failures

    def fetch_streaming_server_ip(self):
        """Fetch the streaming server IP from the CrowdCount API

        Calls api.crowdcount.tech/get_streaming_server_ip with device credentials.
        Returns the new server IP if successful, None otherwise.
        """
        if not self.password:
            print("⚠ Cannot fetch server IP: no credentials configured")
            return None

        try:
            import requests

            api_endpoint = f"{self.api_url}/get_streaming_server_ip"
            payload = {
                'device_id': self.device_id,
                'password': self.password
            }

            import json
            body_str = json.dumps(payload)
            sig_headers = self._sign_request('POST', api_endpoint, body_str)

            print(f"Fetching streaming server IP from API...")
            response = requests.post(api_endpoint, json=payload, headers=sig_headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                new_ip = data.get('server_ip') or data.get('ip') or data.get('streaming_ip') or data.get('streaming_server_ip')
                if new_ip:
                    print(f"✓ Got streaming server IP from API: {new_ip}")
                    return new_ip
                else:
                    print(f"⚠ API response missing server IP: {data}")
                    return None
            else:
                print(f"⚠ Failed to fetch server IP: HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"⚠ Error fetching server IP: {e}")
            return None

    def update_server_ip(self, new_ip):
        """Update the server IP and related URLs"""
        if new_ip and new_ip != self.server_ip:
            print(f"Updating server IP: {self.server_ip} → {new_ip}")
            self.server_ip = new_ip
            # Rebuild URLs without credentials (secured by Tailscale VPN)
            self.publish_url = f"rtsp://{new_ip}:{self.rtsp_port}/{self.stream_name}"
            self.rtsp_url = f"rtsp://{new_ip}:{self.rtsp_port}/{self.stream_name}"
            self.orchestrator_url = f"http://{new_ip}:{self.orchestrator_port}"
            return True
        return False

    def register_device(self):
        """Register device information with the server. Returns True if successful, False if auth failed."""
        try:
            import requests

            register_url = f"{self.orchestrator_url}/device/register"
            payload = {
                "stream_name": self.stream_name,
                "device_id": self.device_id,
                "password": self.password
            }

            print(f"Registering device with server...")
            response = requests.post(register_url, json=payload, timeout=5)

            if response.status_code == 200:
                print(f"✓ Device registered: {self.device_id}")
                return True
            elif response.status_code == 401:
                try:
                    msg = response.json().get('message', 'Invalid credentials')
                except Exception:
                    msg = 'Invalid credentials'
                print(f"✗ Authentication failed: {msg}")
                print(f"  Device ID: {self.device_id}")
                print(f"  Check device-identity.conf has correct DEVICE_ID and API_PASSWORD")
                return False
            elif response.status_code == 400:
                try:
                    msg = response.json().get('message', 'Bad request')
                except Exception:
                    msg = 'Bad request'
                print(f"✗ Registration error: {msg}")
                return False
            else:
                print(f"✗ Registration failed (HTTP {response.status_code})")
                return False
        except Exception as e:
            print(f"✗ Could not connect to server for registration: {e}")
            return False

    def start(self):
        """Start the streaming process with automatic reconnection"""
        print("=" * 60)
        print("Raspberry Pi Camera to MediaMTX RTSP Streamer")
        print("=" * 60)
        print(f"Server: {self.server_ip}:{self.rtsp_port}")
        print(f"Stream: {self.stream_name}")
        print(f"Device ID: {self.device_id}")
        print(f"RTSP URL: {self.rtsp_url}")
        print(f"Auto-reconnect: Enabled (every {self.reconnection_delay}s)")
        print("=" * 60)

        # Setup signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            print("\n\nReceived shutdown signal...")
            self.shutdown_requested = True
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Main connection loop with reconnection
        attempt = 0
        while not self.shutdown_requested:
            attempt += 1
            if attempt > 1:
                print(f"\n{'=' * 60}")
                print(f"Reconnection attempt #{attempt - 1}")
                print(f"{'=' * 60}")

            try:
                # Check if server is reachable BEFORE doing anything else
                # This fails fast instead of letting FFmpeg hang
                reachable, msg = self.check_server_reachable()
                if not reachable:
                    print(f"✗ {msg}")
                    if self.reconnection_enabled and not self.shutdown_requested:
                        # Server unreachable - try to fetch new IP
                        current_time = time.time()
                        if current_time - self.last_ip_refresh >= self.ip_refresh_interval:
                            new_ip = self.fetch_streaming_server_ip()
                            if new_ip:
                                self.update_server_ip(new_ip)
                            self.last_ip_refresh = current_time

                        print(f"Retrying in {self.reconnection_delay} seconds...")
                        for _ in range(self.reconnection_delay):
                            if self.shutdown_requested:
                                break
                            time.sleep(1)
                        continue
                    else:
                        return False
                print(f"✓ {msg}")

                # Register device with server (required - validates credentials)
                if not self.register_device():
                    if self.reconnection_enabled and not self.shutdown_requested:
                        print(f"Retrying in {self.reconnection_delay} seconds...")
                        for _ in range(self.reconnection_delay):
                            if self.shutdown_requested:
                                break
                            time.sleep(1)
                        continue
                    else:
                        return False

                # Setup camera
                if not self.setup_camera():
                    print("✗ Failed to initialize camera")
                    if self.reconnection_enabled and not self.shutdown_requested:
                        print(f"Retrying in {self.reconnection_delay} seconds...")
                        for _ in range(self.reconnection_delay):
                            if self.shutdown_requested:
                                break
                            time.sleep(1)
                        continue
                    else:
                        return False

                # Setup FFmpeg
                if not self.setup_ffmpeg():
                    print("✗ Failed to initialize ffmpeg")
                    self.cleanup()
                    if self.reconnection_enabled and not self.shutdown_requested:
                        # FFmpeg failure might be due to server IP change - fetch new IP
                        current_time = time.time()
                        if current_time - self.last_ip_refresh >= self.ip_refresh_interval:
                            new_ip = self.fetch_streaming_server_ip()
                            if new_ip:
                                self.update_server_ip(new_ip)
                            self.last_ip_refresh = current_time

                        print(f"Retrying in {self.reconnection_delay} seconds...")
                        for _ in range(self.reconnection_delay):
                            if self.shutdown_requested:
                                break
                            time.sleep(1)
                        continue
                    else:
                        return False

                self.running = True
                print("\n▶ Streaming started (Ctrl+C to stop)...\n")

                # Start streaming
                self.stream_frames()

                # If we get here, streaming ended
                if self.shutdown_requested:
                    print("Shutdown requested, exiting...")
                    break

                # Connection lost - cleanup and retry if enabled
                self.cleanup()
                if self.reconnection_enabled:
                    print(f"\n⚠ Connection lost. Reconnecting in {self.reconnection_delay} seconds...")

                    # Try to fetch new server IP from API before reconnecting
                    current_time = time.time()
                    if current_time - self.last_ip_refresh >= self.ip_refresh_interval:
                        new_ip = self.fetch_streaming_server_ip()
                        if new_ip:
                            self.update_server_ip(new_ip)
                        self.last_ip_refresh = current_time

                    for _ in range(self.reconnection_delay):
                        if self.shutdown_requested:
                            break
                        time.sleep(1)
                else:
                    break

            except Exception as e:
                print(f"\n✗ Unexpected error: {e}")
                self.cleanup()
                if self.reconnection_enabled and not self.shutdown_requested:
                    print(f"Retrying in {self.reconnection_delay} seconds...")

                    # Try to fetch new server IP from API before reconnecting
                    current_time = time.time()
                    if current_time - self.last_ip_refresh >= self.ip_refresh_interval:
                        new_ip = self.fetch_streaming_server_ip()
                        if new_ip:
                            self.update_server_ip(new_ip)
                        self.last_ip_refresh = current_time

                    for _ in range(self.reconnection_delay):
                        if self.shutdown_requested:
                            break
                        time.sleep(1)
                else:
                    return False

        # Final cleanup on exit
        self.cleanup()
        return True

    def cleanup(self):
        """Clean up resources - aggressively kills hung processes"""
        print("\nCleaning up...")
        self.running = False

        # Kill FFmpeg FIRST and IMMEDIATELY - don't try graceful shutdown.
        # When the server is down, ffmpeg gets stuck and stdin.close() blocks
        # because the pipe buffer is full. Just kill it.
        if self.ffmpeg_process:
            pid = self.ffmpeg_process.pid
            try:
                # Send SIGKILL immediately - no graceful shutdown attempts
                # that can block when ffmpeg is stuck on network I/O
                print(f"Killing FFmpeg (PID {pid})...")
                self.ffmpeg_process.kill()

                # Wait briefly for it to die
                try:
                    self.ffmpeg_process.wait(timeout=3)
                    print("✓ FFmpeg killed")
                except subprocess.TimeoutExpired:
                    # Still alive? Try os.kill as backup
                    print("⚠ FFmpeg didn't die, trying os.kill...")
                    try:
                        import os
                        os.kill(pid, signal.SIGKILL)
                        time.sleep(0.5)
                        print("✓ FFmpeg force killed")
                    except Exception:
                        print(f"⚠ Could not kill FFmpeg PID {pid}")
            except Exception as e:
                print(f"⚠ Error killing FFmpeg: {e}")
                # Last resort
                try:
                    import os
                    os.kill(pid, signal.SIGKILL)
                    print(f"✓ Force killed FFmpeg (PID {pid})")
                except Exception:
                    pass

            # Now safe to close stdin (process is dead)
            try:
                self.ffmpeg_process.stdin.close()
            except Exception:
                pass
            self.ffmpeg_process = None

        # Now stop camera/encoder (safe to do after FFmpeg pipe is closed)
        if self.picam2:
            try:
                try:
                    self.picam2.stop_encoder()
                except Exception:
                    pass
                self.picam2.stop()
                self.picam2.close()
                print("✓ Closed picamera2")
            except Exception:
                pass
            self.picam2 = None

        if self.cap:
            try:
                self.cap.release()
                print("✓ Closed legacy camera")
            except Exception:
                pass
            self.cap = None

        print("✓ Cleanup completed\n")


def main():
    parser = argparse.ArgumentParser(
        description='Stream Raspberry Pi camera to MediaMTX server via RTSP',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Stream to MediaMTX server with stream name 'camera1'
  python3 stream_to_mediamtx.py 100.72.64.80 camera1

  # Stream with custom resolution and fps
  python3 stream_to_mediamtx.py 100.72.64.80 camera2 --width 1280 --height 720 --fps 25

  # Use custom RTSP port
  python3 stream_to_mediamtx.py 100.72.64.80 entrance --port 8555
        """
    )

    parser.add_argument('server_ip',
                       help='Tailscale IP address of MediaMTX server (e.g., 100.72.64.80)')
    parser.add_argument('stream_name',
                       help='Unique name for this camera stream (e.g., camera1, entrance, counter1)')
    parser.add_argument('--width', type=int, default=VIDEO_WIDTH,
                       help=f'Video width in pixels (default: {VIDEO_WIDTH})')
    parser.add_argument('--height', type=int, default=VIDEO_HEIGHT,
                       help=f'Video height in pixels (default: {VIDEO_HEIGHT})')
    parser.add_argument('--fps', type=int, default=VIDEO_FPS,
                       help=f'Frames per second (default: {VIDEO_FPS})')
    parser.add_argument('--port', type=int, default=8554,
                       help='RTSP port on MediaMTX server (default: 8554)')
    parser.add_argument('--orchestrator-port', type=int, default=5000,
                       help='Orchestrator API port (default: 5000, use 5001 for dev server)')
    parser.add_argument('--device-id', type=str, default=None,
                       help='Device identifier (defaults to stream_name if not provided)')
    parser.add_argument('--password', type=str, default='',
                       help='Optional password for authentication')
    parser.add_argument('--api-url', type=str, default='https://api.crowdcount.tech',
                       help='CrowdCount API URL for status updates (default: https://api.crowdcount.tech)')
    parser.add_argument('--dev', action='store_true',
                       help='Use development server ports (MediaMTX API 9998 instead of 9997)')

    args = parser.parse_args()

    # Create and start streamer
    streamer = RTSPCameraStreamer(
        server_ip=args.server_ip,
        stream_name=args.stream_name,
        width=args.width,
        height=args.height,
        fps=args.fps,
        rtsp_port=args.port,
        orchestrator_port=args.orchestrator_port,
        device_id=args.device_id,
        password=args.password,
        api_url=args.api_url,
        dev_mode=args.dev
    )

    try:
        streamer.start()
    except Exception as e:
        print(f"✗ Fatal error: {e}")
        streamer.cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()
