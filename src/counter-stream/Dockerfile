# Pi 5 / Bookworm friendly base
FROM python:3.11-bookworm

# Allow Raspberry Pi OS packages inside the container
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg2 ca-certificates && \
    curl -fsSL https://archive.raspberrypi.org/debian/raspberrypi.gpg.key \
      | gpg --dearmor -o /usr/share/keyrings/raspberrypi-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.gpg arch=arm64] http://archive.raspberrypi.org/debian/ bookworm main" \
      > /etc/apt/sources.list.d/raspi.list

# Camera + media deps from apt (correct package names for Bookworm)
# NOTE: we install python3-picamera2 and python3-opencv via apt; do NOT pip them.
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3-picamera2 \
      libcamera-apps \
      libcamera0 \
      libcamera-v4l2 \
      python3-opencv \
      v4l-utils \
      ffmpeg \
      build-essential cmake pkg-config \
      libssl-dev \
      libavformat-dev libavcodec-dev libavdevice-dev \
      libavutil-dev libswscale-dev libswresample-dev libavfilter-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy & install Python deps (strip ones provided by apt)
COPY requirements.txt /tmp/requirements.txt
RUN sed -i '/^picamera2/d;/^opencv-python/d' /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY . /app

ENV PYTHONUNBUFFERED=1 \
    LIBCAMERA_LOG_LEVELS="*:2"

CMD ["python", "main.py"]