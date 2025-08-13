# Multi-stage build for Raspberry Pi video streaming client
FROM python:3.11-slim-bookworm AS base

# Install system dependencies for camera and video processing
RUN apt-get update && apt-get install -y \
    # Camera dependencies
    libcamera0 \
    libcamera-apps-lite \
    libcamera-dev \
    python3-libcamera \
    python3-kms++ \
    # OpenCV dependencies
    libopencv-dev \
    python3-opencv \
    # Video/media dependencies
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavfilter-dev \
    v4l-utils \
    # Build tools
    build-essential \
    cmake \
    pkg-config \
    # Networking
    libssl-dev \
    # Cleanup
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    picamera2 \
    opencv-python \
    numpy \
    websockets \
    aiortc \
    av \
    python-dotenv

# Copy application code
COPY . .

# Create a non-root user for security
RUN useradd -m -u 1000 streamer && \
    usermod -a -G video streamer && \
    chown -R streamer:streamer /app

# Switch to non-root user
USER streamer

# Environment variables (can be overridden)
ENV PYTHONUNBUFFERED=1
ENV SERVER_HOST=localhost
ENV SERVER_PORT=3000
ENV SERVER_PROTOCOL=ws
ENV LOG_LEVEL=INFO

# Run the application
CMD ["python3", "main.py"]