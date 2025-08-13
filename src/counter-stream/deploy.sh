#!/usr/bin/env bash
# Raspberry Pi Video Streamer - Docker deployment helper
# Usage:
#   ./deploy.sh up        # build (if needed) and start in background
#   ./deploy.sh down      # stop and remove containers
#   ./deploy.sh rebuild   # rebuild without cache, then up -d
#   ./deploy.sh logs      # follow logs for all services
#   ./deploy.sh ps        # show compose status
#   ./deploy.sh shell     # open a bash shell in the running container (best-effort)
# Notes:
# - This script NEVER writes to .env.
# - It only warns if the camera isn't detected; container still starts.

set -Eeuo pipefail

TITLE="=== Raspberry Pi Video Streamer Docker Deployment ==="
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
SERVICE_GUESS="${SERVICE_OVERRIDE:-rpi-streamer}"   # override with SERVICE_OVERRIDE if your service name differs
CONTAINER_GUESS="${CONTAINER_OVERRIDE:-crowdcount-streamer}" # override with CONTAINER_OVERRIDE if you set container_name

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "$SCRIPT_DIR"

say() { echo -e "$*"; }

need_file() {
  if [[ ! -f "$1" ]]; then
    say "Error: required file '$1' not found in $(pwd)"
    exit 1
  fi
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif have_cmd docker-compose; then
    say "docker-compose found (legacy)."
    COMPOSE=(docker-compose)
  else
    say "Error: Neither 'docker compose' nor 'docker-compose' is installed."
    exit 1
  fi
}

warn_compose_version_key() {
  # Don't modify the file; just warn if deprecated 'version:' is present
  if grep -E -q '^[[:space:]]*version:' "$COMPOSE_FILE"; then
    say "Note: '$COMPOSE_FILE' contains a 'version:' key which is deprecated in modern Compose and will be ignored."
    say "      Consider removing it to avoid warnings."
  fi
}

check_camera_nonblocking() {
  say "Checking camera configuration..."
  if have_cmd libcamera-hello; then
    if libcamera-hello --list-cameras 2>/dev/null | grep -qE '^Available cameras'; then
      say "Camera detected."
    else
      say "Camera NOT detected by libcamera. Container will still start."
      say "Tip: On the host, test with: libcamera-hello -t 2000"
      say "     If it fails, check ribbon cable, enable camera, and run: v4l2-ctl --list-devices"
    fi
  else
    say "libcamera-hello not found on host. Skipping camera check. (Install 'libcamera-apps' on Pi OS Bookworm to enable this check.)"
  fi
}

compose() { "${COMPOSE[@]}" -f "$COMPOSE_FILE" "$@"; }

container_name_guess() {
  # 1) Prefer an explicitly running container that matches container_name guess
  local c
  c="$(docker ps --format '{{.Names}}' | grep -E "^${CONTAINER_GUESS}$" || true)"
  if [[ -n "$c" ]]; then echo "$c"; return 0; fi

  # 2) Fall back to a container derived from the service name
  c="$(docker ps --format '{{.Names}}' | grep -E "${SERVICE_GUESS}" | head -n1 || true)"
  if [[ -n "$c" ]]; then echo "$c"; return 0; fi

  # 3) As a last resort, take the first container for this compose project
  local project
  project="$("${COMPOSE[@]}" -f "$COMPOSE_FILE" ps --services 2>/dev/null | head -n1 || true)"
  if [[ -n "$project" ]]; then
    c="$(docker ps --format '{{.Names}}' | grep -E "${project}" | head -n1 || true)"
    if [[ -n "$c" ]]; then echo "$c"; return 0; fi
  fi

  # nothing found
  echo ""
  return 1
}

usage() {
  cat <<EOF
$TITLE

Commands:
  up        Build if needed and start containers in background
  down      Stop and remove containers
  rebuild   Rebuild images without cache, then start
  logs      Follow logs for all services
  ps        Show Compose status
  shell     Open a bash shell in the running container (best-effort)

Environment overrides:
  COMPOSE_FILE         Path to compose file (default: docker-compose.yml)
  SERVICE_OVERRIDE     Override service name guess for 'logs'/'shell' (default: rpi-streamer)
  CONTAINER_OVERRIDE   Override container name guess for 'shell' (default: crowdcount-streamer)

This script DOES NOT modify your .env.
EOF
}

main() {
  local cmd="${1:-}"
  if [[ -z "$cmd" ]]; then usage; exit 0; fi

  say "$TITLE"

  need_file "$COMPOSE_FILE"
  detect_compose
  warn_compose_version_key

  case "$cmd" in
    up)
      check_camera_nonblocking
      say "Starting container..."
      compose up -d --build
      compose ps
      ;;

    down)
      compose down
      ;;

    rebuild)
      say "Rebuilding images without cache..."
      compose build --no-cache
      say "Starting container..."
      compose up -d
      compose ps
      ;;

    logs)
      # Show all services' logs by default
      compose logs -f
      ;;

    ps)
      compose ps
      ;;

    shell)
      say "Attempting to open a shell inside the running container…"
      local cname
      cname="$(container_name_guess || true)"
      if [[ -z "$cname" ]]; then
        say "Could not determine container name. Ensure it's running, or set CONTAINER_OVERRIDE."
        exit 1
      fi
      exec docker exec -it "$cname" bash
      ;;

    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"