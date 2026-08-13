#!/usr/bin/env python3
"""Extract durable facts from triaged claude.ai conversations with a local model.

Usage: python3 scripts/claude-archive-distill.py <export-dir> [min-ertek] [limit]

Reads triazs-normalizalt.json, processes conversations at or above <min-ertek>
(default 2), and appends candidate facts to <export-dir>/desztillatum.jsonl.
Resumable: conversations already in the output are skipped.

The output is a CANDIDATE list, not memory. A curation pass decides what is
actually written to the memory store.
"""
import json
import os
import re
import sys
import urllib.request

MODEL = os.environ.get("DISTILL_MODEL", "qwen2.5:14b")
OLLAMA = "http://127.0.0.1:11434/api/generate"
PLACEHOLDER = "This block is not supported on your current device yet."
MAX_CHARS = 8000

PROMPT = """Egy beszelgetes atiratat kapod Zoli es egy AI asszisztens kozott.
Szedd ki belole azokat a tenyeket, amiket egy szemelyes asszisztensnek HOSSZU TAVON
tudnia kell Zoli-rol vagy a munkajarol.

BEMEGY:
- tartos teny (ceg, szemely, eszkoz, rendszer, azonosito, szabaly)
- dontes az indokaval
- preferencia vagy munkamodszer
- ismetlodo minta vagy tanulsag

NEM MEGY BE (ezek a leggyakoribb hibak):
- esemeny, ami akkor tortent: "Zoli feltoltott egy fajlt", "Zoli megkerdezte", "elkeszult a tabla"
- hatarido vagy datum, ami azota lejart
- egyszeri kerdes es valasz, amit akkor megoldottatok
- kodreszlet, parancs, hibauzenet
- altalanos tudas, ami nem szemelyesen Zoli-rol szol (pl. hogyan mukodik a Bitcoin,
  mit szoktak a tozsdek korlatozni) -- ezt barmely lexikonban meg lehet nezni
- statusz, ami azota elavulhatott (melyik platformra lep at eppen, mi a nyitott ugy)

DONTO TESZT minden tenyre: igaz lesz-e meg egy ev mulva is? Ha nem biztos, HAGYD KI.

Ha nincs benne semmi tartos, ures listat adj vissza. Ez a leggyakoribb helyes valasz,
a beszelgetesek tobbsegeben tenyleg nincs semmi maradando. Ne eroltess ki tenyeket.

Minden teny EGY tomor magyar mondat legyen, onmagaban is ertheto, konkret nevekkel
es szamokkal, helyes magyar nyelvtannal. Ne hivatkozz a beszelgetesre.

Valaszolj CSAK JSON-nal:
{"tenyek": [{"tema": "2-4 szo", "teny": "egy mondat", "tier": "warm"}]}
tier KOTELEZO, pontosan az egyik: "warm" = stabil teny vagy preferencia,
"cold" = tanulsag vagy mar lezart dontes. Legfeljebb 3 teny, es inkabb kevesebb.

Cim: %(cim)s
Datum: %(datum)s
Kategoria: %(kategoria)s

Atirat:
%(szoveg)s"""


def transcript(conv):
    parts = []
    for msg in conv.get("chat_messages") or []:
        text = (msg.get("text") or "").replace(PLACEHOLDER, "").strip()
        if not text:
            continue
        who = "Zoli" if msg.get("sender") == "human" else "AI"
        parts.append(f"{who}: {text}")
    joined = "\n\n".join(parts)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined[:MAX_CHARS]


def ask(payload):
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps({"model": MODEL, "prompt": payload, "stream": False,
                         "format": "json", "options": {"temperature": 0}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(json.load(resp)["response"])


def main():
    base = sys.argv[1]
    min_value = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    triage = {r["uuid"]: r for r in json.load(open(os.path.join(base, "triazs-normalizalt.json")))}
    conversations = {c["uuid"]: c for c in json.load(open(os.path.join(base, "raw", "conversations.json")))}
    out_path = os.path.join(base, "desztillatum.jsonl")

    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                done.add(json.loads(line)["uuid"])
            except Exception:
                pass

    todo = [u for u, r in triage.items()
            if r.get("ertek", 0) >= min_value and u not in done and u in conversations]
    todo.sort(key=lambda u: (-triage[u]["ertek"], triage[u]["datum"]))
    if limit:
        todo = todo[:limit]
    print(f"feldolgozando: {len(todo)} (kesz: {len(done)}, kuszob: {min_value})", flush=True)

    with open(out_path, "a") as out:
        for index, uuid in enumerate(todo, 1):
            conv, meta = conversations[uuid], triage[uuid]
            text = transcript(conv)
            if len(text) < 200:
                facts = []
            else:
                try:
                    result = ask(PROMPT % {"cim": meta["cim"], "datum": meta["datum"],
                                           "kategoria": meta["kategoria"], "szoveg": text})
                    facts = result.get("tenyek") or []
                    if not isinstance(facts, list):
                        facts = []
                except Exception as exc:
                    facts = [{"tema": "HIBA", "teny": str(exc)[:120], "tier": "hiba"}]
            out.write(json.dumps({"uuid": uuid, "cim": meta["cim"], "datum": meta["datum"],
                                  "kategoria": meta["kategoria"], "ertek": meta["ertek"],
                                  "tenyek": facts}, ensure_ascii=False) + "\n")
            out.flush()
            if index % 10 == 0 or index == len(todo):
                print(f"  {index}/{len(todo)}", flush=True)


if __name__ == "__main__":
    main()
