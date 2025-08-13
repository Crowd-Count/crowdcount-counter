# Minimal container that uses host's libcamera
FROM python:3.11-slim-bookworm

# Install only essential packages
RUN apt-get update && apt-get install -y \
    # OpenCV dependencies
    libopencv-dev \
    # Media libraries
    libavformat-dev \
    libavcodec-dev \
    libavutil-dev \
    libswscale-dev \
    # Build essentials
    build-essential \
    pkg-config \
    # Clean up
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py settings.py ./

# Create logs directory
RUN mkdir -p /app/logs

# Create non-root user
RUN useradd -m -u 1000 streamer && \
    usermod -a -G video streamer && \
    chown -R streamer:streamer /app

USER streamer

ENV PYTHONUNBUFFERED=1

CMD ["python3", "main.py"]