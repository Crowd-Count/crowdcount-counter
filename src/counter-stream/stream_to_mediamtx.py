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
        # Use RTSP for publishing (supports MJPEG)
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
        # First try libcamera (picamera2)
        if self.check_libcamera_cameras():
            try:
                self.picam2 = Picamera2()
                # Configure camera for video capture with framerate control
                # Using YUV420 format is faster than RGB, but we'll convert to BGR for ffmpeg
                config = self.picam2.create_video_configuration(
                    main={"size": (self.width, self.height), "format": "RGB888"},
                    controls={"FrameRate": self.fps},
                    buffer_count=2  # Use double buffering for speed
                )
                self.picam2.configure(config)
                # Start camera and wait for it to be ready
                self.picam2.start()
                time.sleep(1)  # Give camera time to stabilize
                self.use_legacy_camera = False
                print(f"✓ Modern camera (libcamera) initialized: {self.width}x{self.height}@{self.fps}fps")
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
        """Setup ffmpeg process to stream to RTSP"""
        try:
            # ffmpeg command to read raw video from stdin and publish via RTSP
            # Use MJPEG encoding - much lighter on CPU than H.264, perfect for Pi Zero 2W
            ffmpeg_cmd = [
                'ffmpeg',
                '-y',  # Overwrite output files
                '-f', 'rawvideo',  # Input format
                '-vcodec', 'rawvideo',
                '-pix_fmt', 'bgr24',  # OpenCV uses BGR format
                '-s', f'{self.width}x{self.height}',  # Frame size
                '-r', str(self.fps),  # Frame rate
                '-i', '-',  # Read from stdin
                '-c:v', 'mjpeg',  # Use MJPEG codec (motion JPEG - lightweight)
                '-q:v', '5',  # MJPEG quality (2=best, 31=worst, 5≈quality 80)
                '-f', 'rtsp',  # RTSP format (supports MJPEG)
                '-rtsp_transport', 'tcp',  # Use TCP for reliability
                self.publish_url
            ]

            print(f"Publishing stream to: {self.publish_url}")
            print(f"Stream will be available at: {self.rtsp_url}")
            print("Using MJPEG encoding over RTSP (optimized for low-power devices)")

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
        frame_count = 0
        start_time = time.time()

        try:
            while self.running:
                frame = None

                if self.use_legacy_camera:
                    # Use legacy camera (OpenCV)
                    ret, frame = self.cap.read()
                    if not ret:
                        print("Failed to read frame from legacy camera")
                        time.sleep(0.1)
                        continue
                else:
                    # Use modern camera (picamera2) - capture_array is already optimized
                    frame = self.picam2.capture_array()
                    # Convert from RGB to BGR for ffmpeg (numpy operation, very fast)
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

                if frame is not None:
                    # Resize if needed (in case camera didn't set exact size)
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
                        # Try to get FFmpeg error
                        if self.ffmpeg_process and self.ffmpeg_process.poll() is not None:
                            stderr = self.ffmpeg_process.stderr.read().decode('utf-8', errors='ignore')
                            if stderr:
                                print("FFmpeg error output:")
                                print(stderr[-1000:])  # Last 1000 chars
                        break
                    except Exception as e:
                        print(f"✗ Error writing frame: {e}")
                        break

                # No sleep - let camera run at native framerate
                # The camera is configured to capture at self.fps, so it naturally limits the rate

        except KeyboardInterrupt:
            print("\nReceived interrupt signal...")
        except Exception as e:
            print(f"✗ Error streaming frames: {e}")
        finally:
            elapsed = time.time() - start_time
            print(f"\nStreaming stopped: {frame_count} frames in {elapsed:.1f}s ({frame_count/elapsed:.1f} fps)")

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
