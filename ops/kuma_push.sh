#!/usr/bin/env bash
#
# kuma_push.sh — push an HONEST heartbeat to Uptime Kuma.
#
# Replaces:
#     * * * * * curl -fsS ".../api/push/TOKEN?status=up&msg=OK"
#
# That line reported `up` unconditionally, forever, as long as the box had
# outbound internet. It stayed green through a four-day total outage in which
# every camera was being kicked every 15 seconds and nothing was being counted.
# A monitor that cannot report failure is worse than no monitor: it actively
# tells you to look elsewhere.
#
# This checks what the box is actually FOR — ingesting streams and processing
# them — and reports down when that stops. Kuma raises the alert on missing or
# `down` beats, so a crashed box or a dead network still trips it.
#
# Install (crowdcounts2, user crontab, no sudo):
#     * * * * * /home/crowdcounts2/Documents/CrowdCount/crowdcount-counter/ops/kuma_push.sh
#
# Env:
#   KUMA_PUSH_URL   override the push endpoint
#   KUMA_MIN_PATHS  minimum ready ingest paths to call healthy (default 1)

set -uo pipefail

PUSH_URL="${KUMA_PUSH_URL:-https://status.upstreamcv.com/api/push/PEQ7vHxeoC}"
MIN_PATHS="${KUMA_MIN_PATHS:-1}"

CC_API="http://127.0.0.1:9997/v3/paths/list"    # crowdcount mediamtx (RTSP)
UP_API="http://127.0.0.1:19997/v3/paths/list"   # upstream mediamtx (SRT)

fails=()

ready_count() {
  curl -s -m 5 "$1" 2>/dev/null \
    | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print(sum(1 for i in d.get("items", []) if i.get("ready")))
except Exception:
    print(-1)' 2>/dev/null || echo -1
}

cc=$(ready_count "$CC_API")
up=$(ready_count "$UP_API")

# -1 means the API did not answer at all: mediamtx is down or wedged. That is
# distinct from "answered, zero streams" and worth saying differently.
[ "$cc" = "-1" ] && fails+=("crowdcount mediamtx API unreachable")
[ "$up" = "-1" ] && fails+=("upstream mediamtx API unreachable")

# Cameras publish to whichever leg they are configured for, and the fleet is
# mid-migration from RTSP to SRT — so health is the SUM being non-zero, not
# either one individually. Checking them separately would page every time a
# device legitimately switched transport.
total=0
[ "$cc" -gt 0 ] 2>/dev/null && total=$((total + cc))
[ "$up" -gt 0 ] 2>/dev/null && total=$((total + up))
if [ "$cc" != "-1" ] && [ "$up" != "-1" ] && [ "$total" -lt "$MIN_PATHS" ]; then
  fails+=("no cameras ingesting (rtsp=$cc srt=$up)")
fi

# The orchestrator can be alive with zero processors — that is precisely the
# 2026-08-04 failure, where /dev/shm exhaustion meant no processor could spawn
# while streams kept arriving. Only meaningful when RTSP streams exist; with
# the fleet on SRT, processors=0 is normal and must not alarm.
if [ "$cc" != "-1" ] && [ "$cc" -gt 0 ] 2>/dev/null; then
  procs=$(docker logs --since 5m crowdcount-prod 2>&1 \
            | grep -oE "processors=[0-9]+" | tail -1 | cut -d= -f2)
  if [ -n "${procs:-}" ] && [ "$procs" = "0" ]; then
    fails+=("$cc RTSP stream(s) ingesting but 0 processors")
  fi
fi

# The resource exhaustion that caused the outage, caught before it bites.
shm=$(docker exec crowdcount-prod df -h /dev/shm 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')
if [ -n "${shm:-}" ] && [ "$shm" -ge 80 ] 2>/dev/null; then
  fails+=("/dev/shm ${shm}% full (ENOSPC will stop all processing)")
fi

if [ "${#fails[@]}" -eq 0 ]; then
  msg="OK rtsp=$cc srt=$up"
  status="up"
else
  # Kuma truncates long messages; lead with the first failure.
  msg=$(printf '%s; ' "${fails[@]}"); msg="${msg%; }"
  status="down"
fi

curl -fsS --max-time 10 --get "$PUSH_URL" \
  --data-urlencode "status=$status" \
  --data-urlencode "msg=$msg" \
  --data-urlencode "ping=" >/dev/null 2>&1

# Exit non-zero on unhealthy so a human running it by hand sees the failure,
# and so cron surfaces it if the push itself is what is broken.
[ "$status" = "up" ] || { echo "UNHEALTHY: $msg" >&2; exit 1; }
