#!/usr/bin/env python3
"""Integrity manifest for the agent's own instruction surface.

WHY (2026-08-15 security review): the files that steer this agent -- skills,
sub-agent definitions, PreToolUse hooks, autonomy levels, allowlists -- are
executable instruction text, and the agent WRITES SOME OF THEM ITSELF. The
PreCompact hook auto-generates skills into the global ~/.claude/skills tree,
where every future session then loads them as instructions rather than data.
Nothing was watching that tree. A skill written from poisoned input would
propagate silently to every later session; that is the self-replication path in
this system, and it needs no virus.

This tool does not prevent a change. It makes one impossible to miss: a hash
baseline you accept once, and a check that names exactly what moved since.

Usage:
    python3 scripts/integrity-manifest.py --init      # first baseline
    python3 scripts/integrity-manifest.py --check     # what changed since?
    python3 scripts/integrity-manifest.py --accept    # re-baseline after review

--check exits 0 when clean, 1 when something changed, so a scheduled job can
branch on it. Output is plain text meant to be read in a Telegram message.
"""

import argparse
import hashlib
import json
import os
import sys

HOME = os.path.expanduser("~")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(REPO_ROOT, "store", "integrity-manifest.json")

# Directories never worth hashing, whatever the entry.
ALWAYS_SKIP = (".git", "__pycache__", "node_modules")

# Each entry: (label, base directory, relative path or directory, suffix filter)
# with an optional 5th element: extra directory names to skip while walking.
# Kept explicit rather than globbing $HOME: a manifest that quietly grows to
# cover unrelated files gets ignored, and an ignored manifest is worse than none.
WATCHED = [
    ("skill", HOME, ".claude/skills", (".md", ".py", ".sh", ".mjs", ".js")),
    ("subagent", HOME, ".claude/agents", (".md",)),
    ("scheduled-task", HOME, ".claude/scheduled-tasks", (".md", ".json")),
    ("hook", REPO_ROOT, "scripts/hooks", (".mjs", ".py", ".sh")),
    ("guard", REPO_ROOT, "scripts/liveness-watchdog.sh", None),
    ("guard", REPO_ROOT, "scripts/approve-once.sh", None),
    ("guard", REPO_ROOT, "scripts/integrity-manifest.py", None),
    ("policy", REPO_ROOT, "store/autonomy-config.json", None),
    ("policy", REPO_ROOT, "store/egress-allowlist.json", None),
    ("settings", HOME, ".claude/settings.json", None),
    # 2026-08-27: the gap this manifest was built to close, but did not cover.
    # CLAUDE.md is the whole operating rulebook of the main agent and IS written
    # by the agent (the self-rename skill edits it); the per-agent files below are
    # the full instruction set of each sub-agent, and the main agent authored all
    # of them. Both load as instructions at every start, exactly like a skill.
    # Measured: editing CLAUDE.md left --check reporting "unchanged".
    ("instructions", REPO_ROOT, "CLAUDE.md", None),
    # Walks agents/<name>/: CLAUDE.md, SOUL.md, agent-config.json, .mcp.json,
    # .claude/settings.json and .claude/agents/*.md. memory/ and scripts/ are
    # skipped on purpose: those are the agent's own notes and tools, they change
    # with every ordinary work round, and a manifest that cries daily gets muted.
    ("instructions", REPO_ROOT, "agents", (".md", ".json"), ("memory", "scripts")),
]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect():
    """Map of 'label:display-path' -> sha256 for every watched file that exists."""
    out = {}
    for entry in WATCHED:
        label, base, rel, suffixes = entry[:4]
        extra_skip = entry[4] if len(entry) > 4 else ()
        full = os.path.join(base, rel)
        if os.path.isfile(full):
            out[f"{label}:{rel}"] = sha(full)
        elif os.path.isdir(full):
            for root, dirs, files in os.walk(full):
                dirs[:] = [d for d in dirs if d not in ALWAYS_SKIP and d not in extra_skip]
                for name in sorted(files):
                    if suffixes and not name.endswith(suffixes):
                        continue
                    p = os.path.join(root, name)
                    out[f"{label}:{os.path.relpath(p, base)}"] = sha(p)
    return out


def load_manifest():
    try:
        with open(MANIFEST) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_manifest(entries):
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w") as f:
        json.dump({"files": entries}, f, indent=1, sort_keys=True)


def diff(old, new):
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    return added, removed, changed


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--init", action="store_true", help="write the first baseline")
    g.add_argument("--check", action="store_true", help="report changes since the baseline")
    g.add_argument("--accept", action="store_true", help="re-baseline after reviewing a change")
    args = ap.parse_args()

    current = collect()

    if args.init or args.accept:
        existed = load_manifest() is not None
        if args.init and existed:
            print("Már van alapállapot. Felülíráshoz: --accept")
            return 1
        save_manifest(current)
        print(f"Alapállapot rögzítve: {len(current)} fájl.")
        return 0

    baseline = load_manifest()
    if baseline is None:
        print("Nincs alapállapot. Először: python3 scripts/integrity-manifest.py --init")
        return 1

    added, removed, changed = diff(baseline["files"], current)
    if not (added or removed or changed):
        print(f"Az utasítás-felület változatlan ({len(current)} fájl).")
        return 0

    # Changed and removed come first: a modified guard or an edited skill is the
    # interesting case. A new skill is expected -- this agent writes skills.
    print(f"VÁLTOZÁS az utasítás-felületen ({len(current)} fájl figyelve):")
    for k in changed:
        print(f"  MÓDOSULT   {k}")
    for k in removed:
        print(f"  ELTŰNT     {k}")
    for k in added:
        print(f"  ÚJ         {k}")
    print("\nHa rendben van: python3 scripts/integrity-manifest.py --accept")
    return 1


if __name__ == "__main__":
    sys.exit(main())
