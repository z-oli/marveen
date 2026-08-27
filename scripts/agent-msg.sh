#!/usr/bin/env bash
# agent-msg.sh -- reliable inter-agent message send for the Marveen fleet.
#
# WHY: the common `curl -s ... >/dev/null && echo sent` pattern is DANGEROUS -- curl exits 0 even when
# the server REJECTED the request (401/400/5xx), producing a SILENT send failure: the recipient never
# gets the message and two agents can wait on each other forever. The /api/messages router itself is
# fine (HTTP 200 + a message id); the bug is that the SENDER never checks the result. This helper checks
# the HTTP status AND the returned message id, and RETRIES on failure. A message counts as sent only
# when an id came back.
#
# Usage:  bash scripts/agent-msg.sh <from> <to> "<content>"
#   content: plain text (quotes / newlines OK) -- the body is built with json.dumps (no quoting pitfalls).
#   large / multi-line content may come from STDIN when the 3rd arg is "-":
#     echo "<long text>" | bash scripts/agent-msg.sh <from> <to> -
# Output: success -> "OK id=<n>"; failure -> "FAIL <reason>" + a line in store/agent-msg-failures.log, exit 1.
# Env: MARVEEN_WEB_PORT (default 3420).
set -uo pipefail

# base dir = the parent of this script's dir (scripts/..), so it works from any CWD / any install
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${MARVEEN_WEB_PORT:-3420}"
TOKEN_FILE="$BASE/store/.dashboard-token"
URL="http://localhost:${PORT}/api/messages"
LOG="$BASE/store/agent-msg-failures.log"

FROM="${1:?from required}"; TO="${2:?to required}"; C="${3:?content required (or - for STDIN)}"
# A TARTALOM CSAK STDIN-ROL JOHET (2026-08-27). Az inline, idezett argumentum
# alakot SZANDEKOSAN elutasitjuk -- nem azert, mert kenyelmetlen, hanem mert
# NEMÁN CSONKIT. Aznap ketszer fordult elo: egy visszaperjel harom kapcsolo-nevet
# tuntetett el egy uzenetbol, egy idezojel pedig a szoveg felet vagta le. A shell
# a tartalmat MAR CSONKAN adta at, a szkript hibatlanul elkuldte, a szerver
# hibatlanul tarolta, es az eredmeny "OK id=<n>" lett. A kuldes sikerult, a
# TARTALOM volt hianyos -- es ez csak akkor derult ki, amikor a cimzett szolt.
#
# EZERT NEM DETEKTALJUK, HANEM MEGSZUNTETJUK. Stdin-rol a szkript a teljes
# folyamot olvassa; a tartalmon nincs shell-ertelmezes, tehat nincs mit elvagni.
# Ugyanaz az elv, mint a fleet tobbi mai javitasanal: a rossz allapotot szuntesd
# meg, ne a felismereset epitsd.
if [ "$C" != "-" ]; then
  cat >&2 <<'SUGO'
FAIL: a tartalmat STDIN-rol kell adni, nem argumentumkent.

  HELYTELEN:  bash scripts/agent-msg.sh <from> <to> "a szoveg"
  HELYES:     bash scripts/agent-msg.sh <from> <to> - < uzenet.txt
              printf '%s\n' "a szoveg" | bash scripts/agent-msg.sh <from> <to> -

MIERT: az idezett argumentum a shellben NEMÁN csonkulhat (idezojel, visszaperjel,
dollar), es a kuldes ettol meg "OK"-t ad. Stdin-nel ez nem fordulhat elo.
Hosszabb uzenetnel amugy is fajlt erdemes hasznalni: a fajl merete (wc -c) es a
kimenetben megjeleno bajt=<n> osszevetheto.
SUGO
  exit 1
fi
C="$(cat)"
[ -r "$TOKEN_FILE" ] || { echo "FAIL: no token file at $TOKEN_FILE"; exit 1; }
TOKEN="$(cat "$TOKEN_FILE")"

BODY="$(FROM="$FROM" TO="$TO" C="$C" python3 -c 'import json,os; print(json.dumps({"from":os.environ["FROM"],"to":os.environ["TO"],"content":os.environ["C"]}))')"

attempt=0; max=3; CODE=""; ID=""
while [ "$attempt" -lt "$max" ]; do
  attempt=$((attempt+1))
  RESP="$(curl -s -X POST "$URL" -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d "$BODY" -w $'\n%{http_code}' 2>/dev/null || true)"
  CODE="$(printf '%s' "$RESP" | tail -n1)"
  JSON="$(printf '%s' "$RESP" | sed '$d')"
  ID="$(printf '%s' "$JSON" | python3 -c 'import sys,json
try:
  d=json.load(sys.stdin); print(d.get("id","") if isinstance(d,dict) else "")
except Exception:
  print("")' 2>/dev/null)"
  if { [ "$CODE" = "200" ] || [ "$CODE" = "201" ]; } && [ -n "$ID" ]; then
    # A hosszt is kiirjuk, hogy a HIVO ossze tudja vetni azzal, amit KULDENI AKART.
    # 2026-08-27: ketszer fordult elo, hogy a tartalom mar a HIVO shelljeben csonkult
    # (visszaperjel, majd idezojel egy inline, idezett argumentumban), es a kuldes
    # ettol meg "OK id=<n>"-t adott -- a kuldes sikerult, a TARTALOM volt hianyos.
    # FONTOS: egy szkripten BELULI visszaolvasas ezt NEM fogta volna meg, mert a
    # csonkitas mar a $C-be erkezes ELOTT megtortent; a szkript csonkat hasonlitott
    # volna csonkahoz. Ezert a helyes eljaras: a tartalom FAJLBOL menjen (`- < fajl`),
    # es a hivo vesse ossze ezt a szamot a fajl meretevel (`wc -c`).
    echo "OK id=$ID bajt=$(printf '%s' "$C" | wc -c | tr -d ' ')"; exit 0
  fi
  sleep 1
done
echo "FAIL from=$FROM to=$TO http=${CODE:-?} id='$ID' (after $max tries)"
printf '%s\tFAIL\tfrom=%s\tto=%s\thttp=%s\tresp=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$FROM" "$TO" "${CODE:-?}" "$(printf '%s' "${JSON:-}" | head -c 200)" >> "$LOG" 2>/dev/null || true
exit 1
