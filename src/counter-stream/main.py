#!/usr/bin/env python3
"""
Raspberry Pi Video Streaming Client with Authentication
Captures video using picamera2/libcamera and streams via WebRTC to the signaling server
"""

import asyncio
import json
import logging
import signal
import sys
import threading
import time
from typing import Optional, Dict, Any

import cv2
import numpy as np
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaPlayer
from av import VideoFrame
from picamera2 import Picamera2

# Import settings
try:
    from settings import *
except ImportError:
    # Fallback to default settings if settings.py not found
    print("Warning: settings.py not found, using default settings")
    SERVER_URL = "ws://localhost:3000"
    DEVICE_ID = "Demo"
    DEVICE_PASSWORD = "password"
    FEED_ID = "Testing_Demo"
    FEED_NAME = "Raspberry Pi Camera"
    CAMERA_CONFIG = {'size': (1280, 720), 'format': 'RGB888', 'framerate': 30}
    ICE_SERVERS = [{"urls": "stun:stun.l.google.com:19302"}]
    LOG_LEVEL = 'INFO'
    LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format=LOG_FORMAT
)
logger = logging.getLogger(__name__)


class PiCameraTrack(VideoStreamTrack):
    """Custom video track that captures frames from Raspberry Pi camera"""
    
    def __init__(self, camera_config: Dict[str, Any] = None):
        super().__init__()
        self.camera = None
        self.config = camera_config or CAMERA_CONFIG
        self._setup_camera()
        
    def _setup_camera(self):
        """Initialize the Pi camera"""
        try:
            self.camera = Picamera2()
            
            # Configure camera
            config = self.camera.create_video_configuration(
                main={"size": self.config['size'], "format": self.config['format']}
            )
            
            self.camera.configure(config)
            self.camera.start()
            
            # Let camera adjust
            time.sleep(2)
            logger.info(f"Camera initialized: {self.config['size']} @ {self.config['framerate']}fps")
            
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}")
            raise
    
    async def recv(self):
        """Capture and return video frame"""
        try:
            # Capture frame from camera
            frame = self.camera.capture_array()
            
            # Convert BGR to RGB if needed
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Create VideoFrame
            av_frame = VideoFrame.from_ndarray(frame, format="rgb24")
            av_frame.pts = self.next_timestamp()
            av_frame.time_base = self._video_time_base
            
            return av_frame
            
        except Exception as e:
            logger.error(f"Error capturing frame: {e}")
            # Return a blank frame on error
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            av_frame = VideoFrame.from_ndarray(blank, format="rgb24")
            av_frame.pts = self.next_timestamp()
            av_frame.time_base = self._video_time_base
            return av_frame
    
    def cleanup(self):
        """Clean up camera resources"""
        if self.camera:
            try:
                self.camera.stop()
                self.camera.close()
                logger.info("Camera cleaned up")
            except Exception as e:
                logger.error(f"Error cleaning up camera: {e}")


