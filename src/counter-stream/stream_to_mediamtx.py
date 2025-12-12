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

try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False
    print("picamera2 not available, will use legacy camera")


class RTSPCameraStreamer:
    def __init__(self, server_ip, stream_name, width=640, height=480, fps=30, rtsp_port=8554, device_id=None, password=None, api_url=None):
        """
        Initialize the RTSP camera streamer

        Args:
            server_ip: Tailscale IP of the MediaMTX server (e.g., '100.x.x.x')
            stream_name: Unique name for this camera stream (e.g., 'camera1')
            width: Video width in pixels
            height: Video height in pixels
            fps: Frames per second
            rtsp_port: RTSP port on MediaMTX server (default: 8554)
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
        # Use RTSP for publishing with authentication
        # Format: rtsp://device_id:password@server:port/stream_name
        if device_id and password:
            self.publish_url = f"rtsp://{device_id}:{password}@{server_ip}:{rtsp_port}/{stream_name}"
            self.rtsp_url = f"rtsp://{device_id}:{password}@{server_ip}:{rtsp_port}/{stream_name}"
        else:
            self.publish_url = f"rtsp://{server_ip}:{rtsp_port}/{stream_name}"
            self.rtsp_url = f"rtsp://{server_ip}:{rtsp_port}/{stream_name}"
        self.orchestrator_url = f"http://{server_ip}:5000"
        self.api_url = api_url if api_url else "https://api.crowdcount.tech"

        self.picam2 = None
        self.cap = None
        self.ffmpeg_process = None
        self.running = False
        self.use_legacy_camera = False
        self.reconnection_enabled = True
        self.reconnection_delay = 10  # seconds
        self.shutdown_requested = False
        self.last_health_check = 0
        self.health_check_interval = 15  # seconds - check more frequently
        self.consecutive_health_failures = 0
        self.max_health_failures = 3  # Break after 3 consecutive failures (45s) to restart sooner
        self.ip_refresh_interval = 30  # seconds between IP refresh attempts on failure
        self.last_ip_refresh = 0

        # MediaMTX API port (for checking stream status)
        self.mediamtx_api_port = 9997  # Default MediaMTX API port

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
                    '-fflags', 'nobuffer',
                    '-flags', 'low_delay',
                    '-f', 'rtsp',
                    '-rtsp_transport', 'tcp',
                    self.publish_url
                ]
                print("Using MJPEG encoding over RTSP (legacy camera)")
            else:
                # Modern camera: Use hardware H.264 encoding (Picamera2 → FFmpeg copy)
                # FFmpeg just wraps the pre-encoded H.264 stream in RTSP - no re-encoding!
                bitrate = 2500000  # 2.5 Mbps for 640p @ 30fps (increased for better quality)
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-f', 'h264',  # Input is H.264 elementary stream
                    '-r', str(self.fps),  # Force input framerate
                    '-i', '-',  # Read from stdin
                    '-c:v', 'copy',  # NO re-encoding! Just copy the H.264 stream
                    '-fflags', 'nobuffer+flush_packets',  # Disable buffering + flush packets immediately
                    '-flags', 'low_delay',  # Low delay mode
                    '-max_delay', '0',  # Minimum delay
                    '-r', str(self.fps),  # Force output framerate
                    '-f', 'rtsp',  # RTSP format
                    '-rtsp_transport', 'tcp',  # Use TCP for reliability over Tailscale
                    self.publish_url
                ]
                print(f"Using hardware H.264 encoding ({bitrate/1000000:.1f} Mbps)")
                print("FFmpeg is just handling RTSP transport (no re-encoding)")

            # Print URL without exposing password
            display_url = f"rtsp://{self.server_ip}:{self.rtsp_port}/{self.stream_name}"
            print(f"Publishing stream to: {display_url}")
            print(f"Stream will be available at: {display_url}")

            # Start ffmpeg process
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**8
            )

            print("✓ FFmpeg process started")
            return True

        except Exception as e:
            print(f"✗ Error setting up ffmpeg: {e}")
            return False

    def stream_frames(self):
        """Capture frames and pipe them to ffmpeg"""
        start_time = time.time()

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

                # Create H.264 encoder with appropriate bitrate
                # For 640p @ 30fps: 2.5 Mbps provides good quality without frame drops
                bitrate = 2500000
                encoder = H264Encoder(bitrate=bitrate, framerate=self.fps)

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

                    current_time = time.time()

                    # Periodic comprehensive health checks
                    if current_time - self.last_health_check >= self.health_check_interval:
                        all_passed, results, critical_failures = self.perform_health_checks()

                        if not all_passed:
                            self.consecutive_health_failures += 1
                            print(f"\n⚠ Health check FAILED ({self.consecutive_health_failures}/{self.max_health_failures})")
                            for failure in critical_failures:
                                print(f"  ✗ {failure}")

                            # If too many consecutive failures, break and restart
                            if self.consecutive_health_failures >= self.max_health_failures:
                                print(f"\n✗ Too many consecutive health failures - restarting stream...")
                                break
                        else:
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

                # Stop encoder
                self.picam2.stop_encoder()

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

                                if self.consecutive_health_failures >= self.max_health_failures:
                                    print(f"\n✗ Too many consecutive health failures - restarting stream...")
                                    break
                            else:
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

    def check_mediamtx_stream_status(self):
        """Check if our stream is actually registered and active on MediaMTX server

        MediaMTX API returns info about active streams at /v3/paths/list
        """
        try:
            import requests
            from requests.auth import HTTPBasicAuth

            # MediaMTX API endpoint with authentication
            api_url = f"http://{self.server_ip}:{self.mediamtx_api_port}/v3/paths/list"

            # Use HTTP Basic Auth with device credentials
            auth = HTTPBasicAuth(self.device_id, self.password) if self.device_id and self.password else None
            response = requests.get(api_url, auth=auth, timeout=5)

            if response.status_code == 200:
                data = response.json()
                items = data.get('items', [])

                # Look for our stream in the list
                for item in items:
                    if item.get('name') == self.stream_name:
                        # Check if stream has readers or is ready
                        ready = item.get('ready', False)
                        readers = item.get('readers', [])
                        source = item.get('source', {})

                        if ready or source:
                            return True, f"Stream '{self.stream_name}' active on MediaMTX"
                        else:
                            return False, f"Stream '{self.stream_name}' found but not ready"

                return False, f"Stream '{self.stream_name}' not found on MediaMTX"
            else:
                return False, f"MediaMTX API returned {response.status_code}"
        except Exception as e:
            return False, f"MediaMTX API error: {e}"

    def check_api_device_status(self):
        """Check our device status from the CrowdCount API (read-only)

        If the API thinks we're offline but we think we're streaming,
        something is wrong and we should restart.
        """
        if not self.password:
            return True, "No credentials - skipping API check"

        try:
            import requests

            # Check device status from API
            status_url = f"{self.api_url}/get_device_status"
            params = {
                'user_id': self.device_id,
                'password': self.password
            }

            response = requests.get(status_url, params=params, timeout=5)

            if response.status_code == 200:
                data = response.json()
                status = data.get('status', 'unknown')
                if status == 'offline':
                    return False, "API reports device offline"
                return True, f"API status: {status}"
            elif response.status_code == 404:
                # Endpoint might not exist, skip check
                return True, "API check not available"
            else:
                return True, f"API returned {response.status_code}"
        except Exception as e:
            # API errors shouldn't break streaming
            return True, f"API check skipped: {e}"

    def check_network_connectivity(self):
        """Basic network connectivity check to the server"""
        try:
            import socket

            # Try to connect to the RTSP port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.server_ip, self.rtsp_port))
            sock.close()

            if result == 0:
                return True, f"Network OK (port {self.rtsp_port} reachable)"
            else:
                return False, f"Cannot reach {self.server_ip}:{self.rtsp_port}"
        except Exception as e:
            return False, f"Network check error: {e}"

    def perform_health_checks(self):
        """Perform comprehensive health checks to verify stream is actually working

        Returns:
            tuple: (all_passed: bool, results: dict)
        """
        results = {}
        critical_failures = []

        # Check 1: Network connectivity (critical)
        ok, msg = self.check_network_connectivity()
        results['network'] = (ok, msg)
        if not ok:
            critical_failures.append(f"Network: {msg}")

        # Check 2: Tailscale connectivity (critical)
        ok, msg = self.check_tailscale_connectivity()
        results['tailscale'] = (ok, msg)
        if not ok:
            critical_failures.append(f"Tailscale: {msg}")

        # Check 3: MediaMTX stream status (critical - this tells us if server is receiving)
        ok, msg = self.check_mediamtx_stream_status()
        results['mediamtx'] = (ok, msg)
        if not ok:
            critical_failures.append(f"MediaMTX: {msg}")

        # Check 4: API device status (informational - server's view of our status)
        ok, msg = self.check_api_device_status()
        results['api_status'] = (ok, msg)
        # API check is not critical - we don't add to critical_failures

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
            params = {
                'user_id': self.device_id,
                'password': self.password
            }

            print(f"Fetching streaming server IP from API...")
            response = requests.get(api_endpoint, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                new_ip = data.get('server_ip') or data.get('ip') or data.get('streaming_ip')
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
            # Rebuild URLs with credentials
            if self.device_id and self.password:
                self.publish_url = f"rtsp://{self.device_id}:{self.password}@{new_ip}:{self.rtsp_port}/{self.stream_name}"
                self.rtsp_url = f"rtsp://{self.device_id}:{self.password}@{new_ip}:{self.rtsp_port}/{self.stream_name}"
            else:
                self.publish_url = f"rtsp://{new_ip}:{self.rtsp_port}/{self.stream_name}"
                self.rtsp_url = f"rtsp://{new_ip}:{self.rtsp_port}/{self.stream_name}"
            self.orchestrator_url = f"http://{new_ip}:5000"
            return True
        return False

    def register_device(self):
        """Register device information with the server"""
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
            else:
                print(f"⚠ Warning: Failed to register device (server returned {response.status_code})")
                print(f"  Continuing anyway...")
                return False
        except Exception as e:
            print(f"⚠ Warning: Could not register device: {e}")
            print(f"  Continuing anyway...")
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
                # Register device with server
                self.register_device()

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
        """Clean up resources"""
        print("\nCleaning up...")
        self.running = False

        # Close camera
        if self.picam2:
            try:
                # Stop encoder if it's running
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

        # Close ffmpeg
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.stdin.close()
                self.ffmpeg_process.wait(timeout=5)
                print("✓ Closed ffmpeg process")
            except Exception:
                try:
                    self.ffmpeg_process.kill()
                    print("✓ Killed ffmpeg process")
                except Exception:
                    pass
            self.ffmpeg_process = None

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
    parser.add_argument('--width', type=int, default=640,
                       help='Video width in pixels (default: 640)')
    parser.add_argument('--height', type=int, default=480,
                       help='Video height in pixels (default: 480)')
    parser.add_argument('--fps', type=int, default=30,
                       help='Frames per second (default: 30)')
    parser.add_argument('--port', type=int, default=8554,
                       help='RTSP port on MediaMTX server (default: 8554)')
    parser.add_argument('--device-id', type=str, default=None,
                       help='Device identifier (defaults to stream_name if not provided)')
    parser.add_argument('--password', type=str, default='',
                       help='Optional password for authentication')
    parser.add_argument('--api-url', type=str, default='https://api.crowdcount.tech',
                       help='CrowdCount API URL for status updates (default: https://api.crowdcount.tech)')

    args = parser.parse_args()

    # Create and start streamer
    streamer = RTSPCameraStreamer(
        server_ip=args.server_ip,
        stream_name=args.stream_name,
        width=args.width,
        height=args.height,
        fps=args.fps,
        rtsp_port=args.port,
        device_id=args.device_id,
        password=args.password,
        api_url=args.api_url
    )

    try:
        streamer.start()
    except Exception as e:
        print(f"✗ Fatal error: {e}")
        streamer.cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()
