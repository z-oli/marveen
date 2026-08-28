#!/usr/bin/env python3
"""IBC Nyelviskola árajánlat + vezetői összefoglaló generátor.

Használat:
    python3 scripts/ibc-ajanlat/generate.py <adat.json> [kimeneti-mappa]

Két PDF-et készít: IBC_Arajanlat_<cegkod>.pdf (10 oldal) és
IBC_Executive_Summary_<cegkod>.pdf (1 oldal).

Az arculat forrása a claude.ai archívumból mentett IBC_Arajanlat_Kontextus.md,
a tördelés a korábbi kész ajánlatokból (Praktiker, CATL) van visszafejtve.
A boilerplate szöveg alapértelmezésben a Praktiker-ajánlatból származik; minden
cégspecifikus mezőt a JSON ír felül.
"""
import base64
import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

REFERENCIAK = ["STRABAG", "LIDL", "OTP Group", "Coca-Cola", "Nissan", "E.ON",
               "Dreher", "Honeywell", "Novartis", "B.Braun", "GrandVision", "HÖRMANN"]

KAPCSOLAT = {
    "telefon": "+36 20 999 60 50",
    "email": "info@ibc.co.hu",
    "web": "ibc.co.hu",
    "szekhely": "1137 Budapest, Jászai Mari tér 5-6.",
    "far": "B/2020/000684",
}


# Amit nem ad meg a JSON, azt innen veszi. Így egy új ajánlathoz elég a cégnév, a
# kutatásból származó leírás, a létszám és az ár -- a többi a szokásos IBC-alapérték.
DEFAULTS = {
    "ev": "2026",
    "ervenyesseg": "2026.12.31",
    "nyelv": "Angol",
    "oktatok": "Magyar anyanyelvű diplomás nyelvtanárok",
    "helyszin": "Online (személyes oktatásról egyeztetés szükséges)",
    "utemezes": "Heti 2 alkalom, alkalom = 90 perc (2x45 perc)",
    "forma": "csoportos képzés (max 5 fő/csoport, több párhuzamos csoport indítása)",
    "felso_csoport": "tárgyalási angol",
    "szolgaltatas": "Online csoportos képzés",
    "egyseg": "45 perc",
    "fizetes": "Havonta utólag, a teljesített nyelvórák alapján, 30 napos fizetési határidővel",
    "dij_tartalma": [
        "Igény- és szintfelmérést (megkezdődő tréningen résztvevőknek díjmentes)",
        "Nyelvtanár díjazását és minden költséget",
        "Résztvevői óralemondások, átütemezések kezelését és nyilvántartását",
        "Kurzus végi méréseket, konzultációkat, képzés-záró riportokat",
        "Dedikált kapcsolattartó és szakmai projektvezető kinevezését",
        "Havi HR riport, ROI riport (félévente) és ROI riport (évente)",
        "Modulzáró vizsgát írásban és szóban, 80 óra után objektív szintvisszamérést",
        "A felnőttképzési adminisztráció teljes menedzselését (FAR)",
    ],
    "ibc_intro": "Az IBC Nyelviskola 15 éve a vállalati nyelvoktatás megbízható partnere. Szakértelmünk a kommunikáció-központú, munkakör-specifikus nyelvi fejlesztésben rejlik, amelyet rugalmas oktatási formákkal és mérhető eredményekkel támogatunk.",
    "kovetkezo_lepesek": ["Igényfelmérés és szintfelmérés", "Csoportkialakítás",
                          "Képzési terv egyeztetés", "Képzés indítás"],
    # A vezetoi osszefoglalo "Az ar tartalmazza:" sora. Korabban be volt egetve a
    # sablonba; azert lett mezo, hogy EGY ajanlatban lehessen mast irni (2026-08-14,
    # Geodis: dijmentes angol bemutato ora), a tobbi ajanlat valtozatlan maradasa mellett.
    # Rovid legyen: egy sorban all a lapon, hosszan tullogna.
    "ar_tartalmazza_rovid": "ROI riport, oktatásszervezés, szintfelmérés",
    # A bemutatoora NYELVI jelzoje. Alapertelmezesben ures, tehat "bemutatoorat biztositunk".
    # Tobbnyelvu ajanlatnal, ahol a bemutatot csak egy nyelven vallaljuk, ide jon a nyelv
    # SZOKOZZEL a vegen: "angol " -> "angol bemutatoorat biztositunk" (2026-08-14, Geodis).
    "bemutatoora_jelzo": "",
}


def felsorol(items):
    """Magyar felsorolás: "angol", "angol és német", "angol, német és francia"."""
    items = [str(x).strip() for x in items if str(x).strip()]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " és " + items[-1]


def normalize_nyelv(d):
    """A `nyelv` lehet egy szöveg vagy egy lista. A dokumentum mindenhol ugyanazt a
    felsorolást használja, tehát itt egyszer összefűzzük."""
    nyelv = d.get("nyelv", DEFAULTS["nyelv"])
    if isinstance(nyelv, (list, tuple)):
        nyelv = felsorol([n.capitalize() for n in nyelv])
    d["nyelv"] = nyelv
    return d


