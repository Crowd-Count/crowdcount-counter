#!/usr/bin/env python3
"""
Upstream token self-enrollment for the CrowdCount updater.

A device with no UPSTREAM_API_TOKEN in device-identity.conf (or whose
token the streamer flagged fatally rejected) asks crowdcount-server to
broker a fresh device-scoped Upstream token, proving its identity with
the DEVICE_ID + API_PASSWORD HMAC it was born with. The token is then
persisted into the identity file for start_stream.sh to pick up.

Standalone on purpose (no import from crowdcount-updater) — the codebase
deliberately duplicates the HMAC scheme per standalone script.
"""

import hashlib
import hmac as hmac_mod
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

import requests

# ── Configuration ────────────────────────────────────────────────────────
# Written by the streamer when Upstream fatally rejects the token
# (token_revoked/token_expired); its presence triggers a re-enroll here.
# /tmp is tmpfs, so it vanishes on reboot — acceptable, the fatal state
# just re-surfaces on the streamer's next failed call.
TOKEN_FATAL_SENTINEL = Path("/tmp/crowdcount-upstream-token-fatal")

IDENTITY_PATHS = [
    Path("/boot/firmware/device-identity.conf"),
    Path("/boot/device-identity.conf"),
]

# Every provision rotates the token server-side, so retries are for
# transient failures only: connection errors and 401s (cold-boot clock
# skew makes HMAC signatures invalid until NTP lands). Anything else
# waits for the caller's next 6-hour cycle.
PROVISION_ATTEMPTS = 3
PROVISION_RETRY_DELAY_S = 20

logger = logging.getLogger("upstream-enroll")


# ── Helpers ──────────────────────────────────────────────────────────────


def _token_prefix(token: str) -> str:
    """Loggable form of a token: its prefix only, never the secret tail."""
    parts = token.split("_")
    if len(parts) > 3:
        return "_".join(parts[:3])
    return "_".join(parts[:2]) + "_"


def sign_request(
    device_id: str, password: str, method: str, url: str, body: str
) -> dict:
    """Compute HMAC-SHA256 signature headers (same scheme as crowdcount-updater)."""
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


def read_current_token(identity_path):
    """Return the UPSTREAM_API_TOKEN currently in the identity file, or None.

    Mirrors start_stream.sh get_config_value: first line starting exactly
    with KEY= (comments and indented lines never match), value is
    everything after the first '=' with spaces removed.
    """
    try:
        with open(identity_path) as f:
            for line in f:
                if line.startswith("UPSTREAM_API_TOKEN="):
                    value = line.split("=", 1)[1].replace(" ", "").strip()
                    return value or None
    except OSError:
        return None
    return None


def _has_usable_identity(identity_path) -> bool:
    """True when the file has non-empty DEVICE_ID and API_PASSWORD lines.

    Same first-KEY=-line-wins parsing as read_current_token. Gates the
    .bak refresh in write_token: a primary that fails this check must
    never overwrite a backup, or a power-cut-corrupted primary would
    destroy the device's last good copy of its identity.
    """
    values = {}
    try:
        with open(identity_path) as f:
            for line in f:
                for key in ("DEVICE_ID", "API_PASSWORD"):
                    if key not in values and line.startswith(key + "="):
                        values[key] = line.split("=", 1)[1].replace(" ", "").strip()
    except OSError:
        return False
    return bool(values.get("DEVICE_ID") and values.get("API_PASSWORD"))


# ── Provisioning ─────────────────────────────────────────────────────────


def provision_token(device_id: str, password: str, api_base_url: str, timeout: int):
    """Ask crowdcount-server to broker a fresh Upstream device token.

    Signed POST /provision_upstream_token with the device's own HMAC
    identity. Returns the plaintext token, or None (caller retries next
    cycle). The token itself is never logged — prefix only.
    """
    url = f"{api_base_url}/provision_upstream_token"
    for attempt in range(1, PROVISION_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(PROVISION_RETRY_DELAY_S)

        # Fresh signature per attempt: timestamps are windowed and nonces
        # are one-time, so a retried request must be re-signed.
        payload = json.dumps({"device_id": device_id})
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        }
        headers.update(sign_request(device_id, password, "POST", url, payload))

        try:
            resp = requests.post(url, data=payload, headers=headers, timeout=timeout)
        except Exception as exc:
            logger.warning(
                "Token provision attempt %d/%d failed: %s",
                attempt,
                PROVISION_ATTEMPTS,
                exc,
            )
            continue

        if resp.status_code == 401:
            # Cold-boot clock skew: HMAC calls 401 until NTP syncs
            logger.warning(
                "Token provision attempt %d/%d rejected (401) - retrying",
                attempt,
                PROVISION_ATTEMPTS,
            )
            continue

        if not resp.ok:
            # 429/5xx: server-side trouble, give up until the next cycle
            logger.warning(
                "Token provision failed (%s) - will retry next cycle",
                resp.status_code,
            )
            return None

        try:
            token = resp.json().get("upstream_api_token") or None
        except Exception:
            token = None
        if not token:
            logger.warning("Token provision response had no token")
            return None
        logger.info("Provisioned Upstream token %s...", _token_prefix(token))
        return token

    return None


