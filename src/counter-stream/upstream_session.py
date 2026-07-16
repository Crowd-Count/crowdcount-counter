#!/usr/bin/env python3
"""
Upstream session client for SRT dual-mode streaming.

Speaks the Upstream control-plane agent protocol (api.upstreamcv.com):
register agent + camera, mint a stream session, then keep it alive with
15s heartbeats while watching session state and expiry.

Deliberately stateless across restarts: agent registration upserts on
(account, name) and camera registration upserts on (agent, external_id),
so every boot simply re-registers with the same stable names. The
per-device token binds to this device's agent row on first register
(trust-on-first-use) — a stolen token cannot register as another device.

Sessions cannot be renewed: their TTL is fixed at mint (per-account
session_ttl_seconds, 7 days for the CrowdCount fleet account). Approaching
expiry surfaces as needs_rollover, and the streamer restarts the pipeline
onto a freshly minted session — a brief controlled restart once per TTL.
"""

import threading
import time
from datetime import datetime, timezone

FIRMWARE_USER_AGENT = "crowdcount-counter/1.0"

HEARTBEAT_INTERVAL_S = 15
# Consecutive heartbeat failures before check() calls the session unhealthy.
# Bounds the blind window when the Upstream API is partitioned: state polls
# fail too, so check() would otherwise keep passing on a stale "streaming"
# state and recovery would wait on server-side session reaping. Generous on
# purpose — heartbeats reach the API while the video reaches MediaMTX, so an
# API-only outage costs nothing while it lasts: SRT keeps flowing and counts
# keep landing. Tripping early would tear down a working stream and drop it to
# RTSP for the fallback cooldown; at 15s a beat this waits ~10min, and any
# successful heartbeat resets the counter.
MAX_HEARTBEAT_FAILURES = 40
# State polling: fast until MediaMTX confirms ingest, then relaxed.
INGEST_CONFIRM_POLL_S = 2
INGEST_CONFIRM_TIMEOUT_S = 45
STATE_POLL_INTERVAL_S = 60
# Re-mint the session (pipeline rollover) when this close to expires_at.
ROLLOVER_MARGIN_S = 120
HTTP_TIMEOUT_S = 10

# What this appliance actually captures. Must be in the account's
# allowed_stream_types — "srt" is the publish transport, never a source type.
CAMERA_SOURCE_TYPE = "webcam"
# Self-declared workload hint consumed by the package auto-apply rule.
WORKLOAD_CAPABILITY = "overhead-people-counter-line-crossing"

TERMINAL_STATES = ("ended", "expired", "failed")


