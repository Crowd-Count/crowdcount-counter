#!/usr/bin/env python3
"""
Settings configuration for Raspberry Pi Video Streaming Client with Authentication
Modify these values to customize your streaming setup
"""

import os
from typing import List, Dict, Any, Tuple

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()  # Load .env file if it exists
except ImportError:
    print("Note: python-dotenv not installed. Using system environment variables only.")
    print("Install with: pip install python-dotenv")

# =============================================================================
# AUTHENTICATION SETTINGS
# =============================================================================

# Device credentials for authentication - REQUIRED
DEVICE_ID = os.getenv('DEVICE_ID')
DEVICE_PASSWORD = os.getenv('DEVICE_PASSWORD')

# Fallback to defaults if not set (NOT RECOMMENDED for production)
if not DEVICE_ID:
    print("WARNING: DEVICE_ID not set in environment. Using default.")
    DEVICE_ID = 'rpi_camera_01'

if not DEVICE_PASSWORD:
    print("WARNING: DEVICE_PASSWORD not set in environment. Using default.")
    print("Please set DEVICE_PASSWORD in .env file or environment variable!")
    DEVICE_PASSWORD = 'changeme'  # CHANGE THIS!

# Security note: In production, consider:
# 1. Using environment variables for passwords (as shown above)
# 2. Using a secure credential store
# 3. Using certificate-based authentication
# 4. Never committing passwords to version control

# =============================================================================
# SERVER CONNECTION SETTINGS
# =============================================================================

# Server connection details
SERVER_HOST = os.getenv('SERVER_HOST', 'localhost')
SERVER_PORT = int(os.getenv('SERVER_PORT', '3000'))
SERVER_PROTOCOL = os.getenv('SERVER_PROTOCOL', 'ws')  # 'ws' or 'wss' for secure

# Build server URL (you can also set STREAMING_SERVER_URL directly)
if not os.getenv('STREAMING_SERVER_URL'):
    SERVER_URL = f"{SERVER_PROTOCOL}://{SERVER_HOST}:{SERVER_PORT}"
else:
    SERVER_URL = os.getenv('STREAMING_SERVER_URL')

# Connection timeout and retry settings
CONNECTION_TIMEOUT = 10  # seconds
RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY = 5  # seconds between attempts
AUTH_TIMEOUT = 10  # seconds to complete authentication

# =============================================================================
# CAMERA FEED IDENTIFICATION
# =============================================================================

# Feed identification (used by viewers to select this stream)
# By default, uses the device ID as the feed ID
FEED_ID = os.getenv('FEED_ID', DEVICE_ID)
FEED_NAME = os.getenv('FEED_NAME', f'{DEVICE_ID} Camera')

# Optional: Auto-generate unique feed ID based on device
AUTO_GENERATE_FEED_ID = False  # Set to True to append MAC address or hostname

# =============================================================================
# CAMERA CONFIGURATION
# =============================================================================

# Camera resolution settings
CAMERA_RESOLUTION = (1280, 720)  # (width, height)
# Common options:
# - (640, 480)   - VGA
# - (1280, 720)  - HD
# - (1920, 1080) - Full HD
# - (2592, 1944) - Max Pi Camera v2
# - (4056, 3040) - Max Pi Camera v3

# Video format and framerate
CAMERA_FORMAT = 'RGB888'  # Usually leave as RGB888
CAMERA_FRAMERATE = 30     # FPS - adjust based on network/CPU capacity

# Camera sensor settings (advanced)
CAMERA_CONFIG = {
    'size': CAMERA_RESOLUTION,
    'format': CAMERA_FORMAT,
    'framerate': CAMERA_FRAMERATE
}

# Auto-exposure and white balance
CAMERA_AUTO_EXPOSURE = True
CAMERA_AUTO_WHITE_BALANCE = True

# Manual camera controls (only used if auto settings are False)
CAMERA_EXPOSURE_TIME = 10000  # microseconds
CAMERA_GAIN = 1.0
CAMERA_WHITE_BALANCE_R = 1.5
CAMERA_WHITE_BALANCE_B = 1.5

# =============================================================================
# VIDEO ENCODING/QUALITY SETTINGS
# =============================================================================

# Video quality settings for WebRTC
VIDEO_BITRATE_KBPS = 2000  # kilobits per second
VIDEO_MAX_BITRATE_KBPS = 4000
VIDEO_MIN_BITRATE_KBPS = 500