def normalize_arak(d):
    """Egy vagy több árazási sor.

    A JSON vagy egy `arak` listát ad (mindegyik elem: nev, ar, opcionálisan egyseg,
    kedvezmeny, kedvezmenyes_ar, tipus="online"|"szemelyes"), vagy a régi, egysoros
    mezőket (szolgaltatas, ar, ...). A régi forma működik tovább, csak listává alakul.
    """
    if not d.get("arak"):
        d["arak"] = [{
            "nev": d.get("szolgaltatas", DEFAULTS["szolgaltatas"]),
            "ar": d.get("ar", ""),
            "egyseg": d.get("egyseg", DEFAULTS["egyseg"]),
            "kedvezmeny": d.get("kedvezmeny", ""),
            "kedvezmenyes_ar": d.get("kedvezmenyes_ar", ""),
            "tipus": d.get("tipus", "online"),
        }]
    for a in d["arak"]:
        a.setdefault("egyseg", d.get("egyseg", DEFAULTS["egyseg"]))
        a.setdefault("kedvezmeny", "")
        a.setdefault("kedvezmenyes_ar", "")
        # Ha nincs megadva, a nevéből döntjük el, online vagy helyszíni.
        a.setdefault("tipus", "szemelyes"
                     if ("helyszín" in a["nev"].lower() or "személyes" in a["nev"].lower())
                     else "online")
    # A helyszín-sor és a szolgáltatás-megnevezés kövesse, mi szerepel ténylegesen az árak közt.
    tipusok = {a["tipus"] for a in d["arak"]}
    if "helyszin" not in d:
        d["helyszin"] = {
            frozenset({"online"}): "Online",
            frozenset({"szemelyes"}): "Személyes (helyszíni)",
        }.get(frozenset(tipusok), "Online és személyes (helyszíni)")
    d.setdefault("szolgaltatas", d["arak"][0]["nev"])
    d.setdefault("ar", d["arak"][0]["ar"])
    return d


def apply_defaults(d):
    """Kitölti a hiányzó mezőket. A levezethetőket a megadottakból számolja."""
    normalize_nyelv(d)
    normalize_arak(d)
    for key, value in DEFAULTS.items():
        d.setdefault(key, value)
    d.setdefault("datum", __import__("datetime").date.today().strftime("%Y.%m.%d."))
    # Hatarozott nevelo a cegnev elott. A sablon hat helyen irja ki ("a <Ceg> reszere",
    # "Miert az IBC a <Ceg> idealis partnere?" stb.); korabban be volt egetve "a"-nak,
    # amitol maganhangzoval kezdodo cegnevnel HELYESIRASI HIBA ment ki a partnernek
    # (2026-08-18, i-Cell Kft.: "Szolgaltatasaink a i-Cell Kft. szamara"). A betu szerinti
    # levezetes lefedi az eseteket tulnyomo reszet; a KIEJTES viszont nem mindig koveti az
    # irast (pl. "a Unilever", mert "ju"-nak hangzik), ezert a JSON-bol feluliraható.
    d.setdefault("nevelo", "az" if d["ceg"][:1].lower() in "aáeéiíoóöőuúüű" else "a")
    # 2026-08-28: a 08-18-i javitas HAT sablon-helyet fedett le, de KETTOT kihagyott,
    # mert ott a nevelo MONDATKEZDO, es beegetett nagy "A "-kent allt egy f-string
    # kozepen (a "Uzleti nyelvezet" kartya es a HR-oldal lead bekezdese). Az IdomSoft
    # Zrt. ajanlataban emiatt ket helyen "A IdomSoft" jelent meg, mikozben a masik hat
    # helyen helyesen "az IdomSoft" allt. A grep a "nevelo" szora nem talalta meg oket,
    # mert epp az hianyzott beloluk. Mondatkezdo helyen `nevelo.capitalize()` kell.
    d.setdefault("ceg_rovid", d["ceg"].split()[0])
    d.setdefault("cegkod", d["ceg_rovid"].replace(".", ""))
    d.setdefault("csapat_rovid", d.get("csapat", "csapatának"))
    d.setdefault("egyeztetes_szo", "szakmai egyeztetések")
    d.setdefault("szolgaltatas_leiras",
                 [d.get("kepzes_celja", ""), "Online képzés", "Csoportos (max 5 fő/csoport)"])
    return d


def e(value):
    """HTML-escape; None -> üres."""
    return html.escape(str(value)) if value is not None else ""


