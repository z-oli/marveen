#!/usr/bin/env bash
# skill-promote.sh -- OWNER-SIDE review gate for agent-written skills.
#
# The agent writes new skills into ~/.claude/skills-pending/ instead of the live
# ~/.claude/skills/ tree. Pending skills are NOT loaded by any session, so a
# skill distilled from poisoned input cannot start steering future sessions on
# its own. You read it, then promote or drop it.
#
# Usage:
#   bash scripts/skill-promote.sh                 # list what is waiting
#   bash scripts/skill-promote.sh <name>          # show it in full
#   bash scripts/skill-promote.sh <name> --ok     # move it into the live tree
#   bash scripts/skill-promote.sh <name> --drop   # delete it

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PENDING="$HOME/.claude/skills-pending"
LIVE="$HOME/.claude/skills"

mkdir -p "$PENDING"

NAME="${1:-}"
ACTION="${2:-}"

if [[ -z "$NAME" ]]; then
  shopt -s nullglob
  found=0
  for d in "$PENDING"/*/; do
    found=1
    n="$(basename "$d")"
    desc="$(grep -m1 '^description:' "$d/SKILL.md" 2>/dev/null | cut -d: -f2- | sed 's/^ *//')"
    printf '%-38s %s\n' "$n" "${desc:0:80}"
  done
  (( found )) || echo "Nincs várakozó skill."
  exit 0
fi

SRC="$PENDING/$NAME"
[[ -d "$SRC" ]] || { echo "Nincs ilyen várakozó skill: $NAME" >&2; exit 1; }

case "$ACTION" in
  --ok)
    # Never silently overwrite a live skill: a "patch" that replaces a working
    # skill wholesale is exactly the change worth looking at by hand.
    if [[ -e "$LIVE/$NAME" ]]; then
      echo "Már van élő skill ezzel a névvel: $LIVE/$NAME" >&2
      echo "Nézd meg a különbséget, és ha kell, kézzel írd felül:" >&2
      echo "  diff -u \"$LIVE/$NAME/SKILL.md\" \"$SRC/SKILL.md\"" >&2
      exit 1
    fi
    mv "$SRC" "$LIVE/$NAME"
    echo "Élesítve: $LIVE/$NAME"
    bash "$REPO_ROOT/scripts/skill-index.sh" >/dev/null 2>&1 || true
    python3 "$REPO_ROOT/scripts/integrity-manifest.py" --accept >/dev/null 2>&1 || true
    echo "Index és integritás-alapállapot frissítve."
    ;;
  --drop)
    rm -rf "$SRC"
    echo "Eldobva: $NAME"
    ;;
  *)
    echo "=== $NAME ==="
    cat "$SRC/SKILL.md"
    echo
    echo "Élesítés: bash scripts/skill-promote.sh $NAME --ok"
    echo "Eldobás:  bash scripts/skill-promote.sh $NAME --drop"
    ;;
esac
