#!/usr/bin/env bash
# liveness-watchdog.sh -- macOS dead-man's switch for the main agent.
#
# WHY THIS EXISTS (2026-08-15 incident): a morning power cut rebooted the Mac at
# 07:37. The LaunchAgents are configured correctly (RunAtLoad + KeepAlive), yet
# the agent stayed dark until 16:36 -- nine hours -- and nobody knew, because an
# agent that is not running cannot report that it is not running. The repo DOES
# ship a stability suite (channel-watchdog, keepalive probe, host-restart
# watchdog), but every one of those is wired through scripts/systemd/*.timer,
# which does not exist on macOS. So on this install nothing was watching.
#
# This script is the macOS counterpart. It runs from launchd every 10 minutes,
# completely outside the agent: it needs no tmux session, no dashboard and no
# model round-trip, and it talks to Telegram directly through the Bot API. If
# the agent is down, THIS is what still has a voice.
#
# Health = all three must hold:
#   1. the dashboard answers on its port
#   2. the <agent>-channels tmux session exists
#   3. a claude process is alive inside that session
#
# On the first unhealthy check it tries exactly ONE self-heal (launchctl
# kickstart of the channels job) and stays quiet -- a single restart that works
# is not worth a notification. If the NEXT check is still unhealthy, it alerts
# and then re-alerts at most hourly while the outage lasts. Recovery sends one
# "back up" message with the measured downtime.
#
# It also reports a host reboot once per boot (kern.boottime change), so a power
# cut is never mistaken for an application crash.
#
# Safe by construction: read-only except its own state files, every Telegram
# send is best-effort, and the script ALWAYS exits 0 -- a watchdog that fails
# would itself look like an incident.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STORE="$REPO_ROOT/store"
STATE="$STORE/.liveness-state"
BTIME_STATE="$STORE/.last-btime"
LOG="$STORE/liveness-watchdog.log"
TG_ENV="${TELEGRAM_ENV:-$HOME/.claude/channels/telegram/.env}"

mkdir -p "$STORE" 2>/dev/null || true

log() { echo "$(date '+%Y-%m-%dT%H:%M:%S%z') [liveness] $*" >>"$LOG" 2>/dev/null || true; }

