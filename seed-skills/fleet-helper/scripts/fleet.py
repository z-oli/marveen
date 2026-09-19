#!/usr/bin/env python3
"""
ClaudeClaw fleet helper - shared, deterministic plumbing so agents don't burn
tokens hand-rolling curl/SQL/escaping in the model.

Covers: dashboard API auth (token always read from store/.dashboard-token, never
hardcoded), memory save/search, daily log, inter-agent messages, agent list,
kanban read helpers, and Telegram MarkdownV2 escaping.

Importable as a module or used from the CLI. See README.md for usage.

Config (no hardcoded paths or secrets):
  CLAW_DIR  - project root (the dir containing `store/`). If unset, the project
              root is auto-detected by walking up from the current directory
              until a `store/.dashboard-token` is found.
  CLAW_BASE - dashboard base url (default http://localhost:3420).
"""
import json
import os
import sys
import sqlite3
import urllib.request
import urllib.error


def project_dir():
    env = os.environ.get("CLAW_DIR")
    if env and os.path.isdir(os.path.join(env, "store")):
        return env
    d = os.getcwd()
    while True:
        if os.path.isfile(os.path.join(d, "store", ".dashboard-token")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    raise RuntimeError("project root not found (set CLAW_DIR to the dir containing store/)")


def base_url():
    return os.environ.get("CLAW_BASE", "http://localhost:3420").rstrip("/")


def token():
    with open(os.path.join(project_dir(), "store", ".dashboard-token")) as f:
        return f.read().strip()


def db_path():
    return os.path.join(project_dir(), "store", "claudeclaw.db")


def api(method, path, payload=None, timeout=20, want_headers=False):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base_url() + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token())
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            headers = dict(r.headers.items())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"API {method} {path} -> {e.code}: {e.read().decode()[:200]}")
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = body
    return (parsed, headers) if want_headers else parsed


def save_memory(agent, content, category="warm", keywords=""):
    return api("POST", "/api/memories", {"agent_id": agent, "content": content,
                                         "category": category, "keywords": keywords})


# MEMKERESVAK917: this used to return the body and drop r.headers on the floor.
# The memory search is deliberately forgiving -- when nothing matches the query
# as asked, it answers with whatever the leftover filler words pulled in, and
# that answer is byte-identical to a real hit in the BODY. The only thing that
# tells them apart is the X-Memory-Search response header. An agent calling this
# helper could not opt in: there is no `-D` to add to a Python function.
#
# So the label comes back WITH the rows, and `relaxed` gets its own warning
# string, because the whole failure mode is a caller who skims the rows.
def search_memory(agent, q, category=None, strict=False):
    from urllib.parse import quote
    path = f"/api/memories?agent={quote(agent)}&q={quote(q)}"
    if category:
        # No limit widening here on purpose. Until #1384 the tier filter ran
        # AFTER the limit, so a category search truncated in silence and this
        # asked for limit=200 to work around it. #1384 pushed the filter into
        # the search SQL, so the default window now holds rows the caller
        # actually asked for, and a hardcoded 200 would just be a bigger page
        # than every other call site uses.
        path += f"&category={quote(category)}"
    if strict:
        path += "&strict=1"
    rows, headers = api("GET", path, want_headers=True)
    label = ""
    for k, v in headers.items():
        if k.lower() == "x-memory-search":
            label = v
            break
    relaxed = "relaxed=true" in label
    out = {
        "label": label,
        "relaxed": relaxed,
        "strict": strict,
        "hits": len(rows) if isinstance(rows, list) else None,
        "rows": rows,
    }
    if relaxed:
        out["warning"] = ("relaxed=true -- semmi nem illeszkedett UGY, AHOGY KERTED. "
                          "Ezek mentett kozelitesek, NEM bizonyitek. Hiany-allitashoz "
                          "futtasd ujra strict=1-gyel.")
    return out


def daily_log(agent, content):
    return api("POST", "/api/daily-log", {"agent_id": agent, "content": content})


def send_message(from_agent, to_agent, content):
    return api("POST", "/api/messages", {"from": from_agent, "to": to_agent, "content": content})


def list_agents():
    return api("GET", "/api/agents")


def _kanban(where, params=()):
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, title, status, assignee, priority, project, due_date, "
            "updated_at FROM kanban_cards WHERE archived_at IS NULL AND " + where,
            params).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def kanban_due_today():
    return _kanban(
        "due_date IS NOT NULL AND status != 'done' "
        "AND date(due_date,'unixepoch','localtime') <= date('now','localtime') "
        "ORDER BY due_date")


