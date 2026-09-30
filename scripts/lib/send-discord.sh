#!/bin/bash
# send-discord.sh -- honest Discord send primitive for the shell-level alerts.
#
# 2026-09-26: the owner moved his main channel from Telegram to Discord
# (warm memory 1080). The launchd watchdogs (liveness, ups) and notify.sh talk
# to the chat API directly, outside the channel plugin, so they need their own
# sender. Same contract as send-telegram.sh:
#
#   send_discord_message TOKEN CHANNEL_ID TEXT
#
#   returns 0  ONLY when curl exited 0, the API answered HTTP 200 AND the
#              response carries a message "id"
#   returns 1  on transport failure, API rejection, or misuse (empty args),
#              with the reason on stderr and the bot token redacted.
#
# Discord caps a message at 2000 characters; longer text is truncated with a
# visible marker instead of being rejected (an alert that arrives cut is better
# than one that does not arrive). Callers keep Telegram as the fallback when
# this returns 1.
#
# Bash 3.2 compatible. Source it, do not execute it.

send_discord_message() {
  if [ "$#" -lt 3 ]; then
    echo "send_discord_message: usage: send_discord_message TOKEN CHANNEL_ID TEXT" >&2
    return 1
  fi
  local token="$1" channel="$2" text="$3"
  if [ -z "$token" ] || [ -z "$channel" ] || [ -z "$text" ]; then
    echo "send_discord_message: empty token/channel/text -- refusing (nothing would be delivered)" >&2
    return 1
  fi

  local payload response curl_exit http_code body
  payload=$(DISCORD_TEXT="$text" python3 -c '
import json, os
t = os.environ["DISCORD_TEXT"]
if len(t) > 2000:
    t = t[:1980] + "\n[...levagva]"
print(json.dumps({"content": t, "allowed_mentions": {"parse": []}}))
') || { echo "send_discord_message: payload build failed" >&2; return 1; }

  response=$(curl -sS -m 15 -w $'\n%{http_code}' \
    -X POST "https://discord.com/api/v10/channels/${channel}/messages" \
    -H "Authorization: Bot ${token}" \
    -H "Content-Type: application/json" \
    --data-binary "$payload" 2>&1)
  curl_exit=$?
  response="${response//${token}/<token>}"

  if [ "$curl_exit" -ne 0 ]; then
    echo "send_discord_message: transport failure (curl exit ${curl_exit}): ${response}" >&2
    return 1
  fi
  http_code="${response##*$'\n'}"
  body="${response%$'\n'*}"
  if [ "$http_code" = "200" ] && printf '%s' "$body" | grep -q '"id"'; then
    return 0
  fi
  echo "send_discord_message: API rejected the call (HTTP ${http_code}): ${body:0:300}" >&2
  return 1
}