class VideoStreamingClient:
    """WebRTC video streaming client for Raspberry Pi with authentication"""
    
    def __init__(self, server_url: str, device_id: str, device_password: str, 
                 feed_id: str = None, feed_name: str = None):
        self.server_url = server_url
        self.device_id = device_id
        self.device_password = device_password
        self.feed_id = feed_id or device_id
        self.feed_name = feed_name or f"RPi Camera {self.feed_id}"
        
        self.websocket = None
        self.client_id = None
        self.authenticated = False
        self.peer_connections: Dict[str, RTCPeerConnection] = {}
        self.camera_track = None
        self.running = False
        
        # ICE servers for WebRTC
        self.ice_servers = ICE_SERVERS
        
    async def connect(self):
        """Connect to the signaling server"""
        try:
            logger.info(f"Connecting to server: {self.server_url}")
            logger.info(f"Device ID: {self.device_id}")
            
            self.websocket = await websockets.connect(self.server_url)
            self.running = True
            
            # Start message handling
            await self._handle_messages()
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.running = False
            raise
    
    async def _handle_messages(self):
        """Handle incoming WebSocket messages"""
        async for message in self.websocket:
            try:
                data = json.loads(message)
                await self._process_message(data)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON received: {e}")
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    
    async def _process_message(self, data: Dict[str, Any]):
        """Process incoming message from server"""
        msg_type = data.get('type')
        
        if msg_type == 'auth-required':
            # Server requires authentication
            self.client_id = data.get('clientId')
            logger.info(f"Authentication required. Client ID: {self.client_id}")
            await self._authenticate()
            
        elif msg_type == 'auth-success':
            # Authentication successful
            self.authenticated = True
            self.client_id = data.get('clientId')
            device_name = data.get('deviceName', self.device_id)
            
            if data.get('iceServers'):
                self.ice_servers = data['iceServers']
            
            logger.info(f"Authentication successful. Device: {device_name}")
            
        elif msg_type == 'auth-failed':
            # Authentication failed
            error_msg = data.get('message', 'Unknown error')
            logger.error(f"Authentication failed: {error_msg}")
            self.running = False
            await self.websocket.close()
            
        elif msg_type == 'auth-timeout':
            # Authentication timeout
            logger.error("Authentication timeout")
            self.running = False
            
        elif msg_type == 'connected':
            # Connected to server (either after auth or if auth is disabled)
            if not self.client_id:
                self.client_id = data.get('clientId')
            
            if data.get('iceServers'):
                self.ice_servers = data['iceServers']
            
            logger.info(f"Connected with client ID: {self.client_id}")
            await self._register_as_sender()
            
        elif msg_type == 'registered':
            logger.info(f"Registered as sender for feed: {self.feed_id}")
            
        elif msg_type == 'viewer-joined':
            viewer_id = data.get('viewerId')
            logger.info(f"New viewer joined: {viewer_id}")
            await self._handle_new_viewer(viewer_id)
            
        elif msg_type == 'answer':
            sender_id = data.get('senderId')
            answer = data.get('data')
            await self._handle_answer(sender_id, answer)
            
        elif msg_type == 'ice-candidate':
            sender_id = data.get('senderId')
            candidate = data.get('data')
            await self._handle_ice_candidate(sender_id, candidate)
            
        elif msg_type == 'error':
            logger.error(f"Server error: {data.get('message')}")
    
    async def _authenticate(self):
        """Send authentication credentials to server"""
        message = {
            'type': 'authenticate',
            'deviceId': self.device_id,
            'password': self.device_password
        }
        await self._send_message(message)
        logger.info("Authentication credentials sent")
    
    async def _register_as_sender(self):
        """Register this client as a video sender"""
        message = {
            'type': 'register-sender',
            'feedId': self.feed_id,
            'name': self.feed_name
        }
        await self._send_message(message)
    
    async def _handle_new_viewer(self, viewer_id: str):
        """Handle new viewer by creating peer connection and offer"""
        try:
            # Create peer connection for this viewer
            pc = RTCPeerConnection(configuration={"iceServers": self.ice_servers})
            self.peer_connections[viewer_id] = pc
            
            # Add camera track
            if not self.camera_track:
                self.camera_track = PiCameraTrack()
            
            pc.addTrack(self.camera_track)
            
            # Handle ICE candidates
            @pc.on("icecandidate")
            async def on_ice_candidate(candidate):
                if candidate:
                    await self._send_message({
                        'type': 'ice-candidate',
                        'targetId': viewer_id,
                        'candidate': {
                            'candidate': candidate.candidate,
                            'sdpMLineIndex': candidate.sdpMLineIndex,
                            'sdpMid': candidate.sdpMid
                        }
                    })
            
            # Create and send offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            
            await self._send_message({
                'type': 'offer',
                'targetId': viewer_id,
                'offer': {
                    'type': offer.type,
                    'sdp': offer.sdp
                }
            })
            
            logger.info(f"Created offer for viewer: {viewer_id}")
            
        except Exception as e:
            logger.error(f"Error handling new viewer {viewer_id}: {e}")
    
    async def _handle_answer(self, viewer_id: str, answer_data: Dict[str, Any]):
        """Handle answer from viewer"""
        try:
            pc = self.peer_connections.get(viewer_id)
            if not pc:
                logger.warning(f"No peer connection found for viewer: {viewer_id}")
                return
            
            answer = RTCSessionDescription(
                sdp=answer_data['sdp'],
                type=answer_data['type']
            )
            
            await pc.setRemoteDescription(answer)
            logger.info(f"Set remote description for viewer: {viewer_id}")
            
        except Exception as e:
            logger.error(f"Error handling answer from {viewer_id}: {e}")
    
    async def _handle_ice_candidate(self, viewer_id: str, candidate_data: Dict[str, Any]):
        """Handle ICE candidate from viewer"""
        try:
            pc = self.peer_connections.get(viewer_id)
            if not pc:
                logger.warning(f"No peer connection found for viewer: {viewer_id}")
                return
            
            from aiortc import RTCIceCandidate
            candidate = RTCIceCandidate(
                candidate=candidate_data['candidate'],
                sdpMLineIndex=candidate_data['sdpMLineIndex'],
                sdpMid=candidate_data['sdpMid']
            )
            
            await pc.addIceCandidate(candidate)
            logger.debug(f"Added ICE candidate for viewer: {viewer_id}")
            
        except Exception as e:
            logger.error(f"Error handling ICE candidate from {viewer_id}: {e}")
    
    async def _send_message(self, message: Dict[str, Any]):
        """Send message to server"""
        if self.websocket:
            await self.websocket.send(json.dumps(message))
    
    async def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        self.running = False
        
        # Close peer connections
        for pc in self.peer_connections.values():
            await pc.close()
        self.peer_connections.clear()
        
        # Clean up camera
        if self.camera_track:
            self.camera_track.cleanup()
        
        # Close websocket
        if self.websocket:
            await self.websocket.close()
        
        logger.info("Cleanup complete")


async def main():
    """Main function"""
    # Get device info and configuration
    device_info = get_device_info() if 'get_device_info' in globals() else {}
    
    # Use settings from config
    server_url = SERVER_URL
    device_id = DEVICE_ID
    device_password = DEVICE_PASSWORD
    feed_id = device_info.get('feed_id', FEED_ID)
    feed_name = device_info.get('feed_name', FEED_NAME)
    
    logger.info(f"Starting with device ID: {device_id}")
    logger.info(f"Feed ID: {feed_id}, name: {feed_name}")
    logger.info(f"Server URL: {server_url}")
    
    client = VideoStreamingClient(
        server_url=server_url,
        device_id=device_id,
        device_password=device_password,
        feed_id=feed_id,
        feed_name=feed_name
    )
    
    # Handle shutdown gracefully
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal")
        asyncio.create_task(client.cleanup())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        logger.info("Starting video streaming client...")
        await client.connect()
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Client error: {e}")
    finally:
        await client.cleanup()


if __name__ == "__main__":
    # Check if running on Raspberry Pi
    try:
        with open('/proc/device-tree/model', 'r') as f:
            if 'Raspberry Pi' not in f.read():
                logger.warning("Not running on Raspberry Pi - camera may not work")
    except FileNotFoundError:
        logger.warning("Cannot detect device type - assuming Raspberry Pi")
    
    asyncio.run(main())