def kanban_stuck(idle_seconds=14400):
    return _kanban("status = 'in_progress' AND updated_at < strftime('%s','now') - ? "
                   "ORDER BY updated_at", (idle_seconds,))


def kanban_by_status(status):
    return _kanban("status = ? ORDER BY priority DESC, updated_at DESC", (status,))


_MDV2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"


def escape_mdv2(text):
    """Escape literal text for Telegram MarkdownV2. Escape your dynamic text with
    this, THEN wrap intended formatting (e.g. '*'+escape_mdv2(label)+'*' for bold)."""
    return "".join("\\" + ch if ch in _MDV2_SPECIAL else ch for ch in str(text))


def escape_mdv2_keep_bold(text):
    """Escape for MarkdownV2 but leave '*' untouched, so hand-authored '*bold*'
    markers survive. Use this for long, hand-written messages (e.g. the morning
    brief) where the formatting is inline in the prose rather than wrapped around
    programmatic labels. Only '*' is preserved: every other special is escaped,
    so pair your asterisks or Telegram rejects the message with a 400."""
    return "".join(
        ch if ch == "*" else ("\\" + ch if ch in _MDV2_SPECIAL else ch)
        for ch in str(text)
    )


def outgoing_gate_check(text):
    """Return a list of problems the outgoing-copy-gate hook would reject.
    Cheaper to run here than to have the send blocked."""
    problems = []
    if "\u2014" in text or "\u2013" in text:
        problems.append("em/en dash present (the gate rejects it)")
    if " -- " in text.replace("\\-", "-"):
        problems.append("space-hyphen-hyphen-space present (the gate rejects it)")
    stars = text.count("*") - text.count("\\*")
    if stars % 2:
        problems.append("odd number of unescaped '*' (Telegram 400: unclosed entity)")
    return problems
# Csak olyan alakok, amik ONALLO szokent szinte sosem helyesek magyarul.
# 2026-08-23: az elso eles hasznalat kimutatta, hogy 'el', 'ok', 'kor', 'erre'
# TELJESEN SZABALYOS magyar szo (igekoto, fonev, fonev, hatarozo), tehat azok
# csak hamis riasztast adnak. A hamis riasztas rosszabb a semminel, mert
# leszoktat az eszkoz olvasasarol.
_ACCENTLESS = {
    "es": "és", "ot": "öt", "ora": "óra", "ev": "év", "ut": "út", "szo": "szó",
}

# TARTALEK-LISTA, NEM A FO FORRAS (2026-09-10, Kriptonit merese). A fenti hat par
# a KAPU 160 parjabol negy szazalek. Amig ez a lista volt az egyetlen forras, a
# gate_check "OK: mehet"-et adott olyan uzenetre, amit az eles kapu TILTOTT -- az
# `all`, `ar`, `cim`, `dontes`, `eleg`, `allapot` mind hianyzott innen. Ket kezzel
# szinkronban tartott lista definicio szerint szetcsuszik; ezert a helper mostantol
# NEM MASOL, hanem MAGAT A KAPUT hivja, es csak akkor esik vissza a hat parra, ha a
# kaput nem talalja -- olyankor viszont HANGOSAN jelzi, hogy a fedes reszleges.
# A masolas amugy sem lett volna eleg: a regi `\b([a-zA-Z]{2,4})\b` minta a
# HAROM betunel hosszabb bejegyzeseket (`dontes`, `allapot`) meg teljes listaval
# sem fogta volna meg.
_GATE_PATHS = (
    "scripts/hooks/outgoing-copy-gate.py",
    "../scripts/hooks/outgoing-copy-gate.py",
)
_gate_cache = []


def _load_gate():
    """Az ELES kimeno kapu betoltese modulkent (vagy None). Import-biztos: a
    fajlban minden def/konstans, a futtatas `if __name__ == "__main__"` mogott van."""
    if _gate_cache:
        return _gate_cache[0]
    import importlib.util, os
    gyoker = [os.environ.get("CLAUDE_PROJECT_DIR") or "", os.getcwd()]
    d = os.getcwd()
    for _ in range(4):                      # par szint felfele is
        d = os.path.dirname(d) or "/"
        gyoker.append(d)
    for g in gyoker:
        for rel in _GATE_PATHS:
            ut = os.path.normpath(os.path.join(g, rel)) if g else rel
            if os.path.isfile(ut):
                try:
                    sp = importlib.util.spec_from_file_location("_ocg", ut)
                    mod = importlib.util.module_from_spec(sp)
                    sp.loader.exec_module(mod)
                    _gate_cache.append(mod)
                    return mod
                except Exception:
                    pass
    _gate_cache.append(None)
    return None


