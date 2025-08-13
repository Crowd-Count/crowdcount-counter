# Raspberry Pi video streaming client
FROM python:3.11-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # Camera and media
    libcamera0.2 \
    libcamera-tools \
    python3-libcamera \
    python3-kms++ \
    libopencv-dev \
    python3-opencv \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    v4l-utils \
    # Build tools
    build-essential \
    cmake \
    pkg-config \
    libssl-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py settings.py ./

# Create non-root user with video group access
RUN useradd -m -u 1000 streamer && \
    usermod -a -G video,render streamer && \
    chown -R streamer:streamer /app

USER streamer

ENV PYTHONUNBUFFERED=1

CMD ["python3", "main.py"]