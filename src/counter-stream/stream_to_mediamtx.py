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
    def __init__(self, server_ip, stream_name, width=640, height=480, fps=30, rtsp_port=8554, device_id=None, password=None):
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
        """
        self.server_ip = server_ip
        self.stream_name = stream_name
        self.device_id = device_id if device_id else stream_name
        self.password = password if password else ""
        self.width = width
        self.height = height
        self.fps = fps
        self.rtsp_port = rtsp_port
        # Use RTSP for publishing (MJPEG - low CPU)
        self.publish_url = f"rtsp://{server_ip}:{rtsp_port}/{stream_name}"
        self.rtsp_url = f"rtsp://{server_ip}:{rtsp_port}/{stream_name}"
        self.orchestrator_url = f"http://{server_ip}:5000"

        self.picam2 = None
        self.cap = None
        self.ffmpeg_process = None
        self.running = False
        self.use_legacy_camera = False

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
                    controls={"FrameRate": self.fps},
                    buffer_count=2
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
                    except:
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
                bitrate = 2000000  # 2 Mbps for 640p (adjust as needed)
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-f', 'h264',  # Input is H.264 elementary stream
                    '-i', '-',  # Read from stdin
                    '-c:v', 'copy',  # NO re-encoding! Just copy the H.264 stream
                    '-fflags', 'nobuffer',  # Disable buffering for low latency
                    '-flags', 'low_delay',  # Low delay mode
                    '-f', 'rtsp',  # RTSP format
                    '-rtsp_transport', 'tcp',  # Use TCP for reliability
                    self.publish_url
                ]
                print(f"Using hardware H.264 encoding ({bitrate/1000000:.1f} Mbps)")
                print("FFmpeg is just handling RTSP transport (no re-encoding)")

            print(f"Publishing stream to: {self.publish_url}")
            print(f"Stream will be available at: {self.rtsp_url}")

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
                # For 640p: 1.5-4 Mbps is recommended, using 2 Mbps
                bitrate = 2000000
                encoder = H264Encoder(bitrate=bitrate)

                # Output directly to FFmpeg stdin
                output = FileOutput(self.ffmpeg_process.stdin)

                # Start the encoder - this handles everything automatically!
                self.picam2.start_encoder(encoder, output)
                print(f"✓ Hardware encoder started ({bitrate/1000000:.1f} Mbps)")

                # Monitor the stream (encoder runs in background)
                last_status_time = time.time()
                while self.running:
                    # Check if FFmpeg is still alive
                    if self.ffmpeg_process.poll() is not None:
                        print("✗ FFmpeg process died")
                        stderr = self.ffmpeg_process.stderr.read().decode('utf-8', errors='ignore')
                        if stderr:
                            print("FFmpeg error output:")
                            print(stderr[-1000:])
                        break

                    # Print status every 5 seconds
                    current_time = time.time()
                    if current_time - last_status_time >= 5:
                        elapsed = current_time - start_time
                        print(f"Streaming: {elapsed:.1f}s elapsed, encoder running at {self.fps} fps")
                        last_status_time = current_time

                    time.sleep(1)

                # Stop encoder
                self.picam2.stop_encoder()

            else:
                # Legacy camera: Capture frames manually and encode with MJPEG
                frame_count = 0
                while self.running:
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

                        # Print periodic status (every 5 seconds)
                        if frame_count % (self.fps * 5) == 0:
                            elapsed = time.time() - start_time
                            actual_fps = frame_count / elapsed if elapsed > 0 else 0
                            print(f"Streaming: {frame_count} frames | {actual_fps:.1f} fps")

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

    def register_device(self):
        """Register device information with the server"""
        try:
            import requests
            import json

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
        """Start the streaming process"""
        print("=" * 60)
        print("Raspberry Pi Camera to MediaMTX RTSP Streamer")
        print("=" * 60)
        print(f"Server: {self.server_ip}:{self.rtsp_port}")
        print(f"Stream: {self.stream_name}")
        print(f"Device ID: {self.device_id}")
        print(f"RTSP URL: {self.rtsp_url}")
        print("=" * 60)

        # Register device with server
        self.register_device()

        if not self.setup_camera():
            print("✗ Failed to initialize camera")
            return False

        if not self.setup_ffmpeg():
            print("✗ Failed to initialize ffmpeg")
            self.cleanup()
            return False

        self.running = True
        print("\n▶ Streaming started (Ctrl+C to stop)...\n")

        # Setup signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            print("\n\nReceived shutdown signal...")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start streaming
        self.stream_frames()

        # Cleanup on exit
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
                except:
                    pass
                self.picam2.stop()
                self.picam2.close()
                print("✓ Closed picamera2")
            except:
                pass

        if self.cap:
            try:
                self.cap.release()
                print("✓ Closed legacy camera")
            except:
                pass

        # Close ffmpeg
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.stdin.close()
                self.ffmpeg_process.wait(timeout=5)
                print("✓ Closed ffmpeg process")
            except:
                self.ffmpeg_process.kill()
                print("✓ Killed ffmpeg process")

        print("✓ Cleanup completed\n")


def main():
    parser = argparse.ArgumentParser(
        description='Stream Raspberry Pi camera to MediaMTX server via RTSP',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Stream to MediaMTX server at 100.64.1.2 with stream name 'camera1'
  python3 stream_to_mediamtx.py 100.64.1.2 camera1

  # Stream with custom resolution and fps
  python3 stream_to_mediamtx.py 100.64.1.2 camera2 --width 1280 --height 720 --fps 25

  # Use custom RTSP port
  python3 stream_to_mediamtx.py 100.64.1.2 entrance --port 8555
        """
    )

    parser.add_argument('server_ip',
                       help='Tailscale IP address of MediaMTX server (e.g., 100.64.1.2)')
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
        password=args.password
    )

    try:
        streamer.start()
    except Exception as e:
        print(f"✗ Fatal error: {e}")
        streamer.cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()
