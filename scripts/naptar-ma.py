#!/usr/bin/env python3
"""Zoli VALODI naptarainak lekerdezese egy adott napra.

MIERT KELL (2026-08-16): a reggeli napindito a google-calendar MCP szervert
kerdezte, amibe egyetlen fiok van bekotve -- az agens SAJAT fiokja
(mzxhello1@gmail.com). Az mindig ures, tehat a napindito nulla esemenyt latott,
elhitte, es a szabaly szerint kihagyta a naptar-szekciot. Nema hiba: nem
hibauzenet jott, hanem egy hihetonek latszo nulla. Zoli aznap 11:00-kor
programra ment, amirol nem szoltam.

Zoli ket valodi naptara a szolgaltatasfiokos domain-wide delegation-on erheto
el (mzx-gmail-draft SA, calendar.events scope, mindket domainen). Annak nincs
token-lejarata, tehat ez a stabil ut -- az MCP OAuth-tokenje az, ami johet-mehet.

Hasznalat:
    python3 scripts/naptar-ma.py                # ma
    python3 scripts/naptar-ma.py 2026-08-20     # adott nap
    python3 scripts/naptar-ma.py --json         # gepi feldolgozashoz
"""

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo


def _helyi_zona():
    """A telepites zonaja: SCHEDULER_TZ (config-overrides.json, utana .env), kulonben a
    gep sajat zonaja NEVVEL (/etc/localtime), hogy a nyari/teli atallas szabalya megmaradjon.
    Ugyanaz a sorrend, mint a scripts/usage-collect.py-ban (ISSUE1895)."""
    gyoker = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        ov = json.load(open(os.path.join(gyoker, "store", "config-overrides.json"), encoding="utf-8"))
        if isinstance(ov, dict) and ov.get("SCHEDULER_TZ"):
            return str(ov["SCHEDULER_TZ"]).strip()
    except Exception:
        pass
    try:
        for sor in open(os.path.join(gyoker, ".env"), encoding="utf-8", errors="replace"):
            if sor.strip().startswith("SCHEDULER_TZ="):
                v = sor.strip().split("=", 1)[1].strip().strip("\"'")
                if v:
                    return v
    except Exception:
        pass
    cel = os.path.realpath("/etc/localtime")
    return cel.split("zoneinfo/", 1)[1] if "zoneinfo/" in cel else "UTC"


HELYI_TZ = ZoneInfo(_helyi_zona())

# A hitelesito reteg a gmail-draft.py-ban el (szolgaltatasfiok + JWT). Nem irjuk
# ujra: modulkent toltjuk be, es csak a megszemelyesitett fiokot / scope-ot
# allitjuk at hivasonkent.
_spec = importlib.util.spec_from_file_location(
    "gd", "/Users/zoli/marveen/scripts/gmail-draft.py")
gd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gd)

CAL_SCOPE = "https://www.googleapis.com/auth/calendar.events"
FIOKOK = ["szalai.zoltan@ibc.co.hu", "hello@zoltanszal.ai"]

# --- A PRIVAT (fogyasztoi) NAPTARAK, 2026-09-09 -------------------------------
# MIERT KELLETT MEGIS EGY MASODIK UT: a fenti ket cim Zoli SAJAT domainjein van,
# oda szolgaltatasfiokkal, domain-wide delegationnel megyunk be. A szemelyes
# szalaizp@gmail.com a GOOGLE domainjen van, ott delegacio ELVILEG nem letezik,
# tehat oda felhasznaloi OAuth kell. A tokent a google-calendar MCP szerver
# tarolja fiokonkent; onnan olvassuk, nem duplikaljuk a bekotest.
#
# MIERT SZAMIT EZ: 2026-09-09-ig a napindito CSAK a ket ceges naptarat kerdezte,
# tehat Zoli privat programjai SOSEM latszottak benne. Aznap 17:00-kor volt egy
# "Henrik: order flow & volume analizis" a tervezo naptarban, es a reggeli
# uzenetbol kimaradt. Ugyanaz a nema-nulla hiba-osztaly, mint amit ez a szkript
# 2026-08-16-an megszuntetett, csak egy szinttel feljebb: nem rossz fiokot
# kerdeztunk, hanem egy egesz forrast nem kerdeztunk meg.
OAUTH_TOKENEK = "/Users/zoli/.config/google-calendar-mcp/tokens.json"
OAUTH_KLIENS = "/Users/zoli/.gmail-mcp/credentials.json"
OAUTH_FIOK = "zoli"
# Az unnepnap-naptarak (hu/en holiday) SZANDEKOSAN nincsenek itt: minden
# unnepnapon bezajositanak egy sort, es Zoli tudja, mikor van augusztus 20.
PRIVAT_NAPTARAK = [
    ("Zoli privat", "szalaizp@gmail.com"),
    ("tervezo", "fbc25096169ceced4c866909c5f47c296676e721d25b1232cd51f0c518a06541@group.calendar.google.com"),
    ("Csalad", "family00062503414700300061@group.calendar.google.com"),
]