def _accent_findings(plain):
    """Ekezet-talalatok. Ha az eles kapu elerheto, AZT hasznaljuk (sajat szotar,
    sajat tokenizalo, sajat kivetelek), kulonben a hat parra esunk vissza."""
    import re as _re
    g = _load_gate()
    if g is not None:
        prose = g.strip_technical(plain)
        tok_pos = g.accent_check_tokens(prose)
        szavak = [w for w, _ in tok_pos]
        if not (g.is_hungarian(plain) or g.accentless_evidence(szavak)):
            return []
        elso = {}
        for w, p in tok_pos:
            if w in g.ACCENTLESS and w not in elso:
                elso[w] = p
        return [{"kind": "ekezet", "word": w,
                 "context": prose[max(0, elso[w] - 30):elso[w] + len(w) + 15],
                 "fix": f"'{g.ACCENTLESS[w]}' vagy fogalmazd at ugy, hogy a toldalek eltunjon"}
                for w in sorted(elso)]
    ki = [{"kind": "figyelmeztetes",
           "fix": "AZ ELES KAPU NEM TALALHATO -- az ekezet-ellenorzes a hat szavas "
                  "tartalek-listaval fut, ami a kapu szotaranak 4 szazaleka. "
                  "A 'nincs talalat' itt NEM jelent atmenest."}]
    for m in _re.finditer(r"\b([a-zA-Z]{2,7})\b", plain):
        w = m.group(1).lower()
        if w in _ACCENTLESS:
            ki.append({"kind": "ekezet", "word": m.group(1),
                       "context": plain[max(0, m.start() - 30):m.end() + 15],
                       "fix": f"'{_ACCENTLESS[w]}' vagy fogalmazd at ugy, hogy a toldalek eltunjon"})
    return ki


def gate_check(text):
    """Dry-run the outgoing gates on a finished message, BEFORE calling reply.

    Mirrors the three checks that actually block sends:
      1. em dash (U+2014)      -- standing ban, blocks the whole message
      2. accent-less Hungarian words on a word boundary (the suffix false
         positive: 'Drive-ot' -> 'ot', 'BotFather-es' -> 'es')
      3. a full scheme-prefixed URL, which the outbound-data gate reads as a
         destination address when the call looks like a write

    Returns a list of findings; empty list means the message should pass.
    MarkdownV2 backslash escapes are stripped first, exactly like the gate does.
    """
    import re as _re
    plain = _re.sub(r"\\(.)", r"\1", str(text))
    # SZAM + MAGYAR TOLDALEK maszkolasa (2026-08-26). A szohatar a kotojelnel van,
    # tehat a "2024-es"-bol "es" lesz, a "3.9-es"-bol szinten -- es az "es" a
    # szotarban ott van, mert ONALLO szokent valoban "és" kellene. Ketszer futottam
    # bele (08-25 napindito "3.9-es", 08-26 szunetmentes-valasz "2024-es"), es
    # mindketszer ATFOGALMAZTAM a mondatot: rossz javitas, mert a szoveg romlik
    # attol, hogy az ellenorzo hibas. Ugyanez a maszkolas ment az eles kapuba
    # (scripts/hooks/outgoing-copy-gate.py, GATETG826) -- a kettonek egyeznie kell,
    # kulonben az elozetes proba mast mond, mint ami tenylegesen tilt.
    plain = _re.sub(r"\d[\d.,]*-\w+", " ", plain)
    out = []
    n = plain.count("\u2014")
    if n:
        out.append({"kind": "gondolatjel", "count": n,
                    "fix": "cserele kettospontra vagy pontra"})
    out.extend(_accent_findings(plain))
    for m in _re.finditer(r"https?://[^\s)\]]+", plain):
        out.append({"kind": "webcim", "url": m.group(0),
                    "fix": "sema nelkul ird (pl. github.com/x/y), vagy korulirva"})
    # PROZA-SZURO: az eles kapu (scripts/hooks/outgoing-copy-gate.py, strip_technical)
    # a dupla kotojelt es a homoglifat a PROZAN meri, nem a nyers szovegen -- igy a
    # kodreszletek, utvonalak es kapcsolok nem adnak hamis riasztast. Ugyanazt a
    # mintat masoljuk ide, kulonben a helper SZIGORUBB lesz, mint az eles kapu.
    prose = _re.sub(
        r"""https?://\S+ | [\w.+-]+@[\w-]+\.[\w.]+ | `[^`]*` | \b\w+(?:_\w+)+\b
          | \b\w+\.[A-Za-z]{2,10}\b | \b[\w-]*/[\w/-]+""",
        " ", plain, flags=_re.X)

    # DUPLA KOTOJEL gondolatjel-potlokent (2026-09-07). Az ELES kapu 2026-08-16 ota
    # tiltja; a helperbol kimaradt, ezert HAMIS "OK: mehet"-et adott, es a kuldes a
    # valodi kapun bukott el. Elso javitasomat Kriptonit merte vissza: a NYERS
    # szovegen szamolva HAMIS RIASZTAST adott kodblokkos parancsra
    # ("git log --oneline -- src/"), tehat szigorubb lett az eles kapunal.
    # *** MINDKET IRANY KAR: a hamis OK megnyugtat, a hamis riasztas pedig ARRA
    # VESZ RA, HOGY ATIRJ EGY JO SZOVEGET (a fenti 08-26-os komment pont ezt
    # nevesiti). *** Ezert a prozan merunk, ahogy az eles kapu.
    dh = prose.count(" -- ")
    if dh:
        out.append({"kind": "dupla-kotojel", "count": dh,
                    "fix": "kettospont, zarojel vagy uj mondat, kotojel nelkul"})

    # HOMOGLIFA (2026-09-07, Kriptonit merese). Latin szoba keveredett nem-latin
    # betu (jellemzoen cirill 'o', 'a', 'e'): OLVASVA LATHATATLAN, tehat itt a
    # hamis "OK" a teljes vedelmet viszi el -- az em dasht es a dupla kotojelt
    # eszreveszed elolvasva, ezt nem.
    import unicodedata as _ud
    def _script(ch):
        try:
            return _ud.name(ch).split()[0]
        except ValueError:
            return "?"
    for w in _re.findall(r"[^\W\d_]{2,}", prose, flags=_re.UNICODE):
        sc = {_script(c) for c in w if c.isalpha()}
        if "LATIN" in sc and len(sc) > 1:
            bad = next(c for c in w if c.isalpha() and _script(c) != "LATIN")
            out.append({"kind": "homoglifa", "word": w, "char": repr(bad),
                        "fix": "ird ujra a szot latin betukkel (olvasva lathatatlan, de a keresest eltori)"})
    return out