def write_token(identity_path, token: str) -> bool:
    """Persist UPSTREAM_API_TOKEN into the identity file, FAT32-safely.

    The identity file is the device's soul on a non-journaled FAT32 boot
    partition, so never truncate it in place: back up the original, write
    the full new content to a temp file on the same partition, fsync, then
    atomically replace. On any failure the original is left untouched and
    this returns False.
    """
    identity_path = Path(identity_path)
    try:
        original = identity_path.read_text()
    except Exception as exc:
        logger.error("Could not read %s: %s", identity_path, exc)
        return False

    # Replace the live KEY= line if there is one, else uncomment the
    # template's commented line, else append. Plain KEY=VALUE at line
    # start, so both configparser and the start_stream.sh grep see it.
    lines = original.splitlines()
    new_line = f"UPSTREAM_API_TOKEN={token}"
    target = None
    for i, line in enumerate(lines):
        if line.startswith("UPSTREAM_API_TOKEN="):
            target = i
            break
        if target is None and line.lstrip("# \t").startswith("UPSTREAM_API_TOKEN="):
            target = i
    if target is None:
        lines.append(new_line)
    else:
        lines[target] = new_line
    content = "\n".join(lines) + "\n"

    # Best-effort backup first: load_identity falls back to it if a power
    # cut corrupts the primary mid-write. Only refresh it from a primary
    # that still parses as a usable identity — copying a corrupt primary
    # (the exact case the .bak exists for) would clobber the last good one.
    backup_path = identity_path.with_name(identity_path.name + ".bak")
    if _has_usable_identity(identity_path):
        try:
            shutil.copy2(identity_path, backup_path)
        except Exception as exc:
            logger.warning("Could not back up %s: %s", identity_path, exc)
    else:
        logger.warning(
            "%s has no usable identity - keeping existing backup %s",
            identity_path,
            backup_path,
        )

    tmp_path = identity_path.with_name(identity_path.name + ".tmp")
    try:
        with open(tmp_path, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, identity_path)
    except Exception as exc:
        logger.error("Could not write token to %s: %s", identity_path, exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False

    # Best-effort directory fsync: non-journaled FAT32 may not have flushed
    # the rename's directory entry yet, so a power cut here could still
    # surface old/new/missing states. Shrinks that window; never fatal.
    try:
        dir_fd = os.open(identity_path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass

    logger.info(
        "Wrote UPSTREAM_API_TOKEN (%s...) to %s", _token_prefix(token), identity_path
    )
    return True


def maybe_enroll(device_id: str, password: str, api_base_url: str) -> bool:
    """Provision and persist an Upstream token when this device needs one.

    Returns True only when a NEW token was written (the caller restarts
    the main service so start_stream.sh re-reads it). Steady state —
    token present, no fatal sentinel — is a cheap no-op with no network
    I/O, so this is safe to call every update cycle.
    """
    identity_path = next((p for p in IDENTITY_PATHS if p.exists()), None)
    if identity_path is None:
        logger.warning("No identity file found - cannot enroll Upstream token")
        return False

    token = read_current_token(identity_path)
    sentinel = TOKEN_FATAL_SENTINEL.exists()
    if token and not sentinel:
        return False

    if sentinel:
        logger.info("Fatal-token sentinel present - re-provisioning Upstream token")
    else:
        logger.info("No Upstream token in %s - provisioning", identity_path)

    new_token = provision_token(device_id, password, api_base_url, timeout=30)
    if not new_token:
        # Leave the sentinel in place so the next cycle retries
        return False

    if not write_token(identity_path, new_token):
        return False

    try:
        TOKEN_FATAL_SENTINEL.unlink(missing_ok=True)
    except Exception:
        pass
    return True
