#!/bin/bash

# Deployment script for Raspberry Pi video streamer Docker container

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Raspberry Pi Video Streamer Docker Deployment ===${NC}"

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo -e "${YELLOW}Warning: Not running on Raspberry Pi. Camera functionality may not work.${NC}"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for .env file
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    echo "Creating template .env file..."
    cat > .env << 'EOF'
# Raspberry Pi Client Configuration
# Server Connection
SERVER_HOST=localhost
SERVER_PORT=3000
SERVER_PROTOCOL=ws

# Device Authentication (CHANGE THESE!)
DEVICE_ID=rpi_camera_01
DEVICE_PASSWORD=changeme

# Feed Information
FEED_ID=rpi_camera_01
FEED_NAME=Raspberry Pi Camera

# Environment
ENV=production

# Logging
LOG_LEVEL=INFO
EOF
    echo -e "${YELLOW}Please edit .env file with your configuration before running again.${NC}"
    exit 1
fi

# Create logs directory
mkdir -p logs

# Function to check Docker installation
check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Docker is not installed!${NC}"
        echo "Install Docker with: curl -sSL https://get.docker.com | sh"
        echo "Add user to docker group: sudo usermod -aG docker $USER"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        echo -e "${YELLOW}docker-compose not found, trying docker compose...${NC}"
        if ! docker compose version &> /dev/null; then
            echo -e "${RED}Docker Compose is not installed!${NC}"
            echo "Install with: sudo apt-get install docker-compose-plugin"
            exit 1
        fi
        COMPOSE_CMD="docker compose"
    else
        COMPOSE_CMD="docker-compose"
    fi
}

# Function to enable camera
enable_camera() {
    echo -e "${GREEN}Checking camera configuration...${NC}"
    
    # Check if camera is enabled in config
    if ! raspi-config nonint get_camera 2>/dev/null; then
        echo -e "${YELLOW}Enabling camera interface...${NC}"
        sudo raspi-config nonint do_camera 0
        echo -e "${YELLOW}Camera enabled. A reboot may be required.${NC}"
    fi
    
    # Check for camera detection
    if command -v libcamera-hello &> /dev/null; then
        if ! timeout 2 libcamera-hello --list-cameras &> /dev/null; then
            echo -e "${YELLOW}Camera not detected. Please check connections.${NC}"
        else
            echo -e "${GREEN}Camera detected successfully.${NC}"
        fi
    fi
}

# Parse command line arguments
ACTION=${1:-up}

case $ACTION in
    up|start)
        check_docker
        enable_camera
        echo -e "${GREEN}Starting container...${NC}"
        $COMPOSE_CMD up -d --build
        echo -e "${GREEN}Container started. View logs with: docker logs -f crowdcount-streamer${NC}"
        ;;
    
    down|stop)
        check_docker
        echo -e "${YELLOW}Stopping container...${NC}"
        $COMPOSE_CMD down
        echo -e "${GREEN}Container stopped.${NC}"
        ;;
    
    restart)
        check_docker
        echo -e "${YELLOW}Restarting container...${NC}"
        $COMPOSE_CMD restart
        echo -e "${GREEN}Container restarted.${NC}"
        ;;
    
    logs)
        docker logs -f crowdcount-streamer
        ;;
    
    build)
        check_docker
        echo -e "${GREEN}Building image...${NC}"
        $COMPOSE_CMD build --no-cache
        echo -e "${GREEN}Build complete.${NC}"
        ;;
    
    status)
        check_docker
        echo -e "${GREEN}Container status:${NC}"
        docker ps -a | grep crowdcount-streamer || echo "Container not found"
        ;;
    
    shell)
        check_docker
        echo -e "${GREEN}Opening shell in container...${NC}"
        docker exec -it crowdcount-streamer /bin/bash
        ;;
    
    test)
        check_docker
        enable_camera
        echo -e "${GREEN}Running test mode...${NC}"
        docker run --rm -it \
            --privileged \
            --device /dev/vchiq:/dev/vchiq \
            -v /opt/vc:/opt/vc:ro \
            -v ./.env:/app/.env:ro \
            --env-file .env \
            --network host \
            crowdcount-counter-rpi-streamer \
            python3 -c "from picamera2 import Picamera2; print('Camera import successful')"
        ;;
    
    *)
        echo "Usage: $0 {up|down|restart|logs|build|status|shell|test}"
        echo ""
        echo "  up/start  - Build and start the container"
        echo "  down/stop - Stop and remove the container"
        echo "  restart   - Restart the container"
        echo "  logs      - Follow container logs"
        echo "  build     - Rebuild the Docker image"
        echo "  status    - Show container status"
        echo "  shell     - Open shell in running container"
        echo "  test      - Test camera connectivity"
        exit 1
        ;;
esac