def logo_data_uri():
    with open(os.path.join(HERE, "assets", "logo.png"), "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


def footer(page_no, total):
    return (f'<div class="footer"><span>{KAPCSOLAT["email"]} &nbsp;|&nbsp; '
            f'{KAPCSOLAT["telefon"]} &nbsp;|&nbsp; {KAPCSOLAT["web"]}</span>'
            f'<span>{page_no} / {total}</span></div>')


def stat(num, label, green=False):
    cls = "stat green" if green else "stat"
    return f'<div class="{cls}"><div class="num">{num}</div><div class="lbl">{label}</div></div>'


def pricecard(d, compact=False):
    """A közös árazó kártya -- a 9. oldalon és a vezetői összefoglalóban is ez fut.

    A vezetői összefoglaló (compact) egyetlen, fix 297mm-es lapra megy, ezért ott az
    alap- és a kedvezményes ár EGYMÁS MELLETT áll. Kedvezménnyel az egymás alá tördelt
    változat ~30mm-rel magasabb, és kitolná a lap aljáról a referenciákat és a
    következő lépéseket -- a .page overflow:hidden miatt némán, észrevétlenül.
    """
    cards = []
    tobb = len(d["arak"]) > 1
    for a in d["arak"]:
        if compact:
            p = ['<div class="pricecard compact">',
                 f'<div class="head">{e(a["nev"])}'
                 f'<span class="small">{e(a["egyseg"])}</span></div>',
                 '<div class="prow">']
            if a.get("kedvezmeny") and tobb:
                # Több kártya + kedvezmény: külön alapár-blokk nem fér el a lapon,
                # ezért a listaár a kedvezményes ár alá, apró betűvel kerül.
                p.append('<div class="final">Kedvezményes ár:'
                         f'<b>{e(a["kedvezmenyes_ar"])}</b>'
                         f'<span class="dlbl">{e(a["kedvezmeny"])} '
                         f'&nbsp;·&nbsp; listaár: {e(a["ar"])}</span></div>')
            else:
                p.append(f'<div class="base">Ár:<b>{e(a["ar"])}</b></div>')
                if a.get("kedvezmeny"):
                    p.append('<div class="final">Kedvezményes ár:'
                             f'<b>{e(a["kedvezmenyes_ar"])}</b>'
                             f'<span class="dlbl">{e(a["kedvezmeny"])}</span></div>')
            p.append("</div></div>")
        else:
            p = ['<div class="pricecard">',
                 f'<div class="head">{e(a["nev"])}'
                 f'<span class="small">{e(a["egyseg"])}</span></div>']
            # A szolgáltatás-leírás csak egyetlen árnál fér el olvashatóan.
            if not tobb:
                for line in d.get("szolgaltatas_leiras", []):
                    p.append(f'<div class="desc">{e(line)}</div>')
            p.append(f'<div class="base">Ár:<b>{e(a["ar"])}</b></div>')
            if a.get("kedvezmeny"):
                p.append(f'<div class="disc">{e(a["kedvezmeny"])}</div>')
                p.append('<div class="final">Kedvezményes ár:'
                         f'<b>{e(a["kedvezmenyes_ar"])}</b></div>')
            p.append("</div>")
        cards.append("".join(p))

    # Egyetlen kártya: a megszokott, középre zárt szélesség (CSS intézi).
    # Több kártya: egymás mellett, egyenlő szélességben.
    if len(cards) == 1:
        return cards[0]
    return f'<div class="pricegrid">{"".join(cards)}</div>'


# --------------------------------------------------------------------------- oldalak

def p1_borito(d, logo):
    return f"""
<div class="page">
  <div class="cover-top">
    <div class="blob a"></div><div class="blob b"></div>
    <img class="logo-mark cover-logo" src="{logo}" alt="IBC">
    <div class="cover-brand">IBC Nyelviskola</div>
    <div class="cover-title">NYELVI KÉPZÉS<br>ÁRAJÁNLAT</div>
    <div class="cover-for">{e(d['nevelo'])} {e(d['ceg'])} részére</div>
  </div>
  <div class="cover-bottom">
    <div class="warmblob"></div>
    <div class="inner">
      <div class="cover-label">Elérhetőségeink:</div>
      <div class="cover-contact">{KAPCSOLAT['telefon']}</div>
      <div class="cover-contact">{KAPCSOLAT['email']}</div>
      <div class="cover-far">Felnőttképzési Nyilvántartási Szám: {KAPCSOLAT['far']}</div>
      <div class="cover-date">Dátum: {e(d['datum'])}<br>
        <b>Ajánlat érvényessége: {e(d['ervenyesseg'])}</b></div>
    </div>
  </div>
</div>"""


def p2_bemutatkozas(d):
    refs = "".join(f'<div class="pill">{e(r)}</div>' for r in REFERENCIAK)
    return f"""
<div class="page"><div class="body">
  <h1 class="page-title">IBC Nyelviskola<span class="sub">a vállalati nyelvoktatás szakértője</span></h1>
  <p class="lead">Több mint 15 éves tapasztalattal, meghatározó szereplőként a vállalati
  nyelvoktatás területén az IBC Nyelviskola folyamatosan fejlődik és bővül. Jelenleg több mint
  650 aktív nyelvtanfolyamot vezetünk, közel 1200 résztvevő számára.</p>
  <p class="lead">Erős nagyvállalati referenciáink és 15+ év tapasztalatunk biztosítja, hogy
  {e(d['nevelo'])} {e(d['ceg'])} számára is kiemelt minőségű nyelvi képzést tudjunk nyújtani, mérhető
  eredményekkel és teljes körű támogatással.</p>

  <h2>Miért az IBC {e(d['nevelo'])} {e(d['ceg'])} ideális nyelvi partnere?</h2>
  <div class="warmbox">{e(d['ceg_leiras'])}</div>

  <h2>Szakmai küldetésünk</h2>
  <p>Küldetésünknek tekintjük, hogy a nyelvtanfolyami résztvevők valódi, aktív nyelvi készségeket
  és kompetenciákat sajátítsanak el. Dinamikus és interaktív tanulási környezetet teremtve
  lehetővé tesszük, hogy valós munkahelyi szituációkban fejlesszék nyelvtudásukat.</p>

  <div class="stats">
    {stat('650+', 'aktív tanfolyam,<br>közel 1200 résztvevő')}
    {stat('130+', 'magasan képzett<br>nyelvoktató')}
    {stat('15+ év', 'vállalati nyelvoktatási<br>tapasztalat')}
    {stat('94%', 'résztvevői<br>elégedettség', green=True)}
  </div>

  <h2>Néhány referenciánk</h2>
  <div class="pills">{refs}</div>
</div>{footer(2, 10)}</div>"""


def p3_modszertan(d):
    items = [
        ("Üzleti nyelvezet a napi munkához",
         f"Valós, gyakorlati üzleti helyzetekre fókuszálunk: tárgyalási szituációk, "
         f"{d['szaknyelv']}, nemzetközi partnerkommunikáció. {d['nevelo'].capitalize()} {d['ceg_rovid']} "
         f"{d['csapat_rovid']} igényeire szabva."),
        ("Interaktív és beszédcentrikus",
         "100% célnyelvhasználattal és 80% résztvevői aktivitással a beszédkészség "
         "fejlesztésére fektetjük a hangsúlyt. Szituációs feladatok, páros és kiscsoportos "
         "gyakorlatok."),
        ("Kommunikáció-központú megközelítés",
         "Aktív üzleti és munkahelyi nyelvhasználatra fókuszálunk. A résztvevők a meetingek, "
         f"prezentációk, tárgyalások és {d['egyeztetes_szo']} nyelvét sajátítják el."),
        ("Testre szabott, motiváló nyelvórák",
         "Személyre és a csoport igényeire szabott tanulási élményt nyújtunk. Az órák "
         "változatosan épülnek fel: warm-up, egyéni és pármunkák, brainstorming, vita és "
         "szerepjáték."),
    ]
    numbered = "".join(
        f'<div class="item"><div class="n">{i}</div><div><h3>{e(t)}</h3>'
        f'<p style="font-size:8.5pt;color:#4a4d63">{e(b)}</p></div></div>'
        for i, (t, b) in enumerate(items, 1))
    menet = [("Warm-up feladatok", "rövid ráhangolódás, beszédindítás"),
             ("Előző tartalmak ismétlése", "gyors revízió, aktiválás"),
             ("Új tartalom bevezetése", "szemléletes példákkal, kontextusban"),
             ("Gyakorlás", "fokozatosan a kommunikatív feladatokig, sok beszéddel"),
             ("Összegzés", "kulcspontok rögzítése, rövid visszajelzés"),
             ("Cool down feladatok", "könnyebb lezárás, átvezetés a következő órára")]
    lepesek = "".join(
        f'<li><b>{i}. {e(t)}</b><br><span style="color:#6c7085;font-size:8pt">{e(s)}</span></li>'
        for i, (t, s) in enumerate(menet, 1))
    return f"""
<div class="page"><div class="body">
  <h1 class="page-title">Módszertani szemléletünk</h1>
  <p class="lead">Az IBC Nyelviskola oktatási módszertana a valós munkahelyi kommunikáció
  fejlesztésére fókuszál. Beszédcentrikus, interaktív óráink garantálják a gyors és mérhető
  fejlődést.</p>
  <div class="numlist">{numbered}</div>
  <div class="stats">
    {stat('100%', 'célnyelv-<br>használat')}
    {stat('80%', 'résztvevői<br>aktivitás')}
    {stat('4 készség', 'párhuzamos<br>fejlesztése')}
    {stat('A1–C2', 'szintek<br>lefedése')}
  </div>
  <h2>Nyelvóráink menete</h2>
  <ul class="dots" style="columns:2;column-gap:8mm">{lepesek}</ul>
</div>{footer(3, 10)}</div>"""


def p4_portfolio(d):
    cards = [
        ("Vállalati nyelvtanfolyamok",
         "Csoportos, beszédközpontú nyelvtanfolyamok az aktív szakmai és általános nyelvtudás "
         "fejlesztésére, szinten tartására."),
        ("Szaknyelvi tanfolyam",
         f"{d['szaknyelv'].capitalize()}, terminológia és üzleti szakszókincs fejlesztése valós "
         "munkahelyi szituációkon keresztül."),
        ("Üzleti nyelvi képzés",
         "A szervezet profiljának és a munkaköröknek megfelelő üzleti nyelvi kompetenciák gyors "
         "és hatékony fejlesztése."),
        ("Anyanyelvi tanfolyam",
         "Diplomás, anyanyelvi tanárokkal kiejtésjavítás és beszédkészség-fejlesztés. Magas "
         f"szintű {d['nyelv'].lower()}, személyre szabott tematikával."),
        ("Üzleti nyelvi coaching",
         "Intenzív, személyre szabott felkészülés: prezentációk, tárgyalások, meetingek, "
         "konferencia-előadások nyelvi támogatása."),
        ("Nyelvi tréningek",
         "100% beszédfókuszú, kiscsoportos, 1-2 napos nyelvi tréningek a magabiztos nyelvtudás "
         "és üzleti készségek fejlesztésére."),
    ]
    grid = "".join(f'<div class="card"><h3>{e(t)}</h3><p>{e(b)}</p></div>' for t, b in cards)
    return f"""
<div class="page"><div class="body">
  <h1 class="page-title">Portfóliónk</h1>
  <p class="lead">Rugalmas, testre szabható képzésekkel biztosítjuk a szakmai és nyelvi fejlődést.</p>
  <div class="card-grid">{grid}</div>
  <h2>Az oktatás jellemzői</h2>
  <div class="spec"><table>
    <tr><td class="k">Nyelv:</td><td>{e(d['nyelv'].lower())}</td></tr>
    <tr><td class="k">Forma:</td><td>{e(d['forma'])}</td></tr>
    <tr><td class="k">Helyszín:</td><td>{e(d['helyszin'])}</td></tr>
    <tr><td class="k">Intenzitás:</td><td>{e(d['utemezes'])}</td></tr>
    <tr><td class="k">Szintfelmérés:</td><td>online írásbeli és szóbeli teszt a képzésre jelentkezéskor</td></tr>
  </table></div>
</div>{footer(4, 10)}</div>"""


def p5_minoseg(d):
    pillars = [
        ("Résztvevői elégedettségmérés",
         "Online és anonim kérdőíves formában végezzük. A kérdőív célzott kérdései kiterjednek a "
         "képzési program hasznosságára, a tanárok szakmai felkészültségére és az oktatás "
         "tartalmi minőségére."),
        ("Óralátogatások és tanári minőségbiztosítás",
         "Vezető nyelvtanáraink egy előre meghatározott értékelési rendszer mentén elemzik az "
         "órák menetét. Tanárainkat interjún, próbatanításon és rendszeres óralátogatáson "
         "ellenőrizzük."),
        ("Rendszeres HR megbeszélések",
         "Proaktív együttműködésünk során rendszeresen gyűjtjük a belső visszajelzéseket. "
         "Teljesítményértékelő megbeszélésen egyeztetjük a hosszabbításokat, elégedettséget és "
         "javítási lehetőségeket."),
        ("Rugalmas óramegoldások",
         "Tanáraink óralemondás esetén kellő rugalmassággal igyekeznek alternatív időpontokat "
         "biztosítani. A képzési időszakban van lehetőség tanárcserére is – a kérés beérkezését "
         "követő 5 napon belül."),
    ]
    lst = "".join(
        f'<div class="item"><div class="n">{i}</div><div><h3>{e(t)}</h3>'
        f'<p style="font-size:8.5pt;color:#4a4d63">{e(b)}</p></div></div>'
        for i, (t, b) in enumerate(pillars, 1))
    return f"""
<div class="page"><div class="body">
  <h1 class="page-title">Minőségbiztosítás és szintfelmérés</h1>
  <h2>Szintfelmérés és csoportkialakítás</h2>
  <p>A képzés előtt minden résztvevő online írásbeli és szóbeli szintfelmérőn vesz részt, amely
  az Európai Nyelvi Keretrendszerhez (CEFR) igazodik. Ez alapján a {e(d['csapat'])} szint
  szerinti csoportokba szervezzük (pl. A2, B1, B2, C1). Lehetőség van „középfok” és
  „{e(d['felso_csoport'])}” szintű csoportok indítására is.</p>
  <div class="stats">
    {stat('130+', 'képzett nyelvtanár<br>országos hálózatunkban')}
    {stat('C2 szint', 'tökéletes nyelvtudás,<br>nyelvtanári diploma')}
    {stat('15+ év', 'átlag tapasztalat<br>a felnőttképzésben')}
    {stat('94%', 'elégedettség<br>visszajelzések alapján', green=True)}
  </div>
  <h2>Minőségbiztosításunk pillérei</h2>
  <div class="numlist">{lst}</div>
</div>{footer(5, 10)}</div>"""


def p6_meres(d):
    riportok = [
        ("HR riport – havonta",
         "Rendszeres jelentés: résztvevők listája, szintjeik, csoportbeosztás, megtartott órák, "
         "hiányzások, lemondások, képzési aktivitás összesítve."),
        ("ROI riport – félévente",
         "Follow-up kérdőív a résztvevőknek, vezetői mini-értékelés (5-10 fő), és 3-5 "
         "esettanulmány interjú a tényleges munkavégzési változások objektív validálására."),
        ("ROI riport – évente",
         "2-3 kiválasztott üzleti mutató folyamatos követése baseline méréstől kezdve, "
         "összehasonlítva a képzésben résztvevők és nem résztvevők teljesítményét."),
    ]
    cards = "".join(f'<div class="card" style="flex:1 1 calc(33% - 3mm)"><h3>{e(t)}</h3>'
                    f'<p>{e(b)}</p></div>' for t, b in riportok)
    meresek = [
        ("Szintfelmérés", "Online szintfelmérő eszközünkkel a szintfelmérés bármikor, bárhonnan, "
                          "30 percen belül elvégezhető."),
        ("Visszamérés", "80 óránként végezzük, melyek eredményét összehasonlító táblázatokban "
                        "küldjük meg a megrendelő cég számára."),
        ("Elégedettségmérés", "Online kérdőívünkön keresztül lehetőség van minden óra után "
                              "visszajelzést adni, a képzési modul végén részletesebb kérdőív "
                              "kitöltésére kerül sor."),
        ("ROI mérés", "Félévente és évente mérjük a képzés üzleti hatását, összehasonlítva a "
                      "résztvevők és nem résztvevők teljesítményét."),
    ]
    lst = "".join(f'<li><b>{e(t)}</b><br><span style="color:#4a4d63;font-size:8.5pt">{e(b)}</span></li>'
                  for t, b in meresek)
    return f"""
<div class="page"><div class="body">
  <h1 class="page-title">Mérhető fejlődés és riportolás</h1>
  <p class="lead">A képzés kezdetekor megmérjük a résztvevők szóbeli és írásbeli teljesítményét
  az Európai Nyelvi Keretrendszerhez igazított szintrendszerünk és kompetencia-mátrixunk mentén.
  Méréseinket jellemzően 80 óránként végezzük.</p>
  <h2>HR riportolási rendszerünk</h2>
  <p style="margin-bottom:3mm">Támogatjuk az adatalapú döntéshozatalt és igazolt üzleti értéket
  teremtünk a L&amp;D folyamatokban.</p>
  <div class="card-grid">{cards}</div>
  <h2>Mérési módszereink</h2>
  <ul class="dots">{lst}</ul>
</div>{footer(6, 10)}</div>"""


def p7_hr(d):
    roadmap = [
        ("Előkészítés", ["Fejlesztési célok és igények egyeztetése",
                         "Résztvevők adatainak lejelentése (FAR)",
                         "Language policy támogatása"]),
        ("Tervezés &amp; Elindulás", ["Online szóbeli és írásbeli szintfelmérés",
                                      "Konzultáció a HR csapattal, csoportbeosztás",
                                      "Képzési terv és tanfolyamok elindítása"]),
        ("Reporting &amp; Adminisztráció", ["Jelenléti ívek csatolása a számlákhoz havonta",
                                            "Excel riport a jelenlétről, kumulatívan",
                                            "Havi HR riport automatikus megküldése"]),
        ("Haladás és Eredménykövetés", ["80 óránként modulzáró vizsga + elégedettségi kérdőív",
                                        "80 óránként objektív visszamérés",
                                        "ROI riport félévente/évente"]),
        ("Zárás &amp; Értékelés", ["Záróvizsgák szervezése, záró riportok",
                                   "Résztvevői elégedettségmérés",
                                   "Kiértékelő megbeszélés a HR osztállyal"]),
    ]
    items = "".join(
        f'<div class="item"><div class="n">{i:02d}</div><div><h3>{t}</h3>'
        + "".join(f'<div style="font-size:8.3pt;color:#4a4d63">• {e(x)}</div>' for x in xs)
        + "</div></div>"
        for i, (t, xs) in enumerate(roadmap, 1))
    return f"""
<div class="page"><div class="body">
  <h1 class="page-title">Hogyan támogatjuk a HR osztály munkáját?</h1>
  <p class="lead">Arra törekszünk, hogy a HR osztályt minél inkább tehermentesítsük a nyelvi
  képzések szervezése és adminisztrációja terén. {e(d['nevelo'].capitalize())} {e(d['ceg'])} {e(d['csapat'])} szint alapján
  szervezzük csoportokba, teljes adminisztrációval.</p>
  <h2>Szervezési roadmap</h2>
  <div class="numlist">{items}</div>
</div>{footer(7, 10)}</div>"""


def p8_digitalis(d):
    plat = [("Egyszerű használat", "Felhasználóbarát felület, amelyen a tanulók és a HR egyaránt "
                                   "könnyen navigálnak."),
            ("Papírmentes", "Digitális jelenléti ívek – csökkentett adminisztráció, "
                            "környezettudatos megoldás."),
            ("Azonnali adatok", "A jelenléti és elégedettségi adatokból automatikus riportokat "
                                "készítünk partnereinknek."),
            ("Biztonság", "Korszerű biztonsági megoldásokkal a személyes adatok és a képzési "
                          "információk védve vannak.")]
    cards = "".join(f'<div class="card"><h3>{e(t)}</h3><p>{e(b)}</p></div>' for t, b in plat)
    return f"""
<div class="page"><div class="body">
  <h1 class="page-title">Digitális eszközök és blended learning</h1>
  <p class="lead">Az IBC Nyelviskola együtt halad az üzleti világgal – modern digitális
  eszközökkel és online megoldásokkal támogatjuk a nyelvtanulást a hatékonyság maximalizálása
  érdekében.</p>
  <h2>Digitális tananyag</h2>
  <p>A legmodernebb, célzottan az online felnőttképzéshez fejlesztett nyelvkönyvsorozatok
  megfelelő szintjét biztosítjuk online órák esetén digitális formában. A digitális tananyag
  több, mint egy digitalizált tankönyv: hanganyagok, videók, tesztek és megoldásaik egy
  kattintásra, logikusan követik egymást. A digitális tananyag árát az óradíj nem tartalmazza,
  ára a nyomtatott tananyagoknál megszokott árkategóriában mozog.</p>
  <h2>Üzleti blended learning</h2>
  <p>A blended learning módszer ötvözi a személyes nyelvórákat a digitális tanulási
  lehetőségekkel. Kiváló kiegészítése a nyelvóráknak, önálló gyakorlásként, házi feladatként
  vagy órai munkaként is alkalmazható.</p>
  <ul class="dots" style="margin-top:3mm">
    <li>Munkahelyi nyelvre tervezve: kifejezetten üzleti és szaknyelvi leckék</li>
    <li>Online szintfelmérő több nyelven</li>
    <li>Nyelvtan: rövid, gyorsan feldolgozható összefoglalók</li>
  </ul>
  <h2>Online oktatási platform</h2>
  <div class="card-grid">{cards}</div>
</div>{footer(8, 10)}</div>"""


def p9_arazas(d, logo):
    tartalom = "".join(f"<li>{e(x)}</li>" for x in d["dij_tartalma"])
    return f"""
<div class="page">
  <div class="bar">Nyelvi képzés árajánlat {e(d['nevelo'])} {e(d['ceg'])} részére</div>
  <div class="body tight" style="padding-top:7mm">
    <div class="spec"><table>
      <tr><td class="k">NYELV:</td><td>{e(d['nyelv'])}</td></tr>
      <tr><td class="k">A KÉPZÉS CÉLJA:</td><td>{e(d['kepzes_celja'])}</td></tr>
      <tr><td class="k">OKTATÓK:</td><td>{e(d['oktatok'])}</td></tr>
      <tr><td class="k">HELYSZÍN:</td><td>{e(d['helyszin'])}</td></tr>
      <tr><td class="k">RÉSZTVEVŐK:</td><td>{e(d['resztvevok'])}</td></tr>
      <tr><td class="k">ÜTEMEZÉS:</td><td>{e(d['utemezes'])}</td></tr>
      <tr><td class="k">TERVEZETT INDULÁS:</td><td>{e(d['indulas'])}</td></tr>
    </table></div>

    <h2>Nyelvóra díjak</h2>
    {pricecard(d)}

    <div class="darkbox" style="text-align:center">
      <div class="t">Az árajánlat részeként díjmentes, 45 perces {e(d['bemutatoora_jelzo'])}bemutatóórát biztosítunk,</div>
      <div style="font-size:8.5pt">amely során közvetlen betekintést nyerhetnek oktatási
      módszereinkbe.</div>
    </div>

    <h2>A díj magában foglalja</h2>
    <ul class="dots">{tartalom}</ul>

    <div class="warmbox" style="margin-top:2.5mm">
      <b>Fizetés módja:</b> {e(d['fizetes'])}<br>
      <span style="color:var(--red);font-style:italic">Áraink {e(d['ervenyesseg'])}-ig
      érvényesek. A nyelvi képzések tárgyi adómentesek.</span>
    </div>
    
  </div>{footer(9, 10)}</div>"""


def p10_lepesek(d):
    return f"""
<div class="page"><div class="body">
  <h1 class="page-title">Következő lépések</h1>
  <p class="lead">Bízunk abban, hogy ajánlatunk felkeltette érdeklődését! Az IBC Nyelviskola
  készen áll arra, hogy {e(d['nevelo'])} {e(d['ceg'])} megbízható nyelvi partnere legyen.</p>
  <div class="card-grid">
    <div class="card"><h3>Kérjen díjmentes {e(d['bemutatoora_jelzo'])}bemutatóórát!</h3>
      <p>45 perces ingyenes bemutató, amelyen megismerheti oktatási módszereinket.</p></div>
    <div class="card"><h3>Találkozzunk online!</h3>
      <p>Egyeztessük személyesen az igényeket és lehetőségeket egy rövid megbeszélésen.</p></div>
  </div>
  <h2>Kapcsolat</h2>
  <div class="spec"><table>
    <tr><td class="k">IBC Nyelviskola</td><td></td></tr>
    <tr><td class="k">Telefon:</td><td>{KAPCSOLAT['telefon']}</td></tr>
    <tr><td class="k">E-mail:</td><td>{KAPCSOLAT['email']}</td></tr>
    <tr><td class="k">Web:</td><td>www.{KAPCSOLAT['web']}</td></tr>
    <tr><td class="k">Székhely:</td><td>{KAPCSOLAT['szekhely']}</td></tr>
    <tr><td class="k">Nyilvántartási szám:</td><td>{KAPCSOLAT['far']}</td></tr>
  </table></div>
  <p style="margin-top:6mm;color:var(--red);font-weight:700">IBC Nyelviskola – a vállalati
  nyelvoktatás szakértője</p>
  <p style="font-size:8pt;color:var(--gray)">Egyéb nyelvi megoldásaink: https://ibc-trening.hu/</p>
</div>{footer(10, 10)}</div>"""


def exec_summary(d, logo):
    stats = (stat("650+", "Kurzus") + stat("130+", "Oktató")
             + stat("15+", "Év tapasztalat") + stat("94%", "Elégedettség", green=True))
    svc = "".join(f'<div class="it"><b>{e(t)}</b><span>{e(s)}</span></div>'
                  for t, s in d["szolgaltatasok"])
    miert = "".join(f"<li>{e(x)}</li>" for x in d["miert_ibc"])
    # Csak egy sornyi referencia: a .page fix 297mm, a masodik pill-sor mar
    # kitolna a "Kovetkezo lepesek" dobozt a lapról. Az eredeti IBC sablon is
    # egy sort mutatott itt; a teljes lista a 10 oldalas ajanlat 2. oldalan van.
    refs = "".join(f'<div class="pill">{e(r)}</div>' for r in REFERENCIAK[:6])
    lepesek = " &nbsp; ".join(f"{i}. {e(x)}" for i, x in enumerate(d["kovetkezo_lepesek"], 1))
    return f"""
<div class="page">
  <div class="ex-head">
    <div class="blob"></div>
    <img class="logo-mark" src="{logo}" style="width:20mm;height:20mm">
    <div>
      <h1>Vezetői Összefoglaló</h1>
      <div class="s1">Nyelvi Képzés Árajánlat – {e(d['ceg'])}</div>
      <div class="s2">IBC Nyelviskola | {e(d['ev'])}</div>
    </div>
  </div>
  <div class="ex-body">
    <h2>Az IBC Nyelviskola</h2>
    <p style="font-size:8.7pt">{e(d['ibc_intro'])}</p>
    <div class="stats">{stats}</div>
    <h2>Szolgáltatásaink {e(d['nevelo'])} {e(d['ceg'])} számára</h2>
    <div class="svc">{svc}</div>
    <h2>Áraink</h2>
    {pricecard(d, compact=True)}
    <div class="note-i">Az ár tartalmazza: {e(d['ar_tartalmazza_rovid'])} &nbsp;|&nbsp;
    {e(d['utemezes'])} &nbsp;|&nbsp; Árak {e(d['ervenyesseg'])}-ig érvényesek.</div>
    <div class="darkbox">
      <div class="t">Miért az IBC {e(d['nevelo'])} {e(d['ceg'])} ideális partnere?</div>
      <ul class="checks" style="columns:2;column-gap:8mm">{miert}</ul>
    </div>
    <h2>Referenciáink</h2>
    <div class="pills">{refs}</div>
    <div class="warmbox" style="margin-top:5mm">
      <b style="color:var(--red)">Következő lépések</b><br>
      <span style="font-size:8.5pt">{lepesek}</span><br>
      <span style="font-style:italic;font-size:8pt;color:#6c7085">Készséggel állunk
      rendelkezésre személyes egyeztetésre!</span>
    </div>
  </div>
  <div class="footer"><span>{KAPCSOLAT['email']} &nbsp;|&nbsp; {KAPCSOLAT['telefon']}
  &nbsp;|&nbsp; {KAPCSOLAT['web']}</span><span>Vezetői Összefoglaló</span></div>
</div>"""


# --------------------------------------------------------------------------- futtatas

def render(pages, css):
    return ("<!doctype html><html lang=\"hu\"><head><meta charset=\"utf-8\">"
            f"<style>{css}</style></head><body>{''.join(pages)}</body></html>")


def to_pdf(html_path, pdf_path):
    # ABSZOLUT ut kell: a "file://<relativ ut>" URL-ben a Chrome az elso szegmenst
    # HOSZTNEVKENT ertelmezi (ERR_INVALID_URL), es a hibaoldalt nyomtatja ki PDF-be.
    # Az igy keletkezo fajl ~65 kB, tehat meretre HIHETONEK latszik -- ezert nemá a hiba.
    html_path = os.path.abspath(html_path)
    pdf_path = os.path.abspath(pdf_path)
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", f"file://{html_path}"],
                   capture_output=True, timeout=180)
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"a PDF nem keszult el: {pdf_path}")
    # A Chrome hibaoldala is ervenyes PDF, ezert a letezes NEM eleg bizonyitek.
    with open(pdf_path, "rb") as fh:
        nyers = fh.read()
    for jel in (b"ERR_INVALID_URL", b"ERR_FILE_NOT_FOUND", b"site can", b"nem \xc3\xa9rhet\xc5\x91 el"):
        if jel in nyers:
            raise RuntimeError(
                f"a Chrome HIBAOLDALT nyomtatott PDF-be: {pdf_path} -- "
                f"ellenorizd a forras utvonalat: {html_path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    data = apply_defaults(json.load(open(sys.argv[1])))
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    os.makedirs(outdir, exist_ok=True)

    css = open(os.path.join(HERE, "stilus.css")).read()
    logo = logo_data_uri()
    kod = data["cegkod"]

    ajanlat = render([p1_borito(data, logo), p2_bemutatkozas(data), p3_modszertan(data),
                      p4_portfolio(data), p5_minoseg(data), p6_meres(data), p7_hr(data),
                      p8_digitalis(data), p9_arazas(data, logo), p10_lepesek(data)], css)
    osszefoglalo = render([exec_summary(data, logo)], css)

    for name, doc in (("IBC_Arajanlat_" + kod, ajanlat),
                      ("IBC_Executive_Summary_" + kod, osszefoglalo)):
        html_path = os.path.join(outdir, name + ".html")
        pdf_path = os.path.join(outdir, name + ".pdf")
        with open(html_path, "w") as fh:
            fh.write(doc)
        to_pdf(html_path, pdf_path)
        print(f"kesz: {pdf_path} ({os.path.getsize(pdf_path) // 1024} kB)")


if __name__ == "__main__":
    main()