# Video codec preferences (in order of preference)
VIDEO_CODECS = ['H264', 'VP8', 'VP9']

# Frame processing
ENABLE_FRAME_SMOOTHING = True
ENABLE_AUTO_BRIGHTNESS = False
BRIGHTNESS_ADJUSTMENT = 0  # -100 to 100
CONTRAST_ADJUSTMENT = 0    # -100 to 100

# =============================================================================
# WEBRTC CONFIGURATION
# =============================================================================

# ICE servers for NAT traversal
ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
    {"urls": "stun:stun2.l.google.com:19302"},
]

# Additional TURN servers (if you have them)
# ICE_SERVERS.append({
#     "urls": "turn:your-turn-server.com:3478",
#     "username": "your-username",
#     "credential": "your-password"
# })

# WebRTC connection settings
WEBRTC_CONNECTION_TIMEOUT = 15  # seconds
MAX_PEER_CONNECTIONS = 10       # Maximum simultaneous viewers
ENABLE_DATA_CHANNELS = False    # Enable if you want bidirectional communication

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

# Logging level
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')  # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Enable detailed logging for specific components
LOG_CAMERA_STATS = True     # Log camera performance stats
LOG_WEBRTC_STATS = True     # Log WebRTC connection stats
LOG_NETWORK_STATS = False   # Log network performance (verbose)
LOG_AUTH_DETAILS = False    # Log authentication details (NEVER enable in production!)

# Log file settings (set to None to disable file logging)
LOG_FILE = None  # e.g., '/var/log/rpi-streamer.log'
LOG_FILE_MAX_SIZE = 10 * 1024 * 1024  # 10MB
LOG_FILE_BACKUP_COUNT = 3

# =============================================================================
# PERFORMANCE AND MONITORING
# =============================================================================

# Performance monitoring
ENABLE_PERFORMANCE_STATS = True
STATS_INTERVAL = 30  # seconds between stats reports

# Resource limits
MAX_CPU_USAGE = 80        # Percentage - reduce quality if exceeded
MAX_MEMORY_USAGE_MB = 256 # MB - restart if exceeded
MAX_TEMPERATURE = 75      # Celsius - throttle if exceeded

# Frame dropping settings
ENABLE_FRAME_DROPPING = True
MAX_FRAME_QUEUE_SIZE = 5  # Drop frames if queue gets too long

# =============================================================================
# NETWORK SETTINGS
# =============================================================================

# Network interface binding (empty for all interfaces)
BIND_INTERFACE = ''  # e.g., 'eth0', 'wlan0', or '' for all

# Bandwidth management
ADAPTIVE_BITRATE = True   # Automatically adjust bitrate based on network
BANDWIDTH_TEST_INTERVAL = 60  # seconds

# Network quality thresholds
NETWORK_GOOD_RTT_MS = 50     # Consider network good if RTT < this
NETWORK_BAD_RTT_MS = 200     # Consider network bad if RTT > this
PACKET_LOSS_THRESHOLD = 0.05 # 5% packet loss threshold

# =============================================================================
# ADVANCED SETTINGS
# =============================================================================

# Startup behavior
AUTO_START_STREAMING = True   # Start streaming immediately on connection
WAIT_FOR_VIEWERS = False      # Wait for at least one viewer before starting camera

# Error handling
MAX_ERROR_COUNT = 5           # Restart after this many consecutive errors
ERROR_COOLDOWN_TIME = 10      # seconds to wait after error before retry

# Debug features
ENABLE_TEST_PATTERN = False   # Show test pattern instead of camera (for testing)
SAVE_DEBUG_FRAMES = False     # Save frames to disk for debugging
DEBUG_FRAME_INTERVAL = 30     # Save every Nth frame

# Hardware-specific optimizations
ENABLE_GPU_ACCELERATION = True    # Use GPU for encoding if available
ENABLE_HARDWARE_H264 = True       # Use hardware H.264 encoder
THREAD_COUNT = 2                  # Number of encoding threads

# =============================================================================
# SECURITY SETTINGS
# =============================================================================

# Additional authentication options
USE_DEVICE_SERIAL = False    # Use Raspberry Pi serial number as device ID
HASH_PASSWORD_CLIENT_SIDE = False  # Hash password before sending (requires server support)

# Authentication retry settings
MAX_AUTH_ATTEMPTS = 3
AUTH_RETRY_DELAY = 2  # seconds between auth attempts

