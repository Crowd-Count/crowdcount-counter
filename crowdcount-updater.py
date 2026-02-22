#!/usr/bin/env python3
"""
CrowdCount Auto-Updater
Periodically checks for git updates, pulls new code, restarts the main service,
and reports the current version to the API server.
"""

import configparser
import hashlib
import hmac as hmac_mod
import json
import logging
import os
import subprocess
import time
import uuid
from pathlib import Path

import requests

# ── Configuration ────────────────────────────────────────────────────────
UPDATE_INTERVAL_SECONDS = 24 * 60 * 60  # 24 hours
API_BASE_URL = "https://api.crowdcount.tech"
REPO_DIR = Path(__file__).parent
MAIN_SERVICE = "crowdcount-main.service"
UPDATER_SERVICE = "crowdcount-updater.service"

IDENTITY_PATHS = [
    Path("/boot/firmware/device-identity.conf"),
    Path("/boot/device-identity.conf"),
]

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crowdcount-updater")


# ── Helpers ──────────────────────────────────────────────────────────────

def load_identity() -> tuple:
    """Load device_id and password from device-identity.conf.

    Returns (device_id, api_password) or raises RuntimeError.
    """
    device_id = None
    password = None

    for path in IDENTITY_PATHS:
        if path.exists():
            # Try configparser first
            config = configparser.ConfigParser()
            config.read(path)
            section = config["DEFAULT"] if "DEFAULT" in config else config[config.sections()[0]]
            device_id = section.get("DEVICE_ID") or None
            password = section.get("API_PASSWORD") or None

            # Fallback: read API_PASSWORD with raw line parsing
            if device_id and not password:
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("API_PASSWORD="):
                            val = line.split("=", 1)[1].strip()
                            if val:
                                password = val
                                break

            if device_id and password:
                return device_id, password

    if device_id and not password:
        raise RuntimeError(f"Device {device_id} found but API_PASSWORD is empty in device-identity.conf")
    raise RuntimeError("Could not load device identity from any known path")


def sign_request(device_id: str, password: str, method: str, url: str, body: str) -> dict:
    """Compute HMAC-SHA256 signature headers (same scheme as stream_to_mediamtx)."""
    from urllib.parse import urlparse

    signing_key = hashlib.sha256(f"{device_id}:{password}".encode()).digest()
    path = urlparse(url).path
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    string_to_sign = f"{method}\n{path}\n{body_hash}\n{timestamp}\n{nonce}"
    signature = hmac_mod.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        "X-CC-Signature": signature,
        "X-CC-Timestamp": timestamp,
        "X-CC-Nonce": nonce,
        "X-CC-Device-Id": device_id,
        "X-CC-Sig-Version": "1",
    }


def get_current_commit() -> str:
    """Return the current HEAD commit hash by reading .git directly."""
    try:
        git_dir = REPO_DIR / ".git"
        head_file = git_dir / "HEAD"
        head = head_file.read_text().strip()
        if head.startswith("ref: "):
            ref_path = git_dir / head[5:]
            return ref_path.read_text().strip()
        return head
    except Exception as e:
        logger.error("Could not read git commit: %s", e)
        return ""


def report_version(device_id: str, password: str, commit_hash: str) -> None:
    """POST the current commit hash to the API server."""
    url = f"{API_BASE_URL}/report_version"
    payload = json.dumps({
        "device_id": device_id,
        "password": password,
        "commit_hash": commit_hash,
    })
    headers = {"Content-Type": "application/json"}
    headers.update(sign_request(device_id, password, "POST", url, payload))

    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=30)
        if resp.ok:
            logger.info("Reported version %s to server", commit_hash[:8])
        else:
            logger.warning("Version report failed (%s): %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.warning("Could not reach API to report version: %s", exc)


def ensure_git_safe_directory() -> None:
    """Mark the repo directory as safe for git (needed when service runs as root
    but repo is owned by another user)."""
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", str(REPO_DIR)],
        capture_output=True,
        text=True,
    )


def check_and_update(device_id: str, password: str) -> None:
    """Fetch origin/main, pull if changed, restart main service, report version."""
    logger.info("Checking for updates...")

    ensure_git_safe_directory()

    # Fetch latest
    fetch = subprocess.run(
        ["git", "fetch", "origin", "main"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        logger.warning("git fetch failed: %s", fetch.stderr.strip())
        return

    # Compare HEAD vs origin/main
    local = get_current_commit()
    remote_result = subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    remote = remote_result.stdout.strip()

    if local == remote:
        logger.info("Already up to date (%s)", local[:8])
        return

    logger.info("Update available: %s -> %s", local[:8], remote[:8])

    # Pull
    pull = subprocess.run(
        ["git", "pull", "origin", "main"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    if pull.returncode != 0:
        logger.error("git pull failed: %s", pull.stderr.strip())
        return

    logger.info("Pull complete")

    # Restart main service
    restart = subprocess.run(
        ["systemctl", "restart", MAIN_SERVICE],
        capture_output=True,
        text=True,
    )
    if restart.returncode != 0:
        logger.warning("Failed to restart %s: %s", MAIN_SERVICE, restart.stderr.strip())
    else:
        logger.info("Restarted %s", MAIN_SERVICE)

    # Report new version
    new_commit = get_current_commit()
    report_version(device_id, password, new_commit)

    # Restart ourselves so the updater runs the new code too.
    # --no-block queues the restart asynchronously so we can finish logging
    # before systemd kills this process.
    logger.info("Restarting updater service to pick up new code")
    subprocess.run(
        ["systemctl", "restart", "--no-block", UPDATER_SERVICE],
        capture_output=True,
        text=True,
    )


# ── Main loop ────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("CrowdCount updater starting")

    device_id, password = load_identity()
    logger.info("Device: %s", device_id)

    # Report current version immediately on startup
    commit = get_current_commit()
    logger.info("Current version: %s", commit[:8])
    report_version(device_id, password, commit)

    # Check for updates immediately on startup
    try:
        check_and_update(device_id, password)
    except Exception as exc:
        logger.error("Initial update check failed: %s", exc)

    # Then check periodically
    while True:
        time.sleep(UPDATE_INTERVAL_SECONDS)
        try:
            check_and_update(device_id, password)
        except Exception as exc:
            logger.error("Update check failed: %s", exc)


if __name__ == "__main__":
    main()
