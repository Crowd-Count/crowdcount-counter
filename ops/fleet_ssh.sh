#!/usr/bin/env bash
#
# fleet_ssh.sh — out-of-band fleet operations over Tailscale SSH.
#
# RUNS ON AN OPERATOR MACHINE. Never invoked by any unit on a Pi.
#
# Why this exists
# ---------------
# The updater cannot repair a broken updater. L3611 froze on 34ef9c3, which
# predates ensure_root_ssh_config() (added in 5598f37) — the self-heal for its
# own failure shipped in an update it could not fetch. Any fix delivered via
# the update path has that same bootstrap deadlock.
#
# Tailscale SSH survives both observed failure modes: it needs no DNS (tailnet
# IPs) and no updater. That makes it the only reliable repair channel, so the
# repair tooling lives here rather than on the device.
#
# Commands
#   list                 show every reachable counter and its health signals
#   immunize-dns [HOST…] stop Tailscale from managing /etc/resolv.conf
#   reconcile    [HOST…] repair drift on whatever is online; safe for cron
#   unwedge      HOST…   full recovery for a device frozen on old firmware
#
# With no HOST arguments, commands target every online counter.
# immunize-dns and unwedge confirm before acting (FLEET_ASSUME_YES=1 skips).
#
# Most of the fleet is intermittent. A one-shot sweep only reaches whatever is
# up at that instant, so `reconcile` is the one that matters long-term: run it
# on a timer and any device that reappears is converged within one interval,
# including devices too old to carry the firmware-side self-heal.
#
#   */15 * * * *  FLEET_QUIET=1 /path/to/fleet_ssh.sh reconcile
#
# Exit: 0 clean or repaired, 2 something needs a human.

set -uo pipefail

SSH_USER="${FLEET_SSH_USER:-counter}"
SSH_OPTS=(-o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no)
REPO_DIR="/home/counter/crowdcount-counter"

# Device IDs are one letter + four digits (e.g. c4804). Match on the tailnet
# name (first label of DNSName), NOT .HostName: HostName is the OS hostname and
# drifts. C4804 still reports the factory hostname `crowdcount-counter`, so a
# HostName-based filter silently skips it while also matching a stale node of
# that same name. DNSName is assigned by the control plane and is the identity
# `ssh counter@<host>` actually resolves.
HOST_RE='^[a-z][0-9]{4}$'

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_off=$'\033[0m'
ok()   { printf '  %sOK%s   %s\n'   "$c_grn" "$c_off" "$*"; }
warn() { printf '  %sWARN%s %s\n'   "$c_yel" "$c_off" "$*"; }
fail() { printf '  %sFAIL%s %s\n'   "$c_red" "$c_off" "$*"; }

rsh() { ssh "${SSH_OPTS[@]}" "${SSH_USER}@$1" "$2" 2>/dev/null; }

online_hosts() {
  if command -v jq >/dev/null 2>&1; then
    tailscale status --json 2>/dev/null \
      | jq -r '.Peer[] | select(.Online == true) | (.DNSName | split(".")[0])' \
      | grep -E "$HOST_RE" | sort
  else
    # Fallback: column 2 of `tailscale status` is also the tailnet name.
    tailscale status 2>/dev/null | grep -v 'offline' | awk '{print $2}' \
      | grep -E "$HOST_RE" | sort
  fi
}

resolve_hosts() {
  if [ "$#" -gt 0 ]; then printf '%s\n' "$@"; else online_hosts; fi
}

# Interactive by default. FLEET_ASSUME_YES=1 skips the prompt for scripted runs
# and for shells with no controlling tty — without it, reading /dev/tty from a
# pipeline fails and the operation silently aborts.
confirm() {
  printf '\n%s\n' "$1"
  if [ "${FLEET_ASSUME_YES:-}" = "1" ]; then echo "FLEET_ASSUME_YES=1 — proceeding"; return 0; fi
  [ -r /dev/tty ] || { fail "no tty; re-run with FLEET_ASSUME_YES=1"; return 1; }
  printf 'Proceed? [y/N] '
  read -r reply </dev/tty
  [ "$reply" = "y" ] || [ "$reply" = "Y" ]
}

