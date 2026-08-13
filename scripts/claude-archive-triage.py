#!/usr/bin/env python3
"""Classify archived claude.ai conversations with a local Ollama model.

Usage: python3 scripts/claude-archive-triage.py <export-dir> [limit]

Reads <export-dir>/raw/conversations.json, writes <export-dir>/triazs.jsonl
(one JSON object per conversation). Resumable: conversations already present in
the output file are skipped, so the script can be re-run after an interruption.
"""
import json
import os
import sys
import urllib.request

MODEL = os.environ.get("TRIAGE_MODEL", "qwen2.5:14b")
OLLAMA = "http://127.0.0.1:11434/api/generate"

PROMPT = """Te egy archivum-besorolo vagy. Egy beszelgetes metaadatait kapod meg.
Dontsd el, melyik kategoriaba tartozik es mennyire ertekes hosszu tavon.

Kategoriak:
- uzlet: nyelviskola, ajanlat, tender, ugyfel, penzugy, ceges adminisztracio, marketing
- trading: kripto, hatarido, SMC, kereskedesi eszkozok, piaci elemzes
- technikai: gepek, szerverek, kod, MCP, automatizacio, telepites, hibakereses
- magan: kerekpar, ora, egeszseg, haz, csalad, utazas
- zaj: egyszeri apro kerdes, felbeszakadt beszelgetes, semmi maradando

Ertek 0-tol 3-ig:
0 = zaj, semmi maradando
1 = alacsony, egyszeri megoldott feladat
2 = hasznos, visszakeresheto tudas vagy dontes
3 = kiemelt, tartos dontes, strategia, vagy sokszor hivatkozott anyag

Valaszolj CSAK JSON-nal: {"kategoria": "...", "ertek": 0, "indok": "max 12 szo"}

Cim: %(cim)s
Datum: %(datum)s
Uzenetek szama: %(uzenetek)s
Elso kerdes: %(elso)s
Kesobbi reszlet: %(kozep)s"""


def ask(payload):
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps({"model": MODEL, "prompt": payload, "stream": False,
                         "format": "json", "options": {"temperature": 0}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(json.load(resp)["response"])


def first_user_text(conv):
    for msg in conv.get("chat_messages") or []:
        if msg.get("sender") == "human" and (msg.get("text") or "").strip():
            return msg["text"].strip()[:700]
    return ""


def middle_text(conv):
    messages = [m for m in (conv.get("chat_messages") or [])
                if m.get("sender") == "human" and (m.get("text") or "").strip()]
    if len(messages) < 2:
        return ""
    return messages[len(messages) // 2]["text"].strip()[:400]


def main():
    base = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    conversations = json.load(open(os.path.join(base, "raw", "conversations.json")))
    out_path = os.path.join(base, "triazs.jsonl")

    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                done.add(json.loads(line)["uuid"])
            except Exception:
                pass

    todo = [c for c in conversations if c.get("uuid") not in done]
    if limit:
        todo = todo[:limit]
    print(f"feldolgozando: {len(todo)} (kesz: {len(done)})", flush=True)

    with open(out_path, "a") as out:
        for index, conv in enumerate(todo, 1):
            payload = PROMPT % {
                "cim": conv.get("name") or "(cim nelkul)",
                "datum": (conv.get("created_at") or "")[:10],
                "uzenetek": len(conv.get("chat_messages") or []),
                "elso": first_user_text(conv),
                "kozep": middle_text(conv),
            }
            try:
                verdict = ask(payload)
            except Exception as exc:
                verdict = {"kategoria": "hiba", "ertek": -1, "indok": str(exc)[:60]}
            row = {
                "uuid": conv.get("uuid"),
                "cim": conv.get("name") or "(cim nelkul)",
                "datum": (conv.get("created_at") or "")[:10],
                "uzenetek": len(conv.get("chat_messages") or []),
                "kategoria": str(verdict.get("kategoria", "?")).lower(),
                "ertek": verdict.get("ertek", -1),
                "indok": verdict.get("indok", ""),
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            if index % 10 == 0 or index == len(todo):
                print(f"  {index}/{len(todo)}", flush=True)


if __name__ == "__main__":
    main()