class UpstreamError(Exception):
    """Any Upstream API failure the streamer should treat as an SRT failure."""

    def __init__(self, message, code=None, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_expires_at(value):
    """ISO-8601 UTC datetime -> unix timestamp (None on parse failure)."""
    if not value:
        return None
    try:
        if isinstance(value, str) and value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return None


class UpstreamSessionClient:
    """One SRT streaming session against the Upstream control plane.

    Lifecycle: start() -> (streamer launches ffmpeg at .srt_url) ->
    begin_keepalive() -> check() from the streamer's health loop ->
    stop() on any pipeline teardown. Instances are single-use; a rollover
    or retry constructs a fresh client.
    """

    def __init__(
        self,
        base_url,
        token,
        device_id,
        width,
        height,
        fps,
        bitrate_kbps=1200,
        agent_version=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.device_id = device_id
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate_kbps = bitrate_kbps
        self.agent_version = agent_version

        self.agent_id = None
        self.camera_id = None
        self.session_id = None
        self.srt_url = None
        self.expires_at = None  # unix timestamp
        self.session_state = None

        self._streaming_confirmed = False
        self._confirm_deadline = None
        self._fatal_error = None
        self._heartbeat_failures = 0
        self._stop_event = threading.Event()
        self._thread = None
        self._stopped = False

    # ── HTTP plumbing ────────────────────────────────────────────────────

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": FIRMWARE_USER_AGENT,
        }

    def _request(self, method, path, payload=None, params=None):
        """One API call. Returns parsed JSON; raises UpstreamError on non-2xx."""
        import requests

        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                json=payload,
                params=params,
                headers=self._headers(),
                timeout=HTTP_TIMEOUT_S,
            )
        except Exception as e:
            raise UpstreamError(f"{method} {path} failed: {e}") from e

        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except Exception as e:
                raise UpstreamError(f"{method} {path}: bad JSON response") from e

        # Error envelope: {"error": {"code": ..., "message": ...}}
        code = None
        message = f"HTTP {response.status_code}"
        try:
            err = response.json().get("error") or {}
            code = err.get("code")
            message = f"{message} {code}: {err.get('message', '')}"
        except Exception:
            pass
        raise UpstreamError(
            f"{method} {path}: {message}", code=code, status=response.status_code
        )

    # ── Session setup ────────────────────────────────────────────────────

    def start(self):
        """Register agent + camera and mint a session. Returns the SRT URL.

        Raises UpstreamError on any failure — the streamer treats that as
        an SRT failure and falls back to RTSP.
        """
        agent = self._request(
            "POST",
            "/v1/agents/register",
            {
                # Stable name: the TOFU token binding and the upsert key off it
                "name": self.device_id,
                "version": self.agent_version,
                "capabilities": {
                    "srt": True,
                    "crowdcount": True,
                    "workload": WORKLOAD_CAPABILITY,
                },
            },
        )
        self.agent_id = agent["agent"]["id"]
        print(f"✓ Upstream agent registered: {self.device_id}")

        camera = self._request(
            "POST",
            "/v1/cameras/register",
            {
                "agent_id": self.agent_id,
                "name": self.device_id,
                # external_id = CrowdCount device_id is the session->device
                # join the counting worker relies on
                "external_id": self.device_id,
                "source_type": CAMERA_SOURCE_TYPE,
                "default_width": self.width,
                "default_height": self.height,
                "default_fps": self.fps,
                "default_codec": "h264",
                "default_bitrate_kbps": self.bitrate_kbps,
                "default_latency_mode": "stable",
                "metadata": {"product": "crowdcount", "workload": WORKLOAD_CAPABILITY},
            },
        )
        self.camera_id = camera["id"]
        print(f"✓ Upstream camera registered (external_id={self.device_id})")

        self._mint_session(allow_recovery=True)
        return self.srt_url

    def _mint_session(self, allow_recovery=False):
        request_body = {
            "camera_id": self.camera_id,
            "requested": {
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
                "codec": "h264",
                "bitrate_kbps": self.bitrate_kbps,
                # "stable" = the 1500ms SRT latency window: counting tolerates
                # latency, so maximize loss tolerance on venue WiFi
                "latency_mode": "stable",
            },
        }
        try:
            sess = self._request("POST", "/v1/stream-sessions/start", request_body)
        except UpstreamError as e:
            # A power-cut can strand the previous session (webhook missed):
            # the camera row still says streaming. Stop the stragglers once
            # and retry.
            if allow_recovery and e.code == "camera_already_streaming":
                print("⚠ Camera has a stale session - stopping it and retrying...")
                self._stop_stale_sessions()
                sess = self._request("POST", "/v1/stream-sessions/start", request_body)
            else:
                raise

        session = sess["session"]
        self.session_id = session["id"]
        self.srt_url = sess["srt_url"]
        self.session_state = session.get("state")
        self.expires_at = _parse_expires_at(sess.get("expires_at"))
        if self.expires_at:
            hours = (self.expires_at - time.time()) / 3600
            print(f"✓ Upstream session minted (expires in {hours:.1f}h)")
        else:
            print("✓ Upstream session minted (no expiry parsed)")

    def _stop_stale_sessions(self):
        for state in ("streaming", "approved"):
            listing = self._request(
                "GET",
                "/v1/stream-sessions",
                params={"camera_id": self.camera_id, "state": state},
            )
            for session in listing.get("sessions", []):
                try:
                    self._request("POST", f"/v1/stream-sessions/{session['id']}/stop")
                    print(f"  ✓ Stopped stale session {session['id']}")
                except UpstreamError as e:
                    print(f"  ⚠ Could not stop stale session: {e}")

    @property
    def redacted_srt_url(self):
        """SRT URL with its credential-bearing query string removed."""
        if not self.srt_url:
            return "<no srt url>"
        return self.srt_url.split("?")[0] + "?<redacted>"

    # ── Keepalive (heartbeats + state watching) ──────────────────────────

    def begin_keepalive(self):
        """Start the background heartbeat/state thread. Call once ffmpeg is up."""
        self._confirm_deadline = time.time() + INGEST_CONFIRM_TIMEOUT_S
        self._thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="upstream-keepalive"
        )
        self._thread.start()

    def _keepalive_loop(self):
        last_heartbeat = 0.0
        last_state_poll = 0.0
        while not self._stop_event.is_set():
            now = time.time()

            if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                self._send_heartbeat()
                last_heartbeat = now

            # Fast state polls until ingest is confirmed, relaxed afterwards
            poll_interval = (
                INGEST_CONFIRM_POLL_S
                if not self._streaming_confirmed
                else STATE_POLL_INTERVAL_S
            )
            if now - last_state_poll >= poll_interval:
                self._poll_state()
                last_state_poll = now

            self._stop_event.wait(1)

    def _send_heartbeat(self):
        try:
            self._request(
                "POST",
                "/v1/heartbeats",
                payload={
                    "heartbeats": [
                        {
                            "camera_id": self.camera_id,
                            "session_id": self.session_id,
                            "status": "streaming",
                            "fps": float(self.fps),
                            "bitrate_kbps": self.bitrate_kbps,
                            "width": self.width,
                            "height": self.height,
                            "codec": "h264",
                            "agent_version": self.agent_version,
                            "reported_at": _utc_now_iso(),
                        }
                    ]
                },
                params={"agent_id": self.agent_id},
            )
            self._heartbeat_failures = 0
        except UpstreamError as e:
            if e.code in ("token_revoked", "token_expired"):
                # Unrecoverable without re-provisioning the device token
                self._fatal_error = str(e)
                return
            self._heartbeat_failures += 1
            print(f"⚠ Upstream heartbeat failed ({self._heartbeat_failures}): {e}")

    def _poll_state(self):
        try:
            session = self._request("GET", f"/v1/stream-sessions/{self.session_id}")
            self.session_state = session.get("state")
            if self.session_state == "streaming" and not self._streaming_confirmed:
                self._streaming_confirmed = True
                print("✓ Upstream ingest confirmed (session streaming)")
        except UpstreamError as e:
            if e.code in ("token_revoked", "token_expired"):
                self._fatal_error = str(e)
            else:
                # Transient - keep the last known state
                print(f"⚠ Upstream session poll failed: {e}")

    # ── Health view for the streamer ─────────────────────────────────────

    @property
    def needs_rollover(self):
        """True when the session is close enough to expiry to re-mint."""
        if self.expires_at is None:
            return False
        return (self.expires_at - time.time()) <= ROLLOVER_MARGIN_S

    @property
    def is_terminal(self):
        """True when this session can never become healthy again.

        Terminal session states and fatal token errors don't clear on their
        own — the only recovery is tearing down the pipeline and starting
        over (fresh session, or RTSP fallback while the cooldown holds).
        """
        return bool(self._fatal_error) or self.session_state in TERMINAL_STATES

    def check(self):
        """Health verdict for the streamer's periodic checks.

        Returns (ok, message). Not-ok is a critical failure that counts
        toward the streamer's restart threshold.
        """
        if self._fatal_error:
            return False, f"fatal: {self._fatal_error}"
        if self.session_state in TERMINAL_STATES:
            return False, f"session {self.session_state}"
        if self._heartbeat_failures >= MAX_HEARTBEAT_FAILURES:
            # Any successful heartbeat resets the counter, so this only trips
            # on a sustained outage — the session is unreachable, not stale.
            return False, (
                f"{self._heartbeat_failures} consecutive heartbeat failures "
                f"(~{self._heartbeat_failures * HEARTBEAT_INTERVAL_S}s)"
            )
        if self._streaming_confirmed:
            return True, "session streaming"
        # Not confirmed yet: fine within the confirmation window
        if self._confirm_deadline and time.time() <= self._confirm_deadline:
            return True, f"session {self.session_state} (awaiting ingest confirm)"
        return False, (
            f"ingest never confirmed (state={self.session_state} "
            f"after {INGEST_CONFIRM_TIMEOUT_S}s)"
        )

    # ── Teardown ─────────────────────────────────────────────────────────

    def stop(self):
        """Stop keepalive and end the session (idempotent, best-effort)."""
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        if self.session_id:
            try:
                self._request("POST", f"/v1/stream-sessions/{self.session_id}/stop")
                print("✓ Upstream session stopped")
            except Exception as e:
                # The server's runOnNotReady hook / sweeper will finish the job
                print(f"⚠ Upstream session stop failed (server will reap): {e}")
