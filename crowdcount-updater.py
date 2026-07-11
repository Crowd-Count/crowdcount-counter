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
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import requests

# ── Configuration ────────────────────────────────────────────────────────
UPDATE_INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours
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
            section = (
                config["DEFAULT"]
                if "DEFAULT" in config
                else config[config.sections()[0]]
            )
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
        raise RuntimeError(
            f"Device {device_id} found but API_PASSWORD is empty in device-identity.conf"
        )
    raise RuntimeError("Could not load device identity from any known path")


def sign_request(
    device_id: str, password: str, method: str, url: str, body: str
) -> dict:
    """Compute HMAC-SHA256 signature headers (same scheme as stream_to_mediamtx)."""
    from urllib.parse import urlparse

    signing_key = hashlib.sha256(f"{device_id}:{password}".encode()).digest()
    path = urlparse(url).path
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    string_to_sign = f"{method}\n{path}\n{body_hash}\n{timestamp}\n{nonce}"
    signature = hmac_mod.new(
        signing_key, string_to_sign.encode(), hashlib.sha256
    ).hexdigest()
    return {
        "X-CC-Signature": signature,
        "X-CC-Timestamp": timestamp,
        "X-CC-Nonce": nonce,
        "X-CC-Device-Id": device_id,
        "X-CC-Sig-Version": "1",
    }


def get_current_commit() -> str:
    """Return the current HEAD commit hash via git rev-parse (handles packed refs)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.error("git rev-parse HEAD failed: %s", result.stderr.strip())
        return ""
    except Exception as e:
        logger.error("Could not get git commit: %s", e)
        return ""


def report_version(device_id: str, password: str, commit_hash: str) -> None:
    """POST the current commit hash to the API server."""
    url = f"{API_BASE_URL}/report_version"
    payload = json.dumps(
        {
            "device_id": device_id,
            "password": password,
            "commit_hash": commit_hash,
        }
    )
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid.uuid4()),
    }
    headers.update(sign_request(device_id, password, "POST", url, payload))

    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=30)
        if resp.ok:
            logger.info("Reported version %s to server", commit_hash[:8])
        else:
            logger.warning(
                "Version report failed (%s): %s", resp.status_code, resp.text
            )
    except Exception as exc:
        logger.warning("Could not reach API to report version: %s", exc)


def ensure_root_ssh_config() -> None:
    """Copy counter user's SSH config and keys to root if missing.

    The updater runs as root but the SSH deploy key for GitHub
    is configured under the counter user.
    """
    root_ssh = Path("/root/.ssh")
    root_config = root_ssh / "config"
    counter_ssh = Path("/home/counter/.ssh")
    counter_config = counter_ssh / "config"

    # Already set up?
    if (
        root_config.exists()
        and "github-crowdcount-counter-ro" in root_config.read_text()
    ):
        known_hosts = root_ssh / "known_hosts"
        if known_hosts.exists() and "github.com" in known_hosts.read_text():
            return

    if not counter_config.exists():
        logger.warning("No SSH config found at %s", counter_config)
        return

    try:
        root_ssh.mkdir(mode=0o700, exist_ok=True)

        # Copy SSH config
        if (
            not root_config.exists()
            or "github-crowdcount-counter-ro" not in root_config.read_text()
        ):
            shutil.copy2(counter_config, root_config)
            root_config.chmod(0o600)
            logger.info("Copied SSH config to root from counter user")

        # Copy key files referenced in the config
        for line in counter_config.read_text().splitlines():
            line = line.strip()
            if line.startswith("IdentityFile"):
                key_name = Path(line.split()[1]).name
                src = counter_ssh / key_name
                dest = root_ssh / key_name
                if src.exists() and not dest.exists():
                    shutil.copy2(src, dest)
                    dest.chmod(0o600)
                    logger.info("Copied SSH key %s to root", key_name)

        # Add GitHub host key to known_hosts if missing
        known_hosts = root_ssh / "known_hosts"
        if not known_hosts.exists() or "github.com" not in known_hosts.read_text():
            result = subprocess.run(
                ["ssh-keyscan", "github.com"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                with open(known_hosts, "a") as f:
                    f.write(result.stdout)
                known_hosts.chmod(0o600)
                logger.info("Added GitHub host key to root known_hosts")
    except Exception as exc:
        logger.warning("Could not set up root SSH config: %s", exc)


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
    try:
        fetch = subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.warning("git fetch timed out")
        return
    if fetch.returncode != 0:
        logger.warning("git fetch failed: %s", fetch.stderr.strip())
        return

    # Compare HEAD vs origin/main
    local = get_current_commit()
    try:
        remote_result = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        logger.warning("git rev-parse timed out")
        return
    remote = remote_result.stdout.strip()

    if local == remote:
        logger.info("Already up to date (%s)", local[:8])
        return

    logger.info("Update available: %s -> %s", local[:8], remote[:8])

    # Discard local changes (e.g. chmod +x from install scripts) so pull doesn't fail
    subprocess.run(
        ["git", "checkout", "--", "."],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )

    # Pull
    try:
        pull = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning("git pull timed out")
        return
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

    ensure_root_ssh_config()

    # Report current version immediately on startup
    commit = get_current_commit()
    logger.info("Current version: %s", commit[:8])

    # Wait for network before attempting git operations.
    # On fresh devices, WiFi may take minutes (saved creds or Bluetooth provisioning).
    NETWORK_CHECK_INTERVAL = 30  # seconds between checks
    NETWORK_MAX_WAIT = 60 * 60  # wait up to 1 hour for network
    waited = 0
    while waited < NETWORK_MAX_WAIT:
        try:
            import socket

            socket.create_connection(("github.com", 443), timeout=5).close()
            logger.info("Network is up — can reach GitHub")
            break
        except OSError:
            if waited == 0:
                logger.info("Waiting for network connectivity...")
            time.sleep(NETWORK_CHECK_INTERVAL)
            waited += NETWORK_CHECK_INTERVAL
    else:
        logger.warning(
            "No network after %d minutes — will keep trying in background",
            NETWORK_MAX_WAIT // 60,
        )

    report_version(device_id, password, commit)

    # Check for updates now that network is (likely) up
    try:
        check_and_update(device_id, password)
    except Exception as exc:
        logger.warning("Boot update check failed: %s", exc)

    # Then check periodically
    while True:
        time.sleep(UPDATE_INTERVAL_SECONDS)
        try:
            check_and_update(device_id, password)
        except Exception as exc:
            logger.error("Update check failed: %s", exc)
        # Always report version as a heartbeat, regardless of update result
        try:
            current_commit = get_current_commit()
            report_version(device_id, password, current_commit)
        except Exception as exc:
            logger.warning("Periodic version report failed: %s", exc)


if __name__ == "__main__":
    main()