# --- config -----------------------------------------------------------------
read_env() { grep -E "^$1=" "$2" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'\''\r'; }

AGENT_ID="$(read_env MAIN_AGENT_ID "$REPO_ROOT/.env")"
AGENT_ID="${AGENT_ID:-marveen}"
PORT="$(read_env WEB_PORT "$REPO_ROOT/.env")"
PORT="${PORT:-3420}"
# No hardcoded chat id: an install that alerts to someone else's chat is worse
# than an install that stays silent. Missing id -> log only.
CHAT_ID="${MARVEEN_ALERT_CHAT_ID:-$(read_env MARVEEN_ALERT_CHAT_ID "$REPO_ROOT/.env")}"
TOKEN="$(read_env TELEGRAM_BOT_TOKEN "$TG_ENV")"

notify() {
  local msg="$1"
  if [[ -z "$TOKEN" || -z "$CHAT_ID" ]]; then
    log "NOTIFY SKIPPED (missing token or MARVEEN_ALERT_CHAT_ID): $msg"
    return 0
  fi
  curl -s --max-time 15 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${msg}" >/dev/null 2>&1 \
    && log "notified: ${msg%%$'\n'*}" \
    || log "notify FAILED (best-effort): ${msg%%$'\n'*}"
}

now="$(date +%s)"

# --- host reboot notice (once per boot) -------------------------------------
# Output shape: `{ sec = 1786772227, usec = 302722 } Sat Aug 15 07:37:07 2026`.
# Anchor at the start: an unanchored `.*sec = ` greedily matches through to
# `usec = ` and captures the microseconds instead of the boot epoch.
btime="$(/usr/sbin/sysctl -n kern.boottime 2>/dev/null | sed -n 's/^{ *sec = \([0-9]*\).*/\1/p')"
if [[ -n "$btime" ]]; then
  prev_btime=""
  [[ -f "$BTIME_STATE" ]] && prev_btime="$(tr -dc '0-9' <"$BTIME_STATE" 2>/dev/null)"
  if [[ "$prev_btime" != "$btime" ]]; then
    echo "$btime" >"$BTIME_STATE" 2>/dev/null || true
    if [[ -n "$prev_btime" ]]; then
      boot_txt="$(date -r "$btime" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "@$btime")"
      up_min=$(( (now - btime) / 60 ))
      notify "A gép újraindult. Boot: ${boot_txt}. Azóta ${up_min} perc telt el. Ez host szintű restart, nem alkalmazás-hiba."
    else
      log "btime baseline initialised ($btime); no alert on first run"
    fi
  fi
fi

# --- health checks ----------------------------------------------------------
problems=()

curl -s -o /dev/null --max-time 8 "http://localhost:${PORT}/" \
  || problems+=("a dashboard nem válaszol a ${PORT} porton")

if tmux has-session -t "${AGENT_ID}-channels" 2>/dev/null; then
  if ! tmux list-panes -t "${AGENT_ID}-channels" -F '#{pane_pid}' 2>/dev/null \
       | while read -r p; do pgrep -P "$p" -f claude >/dev/null 2>&1 && echo ok; done \
       | grep -q ok; then
    # A pane with no claude descendant is a shell sitting where the agent should be.
    pgrep -f "claude" >/dev/null 2>&1 || problems+=("a channels session él, de nincs benne futó claude processz")
  fi
else
  problems+=("a ${AGENT_ID}-channels tmux session nem létezik")
fi

# --- state machine ----------------------------------------------------------
# State file: <status> <since_epoch> <last_alert_epoch> <healed:0|1>
status="ok"; since="$now"; last_alert="0"; healed="0"
if [[ -f "$STATE" ]]; then
  read -r s_status s_since s_alert s_healed <"$STATE" 2>/dev/null || true
  status="${s_status:-ok}"; since="${s_since:-$now}"
  last_alert="${s_alert:-0}"; healed="${s_healed:-0}"
fi

if [[ ${#problems[@]} -eq 0 ]]; then
  if [[ "$status" == "down" ]]; then
    down_min=$(( (now - since) / 60 ))
    if [[ "$last_alert" != "0" ]]; then
      notify "Újra elérhető vagyok. A kiesés ${down_min} perc volt."
    fi
    log "recovered after ${down_min}m"
  fi
  echo "ok $now 0 0" >"$STATE" 2>/dev/null || true
  exit 0
fi

detail="$(printf '%s; ' "${problems[@]}")"
detail="${detail%; }"

if [[ "$status" != "down" ]]; then
  # First unhealthy check: try one self-heal, stay quiet, decide next round.
  log "unhealthy: $detail -- attempting one kickstart"
  launchctl kickstart -k "gui/$(id -u)/com.${AGENT_ID}.channels" >/dev/null 2>&1 \
    && log "kickstart issued" || log "kickstart failed"
  echo "down $now 0 1" >"$STATE" 2>/dev/null || true
  exit 0
fi

# Still down on a later check.
down_min=$(( (now - since) / 60 ))
if [[ "$last_alert" == "0" ]] || (( now - last_alert >= 3600 )); then
  notify "Nem futok. Amit a watchdog lát: ${detail}. A kiesés ${down_min} perce tart, az automatikus újraindítás nem segített. Kézi beavatkozás kell: cd ~/marveen && bash scripts/channels.sh"
  echo "down $since $now 1" >"$STATE" 2>/dev/null || true
else
  echo "down $since $last_alert 1" >"$STATE" 2>/dev/null || true
fi
log "still down (${down_min}m): $detail"
exit 0