def _out(v):
    print(json.dumps(v, ensure_ascii=False, indent=2) if isinstance(v, (dict, list)) else v)


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "mdv2":
        print(escape_mdv2(rest[0] if rest else sys.stdin.read()))
    elif cmd == "mdv2b":
        src = rest[0] if rest else sys.stdin.read()
        bad = outgoing_gate_check(src)
        if bad:
            sys.stderr.write("BLOCKED before send:\n- " + "\n- ".join(bad) + "\n")
            return 2
        print(escape_mdv2_keep_bold(src))
    elif cmd == "mem-save":
        _out(save_memory(rest[0], rest[1], rest[2] if len(rest) > 2 else "warm",
                         rest[3] if len(rest) > 3 else ""))
    elif cmd == "mem-search":
        res = search_memory(rest[0], rest[1], rest[2] if len(rest) > 2 else None,
                            strict=(len(rest) > 3 and rest[3] in ("strict", "1", "true")))
        # stderr as well as the JSON field: the rows are what a reader's eye
        # goes to, and a rescued near-miss looks exactly like a real hit there.
        if res.get("warning"):
            sys.stderr.write("FIGYELEM: " + res["warning"] + "\n")
        _out(res)
    elif cmd == "daily-log":
        _out(daily_log(rest[0], rest[1]))
    elif cmd == "msg":
        _out(send_message(rest[0], rest[1], rest[2]))
    elif cmd == "agents":
        _out([{"name": a.get("name"), "running": a.get("running"),
               "model": a.get("model")} for a in list_agents()])
    elif cmd == "kanban-due":
        _out(kanban_due_today())
    elif cmd == "kanban-stuck":
        _out(kanban_stuck(int(rest[0]) if rest else 14400))
    elif cmd == "gate-check":
        found = gate_check(rest[0] if rest else sys.stdin.read())
        if not found:
            print("OK: mehet")
            return 0
        _out(found)
        return 1
    elif cmd == "kanban-status":
        _out(kanban_by_status(rest[0]))
    else:
        sys.stderr.write(f"unknown command: {cmd}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