# SSL/TLS settings for secure connections
SSL_VERIFY = True             # Verify SSL certificates
SSL_CERT_FILE = None          # Path to client certificate if needed
SSL_KEY_FILE = None           # Path to client private key if needed

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_device_info() -> Dict[str, str]:
    """Get device information for identification"""
    import hashlib
    
    info = {
        'hostname': os.uname().nodename,
        'feed_id': FEED_ID,
        'feed_name': FEED_NAME,
        'device_id': DEVICE_ID
    }
    
    try:
        # Try to get MAC address for unique identification
        import uuid
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff)
                       for elements in range(0, 2*6, 8)][::-1])
        info['mac_address'] = mac
        
        if AUTO_GENERATE_FEED_ID:
            info['feed_id'] = f"{FEED_ID}_{mac.replace(':', '')[-6:]}"
            
        # Optionally use Raspberry Pi serial number
        if USE_DEVICE_SERIAL:
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if line.startswith('Serial'):
                            serial = line.split(':')[1].strip()
                            info['device_serial'] = serial
                            if not os.getenv('DEVICE_ID'):
                                info['device_id'] = f"rpi_{serial[-8:]}"
                            break
            except:
                pass
                
    except:
        pass
    
    return info

def validate_settings():
    """Validate configuration settings"""
    errors = []
    warnings = []
    
    # Validate authentication
    if not DEVICE_ID:
        errors.append("DEVICE_ID cannot be empty")
    
    if not DEVICE_PASSWORD or DEVICE_PASSWORD == 'secretpass123':
        warnings.append("DEVICE_PASSWORD should be changed from default value")
    
    if len(DEVICE_PASSWORD) < 8:
        warnings.append("DEVICE_PASSWORD should be at least 8 characters long")
    
    # Validate camera resolution
    if not isinstance(CAMERA_RESOLUTION, tuple) or len(CAMERA_RESOLUTION) != 2:
        errors.append("CAMERA_RESOLUTION must be a tuple of (width, height)")
    
    # Validate framerate
    if not 1 <= CAMERA_FRAMERATE <= 60:
        errors.append("CAMERA_FRAMERATE must be between 1 and 60")
    
    # Validate bitrate settings
    if VIDEO_MIN_BITRATE_KBPS >= VIDEO_MAX_BITRATE_KBPS:
        errors.append("VIDEO_MIN_BITRATE_KBPS must be less than VIDEO_MAX_BITRATE_KBPS")
    
    # Validate server URL
    if not SERVER_URL or not SERVER_URL.startswith(('ws://', 'wss://')):
        errors.append("SERVER_URL must be a valid WebSocket URL")
    
    # Security warnings
    if LOG_AUTH_DETAILS:
        warnings.append("LOG_AUTH_DETAILS is enabled - disable in production!")
    
    if SERVER_PROTOCOL == 'ws' and 'localhost' not in SERVER_HOST and '127.0.0.1' not in SERVER_HOST:
        warnings.append("Using unencrypted WebSocket (ws://) for remote server - consider using wss://")
    
    return errors, warnings

# Validate settings on import
_errors, _warnings = validate_settings()

if _errors:
    print("Configuration ERRORS found:")
    for error in _errors:
        print(f"  ❌ {error}")
    print("Please fix these errors before running the client.")

if _warnings:
    print("Configuration warnings:")
    for warning in _warnings:
        print(f"  ⚠️  {warning}")

# =============================================================================
# ENVIRONMENT-SPECIFIC OVERRIDES
# =============================================================================

# Development settings
if os.getenv('ENV') == 'development':
    LOG_LEVEL = 'DEBUG'
    ENABLE_PERFORMANCE_STATS = True
    SAVE_DEBUG_FRAMES = True
    LOG_AUTH_DETAILS = True  # OK for development

# Production settings  
elif os.getenv('ENV') == 'production':
    LOG_LEVEL = 'WARNING'
    ENABLE_PERFORMANCE_STATS = False
    SAVE_DEBUG_FRAMES = False
    LOG_AUTH_DETAILS = False  # Never in production
    MAX_ERROR_COUNT = 10
    
    # Enforce security in production
    if not os.getenv('DEVICE_PASSWORD'):
        raise ValueError("DEVICE_PASSWORD must be set via environment variable in production")

# Testing settings
elif os.getenv('ENV') == 'testing':
    ENABLE_TEST_PATTERN = True
    LOG_LEVEL = 'DEBUG'
    CONNECTION_TIMEOUT = 5
    AUTH_TIMEOUT = 5