# ---------------------------------------------------------------------------
# list — read-only survey
# ---------------------------------------------------------------------------
# The commit devices SHOULD be on. Resolved from the remote, because the
# obvious local answers are both wrong in practice:
#   - your local HEAD may be a branch, or stale
#   - the commit you merged is NOT what devices report. GitHub creates a MERGE
#     commit, and `git reset --hard FETCH_HEAD` lands devices on that. Merging
#     f53b2d6 put the fleet on bbe9712, which CONTAINS it — comparing against
#     the branch commit makes a fully-updated fleet look like it never updated.
expected_head() {
  if [ -n "${FLEET_EXPECTED_HEAD:-}" ]; then echo "${FLEET_EXPECTED_HEAD:0:7}"; return; fi
  local branch="${FLEET_BRANCH:-main}" sha=""
  sha=$(git -C "$(dirname "$0")/.." ls-remote origin "$branch" 2>/dev/null | awk '{print $1}')
  [ -z "$sha" ] && sha=$(gh api "repos/Crowd-Count/crowdcount-counter/commits/$branch" --jq .sha 2>/dev/null)
  echo "${sha:0:7}"
}

cmd_list() {
  local want
  want=$(expected_head)
  if [ -n "$want" ]; then
    echo "expected HEAD (origin/${FLEET_BRANCH:-main}): $want"
  else
    warn "could not resolve expected HEAD; UPD? column will show '?'"
  fi
  printf '%-8s %-9s %-5s %-9s %-7s %-6s %s\n' HOST HEAD UPD? CorpDNS DNS SVC FETCH_ERRS
  for h in $(resolve_hosts "$@"); do
    out=$(rsh "$h" '
      H=$(cd '"$REPO_DIR"' 2>/dev/null && git log --format=%h -1 2>/dev/null || echo "?")
      C=$(tailscale debug prefs 2>/dev/null | grep -oE "\"CorpDNS\": (true|false)" | grep -oE "true|false"); [ -z "$C" ] && C="?"
      D=$(getent hosts api.crowdcount.tech >/dev/null 2>&1 && echo ok || echo FAIL)
      U=$(systemctl is-active crowdcount-updater 2>/dev/null)
      E=$(journalctl -u crowdcount-updater --no-pager -n 400 2>/dev/null | grep -c "git fetch failed")
      echo "$H|$C|$D|$U|$E"')
    if [ -z "$out" ]; then printf '%-8s %s\n' "$h" "(unreachable)"; continue; fi
    IFS='|' read -r H C D U E <<<"$out"
    if [ -z "$want" ]; then upd="?"
    elif [ "$H" = "$want" ]; then upd="yes"
    else upd="NO"
    fi
    printf '%-8s %-9s %-5s %-9s %-7s %-6s %s\n' "$h" "$H" "$upd" "$C" "$D" "$U" "$E"
  done
}

# ---------------------------------------------------------------------------
# immunize-dns — Cause B
# ---------------------------------------------------------------------------
# Tailscale MagicDNS rewrites /etc/resolv.conf to nameserver 100.100.100.100.
# When that resolver stops answering (P4516, 2026-08-08 20:24) every DNS lookup
# fails, so the device loses both cloud APIs while RTSP keeps working over the
# tunnel — alive, streaming, and invisible to the control plane.
#
# `tailscale set` and NOT `tailscale up`: `up` renegotiates the whole session
# and can drop the very SSH connection issuing the command, leaving the device
# half-configured and unreachable. `set --accept-dns=false` only hands
# /etc/resolv.conf back to DHCP; the tunnel is untouched.
cmd_immunize_dns() {
  hosts=$(resolve_hosts "$@")
  [ -z "$hosts" ] && { fail "no hosts"; return 1; }
  confirm "Disable Tailscale DNS management on:"$'\n'"$hosts" || { echo "aborted"; return 1; }

  for h in $hosts; do
    echo "── $h"
    before=$(rsh "$h" 'getent hosts api.crowdcount.tech >/dev/null 2>&1 && echo ok || echo FAIL')
    if ! rsh "$h" 'sudo tailscale set --accept-dns=false' >/dev/null; then
      fail "$h: could not set --accept-dns=false (sudo? unreachable?)"; continue
    fi

    # Releasing MagicDNS is NOT sufficient on its own. Observed on P4516:
    # tailscale handed /etc/resolv.conf back to NetworkManager, but NM did not
    # re-render it — the file was left as a bare "# Generated by NetworkManager"
    # header with ZERO nameserver lines, so DNS stayed broken. NM still held the
    # correct DHCP resolver the whole time; it just never rewrote the file.
    #
    # `nmcli general reload dns-rc` re-renders resolv.conf from NM's existing
    # state. Deliberately not `nmcli con up` / `dev reapply` / a NM restart:
    # those bounce wlan0, which drops Tailscale — and therefore drops the very
    # SSH session performing the repair, on a device we may not physically reach.
    rsh "$h" 'command -v nmcli >/dev/null && sudo nmcli general reload dns-rc' >/dev/null 2>&1
    sleep 3
    after=$(rsh "$h" 'getent hosts api.crowdcount.tech >/dev/null 2>&1 && echo ok || echo FAIL')
    nsvrs=$(rsh "$h" 'grep -c "^nameserver" /etc/resolv.conf 2>/dev/null || echo 0')
    if [ "$after" = "ok" ]; then
      [ "$before" = "FAIL" ] && ok "$h: DNS REPAIRED (was failing)" || ok "$h: DNS ok, MagicDNS disarmed"
    else
      # Worse than before is the only outcome that needs a human.
      [ "$before" = "ok" ] && fail "$h: DNS regressed — rollback: sudo tailscale set --accept-dns=true" \
                           || warn "$h: DNS still failing (cause is not Tailscale)"
    fi
    # An empty resolv.conf is the specific trap this command exists to close:
    # it looks "clean" but resolves nothing.
    [ "${nsvrs:-0}" = "0" ] && fail "$h: resolv.conf has NO nameserver — run: sudo nmcli general reload dns-rc"
  done
}

# ---------------------------------------------------------------------------
# unwedge — break the bootstrap deadlock
# ---------------------------------------------------------------------------
# For a device frozen on firmware that predates the self-heal. Order matters:
# DNS first, because a DNS-dead device cannot resolve github.com to fetch.
#
# Step 5 is a HARD GATE. Restarting the updater before the fetch is proven
# teaches you nothing — it just repeats the original silent failure.
#
# Run this only AFTER the firmware fix is on main, or the device pulls exactly
# the same fragile code it is already stuck on.
cmd_unwedge() {
  [ "$#" -gt 0 ] || { fail "unwedge needs explicit hosts"; return 1; }
  confirm "Unwedge (DNS + remote + root SSH + forced update): $*" || { echo "aborted"; return 1; }

  for h in "$@"; do
    echo "── $h"
    start_head=$(rsh "$h" "git -C $REPO_DIR rev-parse --short HEAD")
    echo "     starting HEAD: ${start_head:-?}"

    rsh "$h" 'sudo tailscale set --accept-dns=false' >/dev/null
    if [ "$(rsh "$h" 'getent hosts github.com >/dev/null 2>&1 && echo ok || echo FAIL')" != "ok" ]; then
      fail "$h: cannot resolve github.com even after DNS fix — stopping"; continue
    fi
    ok "$h: DNS resolves"

    # Give root the counter user's SSH world. -a preserves the 0600 perms ssh
    # demands; a mode mismatch makes ssh silently ignore the key.
    rsh "$h" '
      sudo install -m600 -o root -g root /home/counter/.ssh/config /root/.ssh/config 2>/dev/null
      for k in $(grep -i "^[[:space:]]*IdentityFile" /home/counter/.ssh/config 2>/dev/null | awk "{print \$2}"); do
        k=${k/#\~/\/home\/counter}
        [ -f "$k" ] && sudo cp -a "$k" /root/.ssh/ 2>/dev/null
      done
      sudo mkdir -p /root/.ssh
      sudo ssh-keyscan -t rsa,ed25519 github.com 2>/dev/null | sudo tee -a /root/.ssh/known_hosts >/dev/null
      sudo sort -u -o /root/.ssh/known_hosts /root/.ssh/known_hosts' >/dev/null
    ok "$h: root SSH materials installed"

    # HARD GATE — prove root can actually fetch before restarting anything.
    if ! rsh "$h" "sudo git -C $REPO_DIR fetch origin main" >/dev/null; then
      fail "$h: root git fetch STILL fails — not restarting updater. Inspect:"
      echo "       ssh ${SSH_USER}@$h 'sudo git -C $REPO_DIR fetch origin main'"
      echo "       ssh ${SSH_USER}@$h 'git -C $REPO_DIR remote -v'"
      continue
    fi
    ok "$h: root git fetch succeeds"

    rsh "$h" 'sudo systemctl restart crowdcount-updater' >/dev/null
    echo "     restarted updater; waiting 150s for the update cycle…"
    sleep 150
    new_head=$(rsh "$h" "git -C $REPO_DIR rev-parse --short HEAD")
    if [ -n "$new_head" ] && [ "$new_head" != "$start_head" ]; then
      ok "$h: HEAD $start_head -> $new_head"
    else
      warn "$h: HEAD still $new_head — updater may need another cycle; check:"
      echo "       ssh ${SSH_USER}@$h 'journalctl -u crowdcount-updater -n 40'"
    fi
  done
}

# ---------------------------------------------------------------------------
# reconcile — continuous drift repair (designed to run from cron)
# ---------------------------------------------------------------------------
# A one-shot sweep only reaches devices that happen to be online at that
# moment. Most of the fleet is intermittent: a counter can sit dark for weeks
# and reappear with CorpDNS=true and firmware old enough to predate every
# self-heal we ship. That device is broken from the instant it returns, and
# nothing on it will notice.
#
# So this is the reconciler: idempotent, safe to run every few minutes, and
# silent unless it actually changed something. Whatever is online right now
# gets converged; whatever is dark gets converged whenever it comes back.
#
# Together with the firmware's own boot-time ensure_dns_policy() this covers
# both populations — firmware handles devices new enough to have it, this
# handles the ones that are too old to, which is exactly the set that cannot
# fix themselves.
#
# Deliberately conservative: it repairs DNS (proven safe, non-disruptive) and
# only REPORTS other drift. Auto-rewriting a git remote or SSH config on a
# device we cannot physically reach is not something to do unattended.
cmd_reconcile() {
  local quiet="${FLEET_QUIET:-0}" changed=0 checked=0
  local problems=() remotes_seen=() heads_seen=() fetch_failed=()

  for h in $(resolve_hosts "$@"); do
    state=$(rsh "$h" '
      C=$(tailscale debug prefs 2>/dev/null | grep -oE "\"CorpDNS\": (true|false)" | grep -oE "true|false")
      N=$(grep -c "^nameserver" /etc/resolv.conf 2>/dev/null || echo 0)
      D=$(getent hosts api.crowdcount.tech >/dev/null 2>&1 && echo ok || echo FAIL)
      R=$(git -C '"$REPO_DIR"' remote get-url origin 2>/dev/null)
      H=$(git -C '"$REPO_DIR"' log --format=%h -1 2>/dev/null)
      # Whether the MOST RECENT update attempt failed — not whether any
      # attempt ever failed. A device that was broken and has since recovered
      # (p4516 after its DNS repair) must not keep alarming off stale journal
      # entries; that is precisely the cry-wolf noise that trained everyone to
      # ignore this system in the first place.
      E=$(journalctl -u crowdcount-updater --no-pager --since "-8h" 2>/dev/null \
            | grep -oE "git fetch failed|Already up to date|Updated to" | tail -1)
      echo "$C|$N|$D|$R|$H|$E"')
    [ -z "$state" ] && continue          # offline mid-run; next pass gets it
    checked=$((checked + 1))
    IFS='|' read -r corpdns nsvrs dns remote head ferrs <<<"$state"

    # --- repair: Tailscale DNS capture -------------------------------------
    if [ "$corpdns" = "true" ] || [ "${nsvrs:-0}" = "0" ] || [ "$dns" = "FAIL" ]; then
      echo "── $h: DNS drift (CorpDNS=$corpdns nameservers=$nsvrs resolve=$dns) — repairing"
      rsh "$h" 'sudo tailscale set --accept-dns=false' >/dev/null
      rsh "$h" 'command -v nmcli >/dev/null && sudo nmcli general reload dns-rc' >/dev/null 2>&1
      sleep 3
      if [ "$(rsh "$h" 'getent hosts api.crowdcount.tech >/dev/null 2>&1 && echo ok || echo FAIL')" = "ok" ]; then
        ok "$h: DNS repaired"; changed=$((changed + 1))
      else
        fail "$h: DNS STILL broken after repair — needs a human"
        problems+=("$h: DNS unresolvable")
      fi
    fi

    # --- report only: update-path drift ------------------------------------
    # Not auto-repaired. `unwedge` does that deliberately, one device at a
    # time, hard-gated on a proven fetch.
    #
    # Collected now, judged after the loop against the fleet's modal commit.
    # A log-only test gives stale flags: p4516's last logged attempt failed,
    # but that was before its DNS was repaired and it is in fact current.
    # "Behind everyone else" is the durable signal; "logged an error once" is
    # not, and shipping the noisy version would just retrain everyone to
    # ignore it.
    heads_seen+=("$h=${head:-?}")
    [ "$ferrs" = "git fetch failed" ] && fetch_failed+=("$h")
    # Deliberately NOT flagging the `github-crowdcount-counter-ro` alias: it
    # resolves to github.com via the counter user's ssh config and is correct
    # for this fleet. Nor the elkanbruha/ vs Crowd-Count/ org split — both
    # currently fetch fine, so per-device noise here would bury the one line
    # that matters. Org convergence is Stage 2's probe-gated job; surface it
    # once, fleet-wide, rather than eight times.
    remotes_seen+=("${remote##*:}")
  done

  # Modal commit = what the fleet has converged on. Needs a quorum, or a
  # 2-device sample makes whichever answered first look canonical.
  if [ "${#heads_seen[@]}" -ge 3 ]; then
    modal=$(printf '%s\n' "${heads_seen[@]}" | cut -d= -f2 | grep -v '^?$' \
              | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')
    for entry in "${heads_seen[@]}"; do
      hh=${entry%%=*}; hv=${entry##*=}
      [ "$hv" = "$modal" ] && continue
      [ "$hv" = "?" ] && continue
      # Only actionable when the updater is ALSO failing. A device on a
      # different commit with a healthy updater converges by itself within one
      # cycle — flagging it is noise.
      #
      # And the direction cannot be inferred from the modal commit anyway.
      # During a rollout the first devices to update are the minority, so an
      # earlier version of this reported them as "behind fleet" when they were
      # in fact ahead. Wrong AND useless: exactly the kind of alert that trains
      # people to ignore the channel.
      if printf '%s\n' "${fetch_failed[@]}" | grep -qx "$hh"; then
        problems+=("$hh: on $hv (fleet majority=$modal) AND updater cannot fetch — run: $0 unwedge $hh")
      fi
    done
  fi

  # One line, only when the fleet is genuinely inconsistent.
  uniq_remotes=$(printf '%s\n' "${remotes_seen[@]}" | grep -v '^$' | sort -u)
  if [ "$(printf '%s\n' "$uniq_remotes" | grep -c .)" -gt 1 ]; then
    problems+=("fleet git remotes are inconsistent: $(printf '%s ' $uniq_remotes)")
  fi

  if [ "${#problems[@]}" -gt 0 ]; then
    echo; echo "Needs attention:"
    printf '  - %s\n' "${problems[@]}"
  fi
  # Quiet on a clean pass so cron only mails when something happened.
  if [ "$changed" = "0" ] && [ "${#problems[@]}" -eq 0 ]; then
    [ "$quiet" = "1" ] || echo "reconcile: $checked device(s) checked, no drift"
    return 0
  fi
  echo; echo "reconcile: $checked checked, $changed repaired, ${#problems[@]} needing attention"
  [ "${#problems[@]}" -gt 0 ] && return 2 || return 0
}

case "${1:-}" in
  list)         shift; cmd_list "$@" ;;
  immunize-dns) shift; cmd_immunize_dns "$@" ;;
  reconcile)    shift; cmd_reconcile "$@" ;;
  unwedge)      shift; cmd_unwedge "$@" ;;
  *) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
