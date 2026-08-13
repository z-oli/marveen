#!/usr/bin/env python3
"""Build a semantic index over the normalized claude.ai archive.

Usage: store/rag-venv/bin/python scripts/claude-archive-index.py <export-dir>

Chunks md/, projektek/, claude-memoria/ and fajlok-szoveg/, embeds every chunk
with the local bge-m3 model through Ollama, and stores vectors in
<export-dir>/index.db (SQLite, one row per chunk).

Re-runnable: chunks whose (path, chunk_ix, hash) are already stored are skipped,
so a new export only costs the embedding of what actually changed.
"""
import hashlib
import json
import os
import re
import sqlite3
import struct
import sys
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434/api/embed"
MODEL = "bge-m3"
BATCH = 32
CHUNK = 1200
OVERLAP = 200

DETAILS = re.compile(r"<details>.*?</details>", re.S)
FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)

KINDS = {
    "md": "beszelgetes",
    "projektek": "projekt",
    "claude-memoria": "claude-memoria",
    "fajlok-szoveg": "dokumentum",
}


def schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS chunks (
      id INTEGER PRIMARY KEY,
      kind TEXT NOT NULL,
      path TEXT NOT NULL,
      cim TEXT,
      datum TEXT,
      chunk_ix INTEGER NOT NULL,
      hash TEXT NOT NULL,
      text TEXT NOT NULL,
      vec BLOB NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS chunks_uniq ON chunks(path, chunk_ix, hash);
    CREATE INDEX IF NOT EXISTS chunks_kind ON chunks(kind);
    """)


def meta_of(path, text, kind):
    """Title and date: markdown frontmatter first, then filename conventions."""
    cim = os.path.basename(path)
    datum = ""
    match = FRONT.match(text)
    if match:
        for line in match.group(1).splitlines():
            if line.startswith("cim:"):
                cim = line[4:].strip().strip('"')
            elif line.startswith("letrehozva:"):
                datum = line[11:].strip()[:10]
    if not datum:
        stamp = re.match(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
        if stamp:
            datum = stamp.group(1)
    if kind == "projekt":
        cim = f"{os.path.basename(os.path.dirname(path))} / {cim}"
    return cim, datum


def split(text):
    """Paragraph-aware fixed-size chunks with overlap."""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= CHUNK:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = min(start + CHUNK, len(text))
        if end < len(text):
            brk = text.rfind("\n\n", start + CHUNK // 2, end)
            if brk == -1:
                brk = text.rfind(". ", start + CHUNK // 2, end)
            if brk != -1:
                end = brk + 1
        piece = text[start:end].strip()
        if len(piece) > 60:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return out


def embed(texts):
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps({"model": MODEL, "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.load(resp)["embeddings"]


def main():
    base = sys.argv[1]
    db = sqlite3.connect(os.path.join(base, "index.db"))
    schema(db)
    known = {(p, i, h) for p, i, h in db.execute("SELECT path, chunk_ix, hash FROM chunks")}

    pending = []
    for sub, kind in KINDS.items():
        root_dir = os.path.join(base, sub)
        if not os.path.isdir(root_dir):
            continue
        for root, _, files in os.walk(root_dir):
            for name in sorted(files):
                if not name.endswith((".md", ".txt")):
                    continue
                path = os.path.join(root, name)
                text = open(path, errors="replace").read()
                if kind == "beszelgetes":
                    text = DETAILS.sub("", text)
                cim, datum = meta_of(path, text, kind)
                rel = os.path.relpath(path, base)
                for ix, piece in enumerate(split(text)):
                    digest = hashlib.sha1(piece.encode()).hexdigest()[:16]
                    if (rel, ix, digest) in known:
                        continue
                    pending.append((kind, rel, cim, datum, ix, digest, piece))

    print(f"uj chunk: {len(pending)} (mar indexelt: {len(known)})", flush=True)
    started = time.time()
    for offset in range(0, len(pending), BATCH):
        group = pending[offset:offset + BATCH]
        vectors = embed([row[6] for row in group])
        db.executemany(
            "INSERT OR IGNORE INTO chunks(kind,path,cim,datum,chunk_ix,hash,text,vec)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [(k, p, c, d, i, h, t, struct.pack(f"{len(v)}f", *v))
             for (k, p, c, d, i, h, t), v in zip(group, vectors)],
        )
        db.commit()
        done = offset + len(group)
        if offset % (BATCH * 20) == 0 or done == len(pending):
            rate = done / max(time.time() - started, 0.01)
            print(f"  {done}/{len(pending)}  ({rate:.0f} chunk/s)", flush=True)

    total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print("\nindex kesz, osszes chunk:", total)
    for kind, count in db.execute("SELECT kind, COUNT(*) FROM chunks GROUP BY kind ORDER BY 2 DESC"):
        print(f"  {kind}: {count}")
    db.close()


if __name__ == "__main__":
    main()