def _oauth_token():
    """Access token a privat naptarakhoz, a MCP szerver refresh tokenjebol."""
    with open(OAUTH_KLIENS, encoding="utf-8") as fh:
        k = json.load(fh)["installed"]
    with open(OAUTH_TOKENEK, encoding="utf-8") as fh:
        rt = json.load(fh)[OAUTH_FIOK]["refresh_token"]
    adat = urllib.parse.urlencode({
        "client_id": k["client_id"], "client_secret": k["client_secret"],
        "refresh_token": rt, "grant_type": "refresh_token",
    }).encode()
    keres = urllib.request.Request("https://oauth2.googleapis.com/token", data=adat)
    with urllib.request.urlopen(keres, timeout=30) as r:
        return json.load(r)["access_token"]


def nap_hatarai(nap):
    """A nap eleje es vege Budapest szerint, a NAPRA ervenyes offsettel.

    2026-10-25-ig itt fix +02:00 allt: telen (CET, UTC+1) ez az ablakot egy oraval
    elcsusztatta, az elozo nap 23:00-as esemenye bekerult, a mai 23:00 utani kimaradt.
    """
    tz = HELYI_TZ
    d = date.fromisoformat(str(nap))
    eleje = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
    vege = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz)
    return eleje.isoformat(), vege.isoformat()


def privat_esemenyek(naptar_id, nap, token):
    t_min, t_max = nap_hatarai(nap)
    q = urllib.parse.urlencode({
        "timeMin": t_min,
        "timeMax": t_max,
        "singleEvents": "true",
        "orderBy": "startTime",
    })
    url = ("https://www.googleapis.com/calendar/v3/calendars/"
           f"{urllib.parse.quote(naptar_id)}/events?{q}")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("items", [])


def esemenyek(fiok, nap):
    """Egy fiok primary naptaranak esemenyei az adott napon (lokal ido)."""
    gd.SUBJECT_USER = fiok
    gd.SCOPE = CAL_SCOPE
    token = gd.access_token()
    t_min, t_max = nap_hatarai(nap)
    q = urllib.parse.urlencode({
        # A Google a naptar sajat idozonajaban ertelmezi, a kiirt offset teszi
        # egyertelmuve (nyaron +02:00, telen +01:00, a naptol fuggoen).
        "timeMin": t_min,
        "timeMax": t_max,
        "singleEvents": "true",   # ismetlodo esemenyek peldanyokra bontva
        "orderBy": "startTime",
    })
    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{q}"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("items", [])


def formaz(e):
    start = e.get("start", {})
    dt = start.get("dateTime")
    if dt:
        # Az esemeny sajat offsetje UTC (Z) is lehet (pl. a Csalad naptar),
        # ezert Budapestre valtjuk, kulonben ket oraval korabbi idot irna ki.
        idopont = (datetime.fromisoformat(dt.replace("Z", "+00:00"))
                   .astimezone(HELYI_TZ).strftime("%H:%M"))
    else:
        idopont = "egesz nap"
    return idopont, e.get("summary", "(cim nelkul)"), e.get("location", "")


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    gepi = "--json" in sys.argv
    nap = args[0] if args else date.today().isoformat()

    osszes = []
    for fiok in FIOKOK:
        try:
            for e in esemenyek(fiok, nap):
                idopont, cim, hely = formaz(e)
                osszes.append({"fiok": fiok, "ido": idopont, "cim": cim, "hely": hely})
        except urllib.error.HTTPError as err:
            # Hangosan bukjunk: egy nema nulla pont ezt a szkriptet tette szuksegesse.
            uzenet = f"{fiok}: HTTP {err.code} -- {err.read()[:200].decode(errors='replace')}"
            if gepi:
                osszes.append({"fiok": fiok, "hiba": uzenet})
            else:
                print(f"HIBA {uzenet}", file=sys.stderr)

    # A privat naptarak EGY tokennel mennek, ezert a token-keres kivul van a
    # cikluson: ha az bukik, mind a harom naptar egyszerre esik ki, es azt EGY
    # hibasorral kell jelenteni, nem harommal.
    try:
        ptoken = _oauth_token()
    except Exception as err:                      # noqa: BLE001 -- hangos bukas kell
        ptoken = None
        uzenet = f"privat naptarak: nincs token -- {type(err).__name__}: {err}"
        if gepi:
            osszes.append({"fiok": "privat", "hiba": uzenet})
        else:
            print(f"HIBA {uzenet}", file=sys.stderr)
    if ptoken:
        for nev, naptar_id in PRIVAT_NAPTARAK:
            try:
                for e in privat_esemenyek(naptar_id, nap, ptoken):
                    idopont, cim, hely = formaz(e)
                    osszes.append({"fiok": nev, "ido": idopont, "cim": cim, "hely": hely})
            except urllib.error.HTTPError as err:
                uzenet = f"{nev}: HTTP {err.code} -- {err.read()[:200].decode(errors='replace')}"
                if gepi:
                    osszes.append({"fiok": nev, "hiba": uzenet})
                else:
                    print(f"HIBA {uzenet}", file=sys.stderr)

    if gepi:
        print(json.dumps({"nap": nap, "esemenyek": osszes}, ensure_ascii=False))
        return

    if not osszes:
        print(f"{nap}: egyik naptarban sincs esemeny.")
        return
    print(f"{nap}:")
    for e in sorted(osszes, key=lambda x: x.get("ido", "")):
        hely = f"  [{e['hely']}]" if e.get("hely") else ""
        print(f"  {e['ido']}  {e['cim']}{hely}   ({e['fiok']})")


if __name__ == "__main__":
    main()
