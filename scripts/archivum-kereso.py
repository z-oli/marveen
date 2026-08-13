#!/usr/bin/env python3
"""Search the semantic archive index.

Usage:
  store/rag-venv/bin/python scripts/archivum-kereso.py "kerdes" [-n 8] [-k kind] [--teljes]

Options:
  -n N        how many hits to return (default 8)
  -k KIND     restrict to one kind: beszelgetes, projekt, dokumentum, claude-memoria
  --teljes    print the whole chunk instead of a trimmed preview

Prints the hits ranked by cosine similarity, each with its source path so the
full context can be opened from the archive.
"""
import json
import os
import sqlite3
import struct
import sys
import urllib.request

import numpy as np

DB = os.environ.get(
    "ARCHIVE_DB",
    "/Users/zoli/marveen/store/archive/claude/2026-08-12/index.db",
)
OLLAMA = "http://127.0.0.1:11434/api/embed"
MODEL = "bge-m3"


def embed(text):
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps({"model": MODEL, "input": [text]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return np.array(json.load(resp)["embeddings"][0], dtype=np.float32)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    limit, kind, full, as_json = 8, None, False, False
    query = []
    i = 0
    while i < len(args):
        if args[i] == "-n":
            limit = int(args[i + 1]); i += 2
        elif args[i] == "-k":
            kind = args[i + 1]; i += 2
        elif args[i] == "--teljes":
            full = True; i += 1
        elif args[i] == "--json":
            as_json = True; i += 1
        else:
            query.append(args[i]); i += 1
    question = " ".join(query)

    db = sqlite3.connect(DB)
    sql = "SELECT kind, path, cim, datum, chunk_ix, text, vec FROM chunks"
    params = ()
    if kind:
        sql += " WHERE kind = ?"
        params = (kind,)
    rows = db.execute(sql, params).fetchall()
    if not rows:
        print("nincs indexelt chunk")
        return

    dim = len(rows[0][6]) // 4
    # bge-m3 already returns unit vectors, so only renormalise the rows that need it
    matrix = np.frombuffer(b"".join(r[6] for r in rows), dtype=np.float32).reshape(len(rows), dim)
    matrix = matrix.astype(np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    np.divide(matrix, norms, out=matrix, where=norms > 1e-9)

    vector = embed(question).astype(np.float64)
    norm = np.linalg.norm(vector)
    if norm > 1e-9:
        vector /= norm
    # Apple's Accelerate BLAS raises spurious FP flags here; the results are exact
    # (self-similarity comes out at 1.0 and every score is finite), so ignore them.
    with np.errstate(all="ignore"):
        scores = matrix @ vector
    order = np.argsort(-scores)[:limit]

    if as_json:
        hits = []
        for idx in order:
            kind_, path, cim, datum, chunk_ix, text, _ = rows[idx]
            hits.append({"score": round(float(scores[idx]), 4), "kind": kind_, "path": path,
                         "cim": cim, "datum": datum, "chunk_ix": chunk_ix,
                         "text": text if full else " ".join(text.split())[:600]})
        print(json.dumps({"query": question, "chunks_searched": len(rows), "hits": hits},
                         ensure_ascii=False))
        return

    print(f'"{question}"  --  {len(rows)} chunk atnezve\n')
    for rank, idx in enumerate(order, 1):
        kind_, path, cim, datum, chunk_ix, text, _ = rows[idx]
        head = f"{rank}. [{scores[idx]:.3f}] {cim}"
        if datum:
            head += f"  ({datum})"
        print(head)
        print(f"   {kind_} | {path} #{chunk_ix}")
        body = text if full else " ".join(text.split())[:400]
        for line in (body.splitlines() if full else [body]):
            print(f"   {line}")
        print()


if __name__ == "__main__":
    main()
