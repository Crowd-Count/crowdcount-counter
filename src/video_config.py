"""
Video Configuration for CrowdCount Counter (Device Side)
Central configuration for video settings on Raspberry Pi devices

Change these values to adjust FPS and resolution globally.
These should match the server-side settings in crowdcount-counter-server.
"""

# =============================================================================
# VIDEO SETTINGS - Change these values to adjust FPS and resolution globally
# =============================================================================
VIDEO_FPS = 15  # Frames per second (was 30)
VIDEO_WIDTH = 640  # Video width in pixels
VIDEO_HEIGHT = 480  # Video height in pixels
# =============================================================================
