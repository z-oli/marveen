---
name: fleet-helper
description: Shared, dependency-free Python helpers for the agent fleet - dashboard API (memory, messages, kanban), Telegram MarkdownV2 escaping, and rule-based Mail.app triage. Use to do deterministic work (fetch/filter/SQL/format/escape) in Python instead of burning model tokens doing it in the LLM turn. The dashboard token is read from store/.dashboard-token at call time, never hardcoded.
---

# fleet-helper

Move deterministic work (fetch / filter / SQL / format / escape) out of the model
and into Python, so heartbeats and scheduled tasks stop spending tokens
re-deriving the same plumbing each cycle. Python 3 stdlib only, no pip deps.

No secrets or personal data are baked in: the dashboard token is read from
`store/.dashboard-token` at call time, the project root comes from `CLAW_DIR`
(or is auto-detected), and any personal sender/keyword lists live in a gitignored
`mail_rules.json` (see `scripts/mail_rules.example.json`).

## When to use
- Saving/searching memory, posting daily-log, sending inter-agent messages.
  **This is the most-skipped one, and it is measurable. On 2026-08-28 a single night's
  scratchpad held 146 throwaway scripts, and 74 of them hand-rolled the same
  `urllib.request.Request` POST to `/api/memories` or `/api/daily-log` -- token read,
  headers, json.dumps, all rebuilt from scratch each time. `fleet.py mem-save` and
  `fleet.py daily-log` already do exactly that (see `main()` dispatch). Nobody decided
  to skip the helper; it simply was not the first thing that came to mind, seventy-four
  times in a row. If you are about to write a POST to a dashboard endpoint by hand,
  that is the signal: use the helper instead.**
- Reading kanban (due today / stuck / by status) without writing SQL by hand.
- Escaping text for a Telegram MarkdownV2 message.
- An email heartbeat: pre-filter unread mail to a compact JSON before the model
  reasons about it.
- Building a token-cheap heartbeat gate (see "The heartbeat gate pattern" below).

## Scripts
- `scripts/fleet.py` - dashboard API + kanban read helpers + MarkdownV2 escaper
  (CLI and importable module).
  - **KET escaper van, es a rossz valasztas nemitja a formazast (2026-08-28-i meres).**
    `mdv2` MINDENT escapel, a `*`-ot IS: az `*felkover*` markereidbol `\*felkover\*`
    lesz, tehat sima szoveg. Ez akkor helyes, ha PROGRAMBOL rakod ossze az uzenetet
    (escapeled a dinamikus reszt, aztan te teszed ra a `*`-ot). KEZZEL IRT hosszu
    uzenethez (reggeli napindito) `mdv2b` kell: az a `*`-ot meghagyja, minden mast
    escapel, ES kuldes elott lefuttatja az `outgoing_gate_check`-et (em dash,
    ` -- `, paratlan csillag). Ha talal valamit, exit 2 es NEM ad kimenetet.
- `scripts/mail_triage.py` - rule-based unread Mail.app filter (macOS), JSON out,
  never sends and never marks read.
- `scripts/gate_example.py` - reference heartbeat gate; its shell invocation IS
  the mandatory keep-alive tool call (the LLM turn is not skipped, just cheap).
- `scripts/mail_rules.example.json` - copy to `mail_rules.json` (gitignored) with
  your real senders/keywords.
- `scripts/README.md` - full usage and the heartbeat gate pattern write-up.

## Quick start
```bash
P=seed-skills/fleet-helper/scripts
python3 $P/fleet.py mdv2 "Tomorrow (8:00) - report!"   # escaped MarkdownV2 (kills *bold*)
cat brief.txt | python3 $P/fleet.py mdv2b            # keeps *bold*, refuses em dash / " -- "
python3 $P/fleet.py gate-check "$(cat uzenet.txt)"  # kapu-szimulacio KULDES ELOTT
python3 $P/fleet.py kanban-due
python3 $P/mail_triage.py 90                            # unread <= 90 min -> JSON
```

KET BUKTATO A PATH-BAN ES A KAPCSOLOKBAN, MINDKETTO MERVE 2026-08-30-an:

*** 1. A SCRIPTS NINCS A TELEPITETT SKILL ALATT. *** A `~/.claude/skills/fleet-helper/`
mappaban CSAK a SKILL.md van, `scripts/` alkonyvtar NINCS. A megszokott reflex
(`~/.claude/skills/<nev>/scripts/...`) `No such file or directory`-vel elszall, es
konnyu masodszor is ugyanoda nyulni. A futtathato kod a REPOBAN el:
`/Users/zoli/marveen/seed-skills/fleet-helper/scripts/fleet.py` -- ezt hasznald abszolut
uton, vagy a fenti `P=` relativ alakot a repo gyokerebol.

*** 2. ISMERETLEN KAPCSOLOT A CLI NEM UTASIT VISSZA, HANEM ESCAPE-EL. *** A `mdv2`
a szoveget POZICIOS argumentumkent vagy STDIN-rol varja, `--file`-t NEM ismer. Ha megis
odaadod, nem kapsz hibat: a `--file` sztringet escape-eli, es kiirja, hogy `\-\-file`.
Egy hosszu napinditonal ez azt jelenti, hogy a kimenet ROVID es ERTELMETLEN, de sikeresnek
latszik. Fajlbol igy megy: `python3 $P/fleet.py mdv2 < uzenet.txt`, vagy a « »-jeloloknel
ugyis python-bol importalod (`from fleet import escape_mdv2`).

*** 3. A MEM-SAVE TARTALMA NE MENJEN IDEZETT SHELL-ARGUMENTUMBAN, MERT A BACKTICK
LEFUT. (2026-09-07) *** Aznap egy emleket igy mentettem: a tartalmat dupla idezojelbe tett
argumentumkent adtam at, es benne backtick koze zart modell-nevek voltak. A dupla
idezojelen BELUL a backtick PARANCSHELYETTESITES: a shell megprobalta LEFUTTATNI oket,
kiirta, hogy "command not found: qwen2.5:14b", a helyukre URES sztringet tett, es az igy
MEGCSONKITOTT szoveget kuldte el. A szerver 400-zal el is utasitotta
("Content rejected by security filter"), tehat az emlek EL SEM MENTODOTT.

*** ES A VESZELYES RESZE NEM A 400 VOLT, HANEM AZ, HOGY EGY MASIK NAPON ATMEHETETT VOLNA. ***
Ha a szovegben nincs olyan backtick-tartalom, amitol a filter felkap, akkor a parancs
SIKERT ir, es egy CSENDBEN MEGCSONKITOTT emlek kerul a memoriaba, amirol egy kesobbi
session azt hiszi, hogy teljes. Ugyanaz a hiba-csalad, mint az inter-agent kuldesnel
(CLAUDE.md): a shell nemán csonkit, es a muvelet attol meg sikeresnek latszik.

A SZABALY: barmilyen TOBB SOROS vagy formazott tartalom (emlek, napi naplo, kanban komment,
approval-leiras) FAJLBOL menjen, es a JSON-t python epitse, ne a shell. A tartalom-fajlt
IDEZETT heredoc-kal ird ki:

    cat > /tmp/mem.txt <<'VEGE'
    ... a tartalom: backtick, idezojel, dollar, barmi ...
    VEGE

*** AZ APOSZTROF A LENYEG: *** az idezett heredoc (<<'VEGE') se valtozot, se backticket
NEM helyettesit. Aposztrof nelkul (<<VEGE) ugyanaz a csapda, csak fajlbol.
Utana a POST-ot python epitse: json.dumps a fajl tartalmabol, urllib.request-tel kuldve.

*** ES A KIMENETET NEZD MEG: a 200-as statusz ES a visszakapott id a bizonyitek. Ha nincs
id, nem mentodott el. *** Ugyanaz az elv, mint az agent-msg.sh-nal a CLAUDE.md-ben.

*** ES HA MAR MEGTORTENT: A CSONKITAS-KERESO IS MEROESZKOZ, ES MINDKET IRANYBAN HAZUDIK. ***
A mechanizmus beirasa nem eleg, vissza kell menni a MAR MEGIRT adatra is -- de a keresest
NE hidd el elsore. Nalam a "nem-sortoreses dupla szokoz" minta 3 talalatot adott 14
emleken, ebbol EGY volt valodi csonkitas; a masik ketto tablazat-igazitas es szandekos
behuzas. Kriptonitnal az "ures zarojel" minta 12 HAMIS POZITIVOT adott 71 emleken, mert a
FUGGVENYNEVEKRE illeszkedett (diff(), arany.py) -- ha elhiszi, a csonkitas-kereso rongalta
volna meg pont azt, amit ved.
A SZABALY: minden talalatot OLVASS EL, mielott hozzanyulsz; es a javitas elott gondold vegig,
mi VESZETT EL (nalam egy parancsnev egy bizonyitek-sorbol, a szabaly szovege ep volt).
ES EGY ELEGANS ELLENPROBA KRIPTONITTOL: ha egy emlekben MEGVAN a backtick, az a jo hir --
ha a shell lefuttatta volna, eltunt volna. Itt a jel JELENLETE bizonyit.

*** ES AMIERT O NEM FUTOTT BELE: NEM OVATOSABB VOLT, HANEM MAS UTAT HASZNALT. *** Mindent
aposztrofos python-heredocbol mentett, ami nem interpolal, tehat a shell bele sem futhatott.
A vedelmet az UT adta, nem a figyelem -- vagyis aki atall a rovidebb, idezett-argumentumos
helper-alakra, az ugyanugy belefut, barmilyen gondos.


## A `mem-save` argumentum-sorrendje: agent CONTENT category keywords

Ha a category-t teszed masodiknak, a szerver 400-at ad, es a hibauzenetben a TELJES
memoria-szoveged all `Invalid category "<az egesz bekezdesed>"` alakban. Merve
2026-08-29-en, elsore. A dispatch a `main()`-ben:
`save_memory(rest[0], rest[1], rest[2] or "warm", rest[3] or "")` -- a category es a
keywords opcionalis, a CONTENT nem. Ugyanez az alak a `daily-log`-nal: `agent CONTENT`.

```bash
P=seed-skills/fleet-helper/scripts
python3 $P/fleet.py mem-save marveen "a memoria szovege" cold "kulcsszavak"
python3 $P/fleet.py daily-log marveen "## 02:30 -- mi tortent"
```

*** ES A SZOVEGET NE IDEZETT ARGUMENTUMKENT ADD AT, HA BARMI KULONLEGES KARAKTER VAN BENNE
(2026-09-01, sajat mulasztas). *** A ketto koze zart szovegben a VISSZAPERJELES IDEZOJEL
parancs-behelyettesites: a shell lefuttatja, ami benne all. Aznap ket kapcsolonev volt igy
jelolve egy tanulsag-emlekben; a shell "command not found"-ot irt rajuk, es a mentett szovegbol
NYOMTALANUL kimaradtak. **Az API valasza {"ok":true} volt, az emlek letrejott, a hossza hiheto**
-- vagyis a hiba NEMA. Ugyanaz az alak, mint amire a CLAUDE.md az agent-msg.sh-nal figyelmeztet,
csak itt a memoria-szovegen. Ugyanez all a $-ra, a !-re es a backslashre.

**A BIZTOS ALAK: a tartalom FAJLBOL jon, es a hivas python-bol megy** -- ugyanaz az elv, mint a
CLAUDE.md-ben az approval-leirasnal. Heredoc-ba ird a szoveget, majd `open(...).read()` a JSON-be,
es POST a /api/memories vegpontra. Ha a python-hivast is heredocbol inditod, a KET heredoc
hatarolója NE legyen ugyanaz (a belso lezarna a kulsot) -- ez elsore elszallt 2026-09-01-en.

**ES MENTES UTAN OLVASD VISSZA** (`GET /api/memories?...&q=<egy egyedi darab>`), es keress ra egy
olyan reszletre, ami a veszelyes karakter KORNYEKEN all. A hossz onmagaban nem bizonyitek: egy
kimaradt kapcsolonev par karakter, a szoveg tole meg teljesnek latszik.

*** ES EGY FIGYELMEZTETES ERROL A FAJLROL MAGAROL (2026-08-29): ez a PELDANY (az eles,
~/.claude/skills/ alatt) ELTER a repoban levo seed-skills/fleet-helper/SKILL.md-tol --
16648 vs 7306 bajt, es a kettonek kulon horgonyai vannak. Az eles a NAGYOBB es a
REGEBBI, a seed a KISEBB es az UJABB. Ha barmit irsz az egyikbe, nezd meg, kell-e a
masikba is: egy patch csendben csak az egyikben landolhat. ***
## KULDES ELOTT: gate-check, ne fejbol (2026-08-23 ota)

A harom kimeno kapu (gondolatjel, ekezet nelkuli toldalek, sema-val kezdodo webcim)
kulon-kulon dokumentalva van lentebb, DE 2026-08-22-en egyetlen nap alatt OTSZOR
akadtam el rajtuk, mert a szabalyt csak a blokkolas UTAN olvastam el. A tudas
szovegkent keveset er, ezert most szkript is van ra:

```bash
python3 $P/fleet.py gate-check "$(cat uzenet.txt)"   # exit 0 = mehet, exit 1 = talalat
```

Amit visszaad: minden talalatnal a fajta, a konkret szo vagy cim, a KORNYEZETE
(hogy lasd, hol van), es a javitasi javaslat. A MarkdownV2 escape-eket eloszor
feloldja, pont ahogy a kapu is teszi, tehat a mar escape-elt szoveget is meg lehet
vele nezni. Nem helyettesiti a kaput, csak eloreveti, mit fog mondani.

Egy hosszu napindito eseten ez egy parancs, es megsporol ket-harom korbe-fordulast.

**Az ekezet-szotar SZUK legyen, nem bo. Ezt az elso eles futas tanitotta meg
(2026-08-23, harom perccel a napindito elott).** Az elso valtozatba beraktam az
`el`, `ok`, `kor`, `erre` alakot is, es a szkript rogton OT talalatot adott a
napinditora, amibol MIND AZ OT hamis volt: ezek teljesen szabalyos magyar szavak
(igekoto, fonev, fonev, hatarozo). Egy hamis riasztasokat ado ellenorzo ROSSZABB
a semminel, mert par kor utan atugrom a kimenetet, es akkor az igazi talalat is
velük vesz. Ezert a szotarba CSAK olyan alak kerulhet, ami onallo szokent szinte
sosem helyes: `es`, `ot`, `ora`, `ev`, `ut`, `szo`.

Ha bovited: elotte futtasd le a szkriptet ket-harom REGI, mar kikuldott uzenetre.
Ha azokon talalatot ad, a bovites rossz, mert azok atmentek a valodi kapun.
Es forditva, szukites utan futtasd le a KORABBAN elakadt szovegre is, hogy lasd,
nem vesztetted-e el a hasznat.

**A GATE-CHECK SZOTARA SZUKEBB, MINT A VALODI KAPUE (2026-08-24).** A `gate-check`
"OK: mehet"-et adott egy heti biztonsagi jelentesre, a valodi kimeno kapu viszont
BLOKKOLTA: `HIANYZO EKEZETEK, 1 szo: level -> level`. Az angol `level` szot a kapu
magyar `level`-nek (mint posta) latja, es ez a szo a gate-check szotarabol hianyzik.
KOVETKEZMENY: a gate-check zold jelzese NEM garancia, csak eloszures. Ha a valodi kapu
megis blokkol, NE bovitsd emiatt a gate-check szotarat kapkodva -- a helyes valasz az
ATFOGALMAZAS magyarra (`level 1` -> `a legalacsonyabb szinten`, `level 3` -> `a harmadikon`),
mert a kapu szandeka jo: magyar szovegbe angol szakszo ekezet-hibanak latszik.
ALTALANOS SZABALY: angol szakszo magyar mondatban a kimeno uzenetben kerulendo, mert a
kapu nem tudja, hogy szakszo. A kodrol/technikai reszrol beszelj magyarul, vagy tedd
backtick koze -- ha mindenkeppen kell, futtasd le ra a `gate_check`-et A TELJES, KESZ
SZOVEGGEL (a rovid proba VAK, lasd ket bekezdessel lentebb).
*** ES NEM CSAK A SZAKSZO AKAD BE: AZ IDEZETT ANGOL MENUPONT IS (2026-09-10). *** A
Discord adatexport utjat irtam le szo szerint (`Request all of my Data`), es a kapu az
`all`-t magyar `all` -> `all`-nak vette: `HIANYZO EKEZETEK, 1 szo: all -> all`. A teljes
uzenet visszapattant EGYETLEN angol szo miatt, ami ott meg csak egy gomb neve volt.
Ez a MASODIK ilyen alak (az elso a `level`), es a kozos vonasuk, hogy egyik sem a sajat
fogalmazasom volt, hanem BEMASOLT idegen szoveg: gepi level-targy, menupont, gombfelirat.
**A MEGOLDAS UGYANAZ, ES GYORS: ne idezd, hanem MONDD EL MAGYARUL, hova kell kattintani**
(`a beallitasokban, az adatvedelmi resznel tudod kerni a teljes adatkiadast`). A gazdanak
igy is egyertelmu, es nem kell a szotarhoz nyulni. *** AMIT NE CSINALJ: a szotarbol kivenni
az `all`-t. Az egy gyakori magyar szo; egy hianyzo ekezet miatt kimeno uzenetben pont az
lenne kinos. *** Ha egy idegen nyelvu idezet MINDENKEPP kell (pl. hibauzenet szo szerint),
tedd backtick koze, es futtasd le ra a `gate_check`-et A TELJES, KESZ SZOVEGGEL.
*** ES EPP EZERT: A PROBAT A TELJES SZOVEGGEL FUTTASD, NE ROVID MINTAVAL (2026-09-10, Kriptonit
merese). *** Az ekezet-ag az eles kapuban NYELVI KAPU alatt van (`is_hungarian`, harom
magyar marker kell): rovid szovegre ez False, tehat az ellenorzes EL SEM INDUL, es a proba
"ATENGEDI"-t ir. Negy egymas utani rovid teszt adott igy hamis OK-ot, majd a HOSSZU, eles
uzenet ugyanazzal a mondattal elbukott. A rovid proba tehat nem enyhebb, hanem VAK.

**ES A `gate_check` ZOLD JELZESE 2026-09-10 ELOTT 4 SZAZALEKOS FEDEST JELENTETT.** A helper
sajat szolistaja hat par volt, az eles kapue 160 -- hianyzott belole az `all`, `ar`, `cim`,
`dontes`, `eleg`, `allapot`. Ezen felul a helper mintaja csak 2-4 betus szot nezett, tehat a
hosszabb bejegyzeseket a teljes lista birtokaban sem fogta volna meg: ket hiba egymas mogott,
es a felso elrejtette az alsot. *** JAVITVA: a `gate_check` mostantol nem MASOLJA a kaput,
hanem BETOLTI es az O pipeline-jat hivja (strip_technical -> accent_check_tokens ->
ACCENTLESS + AMBIGUOUS_TRIGGER + is_hungarian), tehat a kotojel-kivetelek es a nagybetu-
szabaly is automatikusan stimmel. *** Ha a kaput nem talalja (nincs `CLAUDE_PROJECT_DIR`,
mas munkakonyvtar), visszaesik a hat parra, DE kiir egy `figyelmeztetes` talalatot -- ha azt
latod a kimenetben, a "nincs talalat" NEM jelent atmenest. **A TANULSAG A SZOLISTAN TULRA:
ket kezzel szinkronban tartott masolat definicio szerint szetcsuszik; ha egy ellenorzo egy
masik ellenorzot utanoz, ne masolj adatot, hivd meg az eredetit.**

**SZAMMAL IRT IDOPONT/EVSZAM UTAN A `-es` TOLDALEK BEAKAD (2026-08-23).** A gate-check
a `16:07-es`, `08-17-es` alakokra `ekezet`-talalatot ad, mert a kotojel utani `es`
onallo szonak latszik. Csak a SZOTARBAN LEVO toldalek akad be (`es`, `ot`, `ora`, `ev`,
`ut`, `szo`): a `2026-os`, `5-os` atmegy, mert az `os` nincs a szotarban. NE bovitsd
emiatt a szotarat kivetellel: a kapu ugyanezt a tokenizalast hasznalja, tehat a valodi
kuldes is elakadhat rajta. A gyors es biztos megoldas az ATFOGALMAZAS:
`a 16:07-kor tortent ujraindulas`, `a 08-17-i checklista`. Egy szo, es a talalat eltunik.

## Felkover szoveg ES escape egyszerre (a napinditonal ez a buktato)

A `mdv2` escaper MINDENT escape-el, tehat a formazasnak szant `*` karaktert is --
igy a felkover szoveg elveszik. Hosszu, formazott uzenetnel (reggeli napindito) ez a
mukodo minta: ird a szoveget sajat jelolovel, escape-elj, majd csereld vissza.

```python
ESC = r'_*[]()~`>#+-=|{}.!'
escape = lambda s: "".join("\\"+c if c in ESC else c for c in s)
szoveg = "🌅 «Napindito» ... 9:00-kor (fontos)!"     # a « » a felkover jelolo
ki = escape(szoveg).replace("«","*").replace("»","*")
```

Miert szamit: a MarkdownV2-ben EGYETLEN elrontott karakter miatt a Telegram a TELJES
uzenetet visszautasitja, nem csak a formazast veszti el. Kezzel escape-elni egy
2000 karakteres napinditot nem realis -- ezt mindig szkript csinalja, es a kuldes
elott nezd meg a kimenetet.



## Harmadik kapu a küldés előtt: a magyar toldalék hamis riasztást szül

A Telegram-válaszra egy PreToolUse kapu (`outgoing-copy-gate`) is ráfut, amelyik ékezet
nélküli magyar szavakat keres. Ez jó szabály, de **szó-határon illeszt, ezért a számhoz
vagy idegen szóhoz kötött toldalékot önálló szónak nézi**, és megtagadja a küldést:

| Amit írtál | Amit a kapu lát | Amit javasol |
|---|---|---|
| `a repo scope-ot` | `ot` | `öt` |
| `a 47 647 221-es összeg` | `es` | `és` |

Mindkettő helyes magyarul, a kapu mégis blokkol. 2026-08-21-én egyetlen délutánon kétszer
fordult elő, két különböző üzenetben.


**DE ELŐBB: a találat NEM feltétlenül hamis. 2026-08-25-én kilenc valódi volt.**
A reggeli napindítót először végig ékezet nélkül fogalmaztam meg, mert a belső munkám
(memóriák, skill-szövegek, commit-üzenetek) ékezet nélküli, és ez észrevétlenül átszivárgott
a Zolinak szóló üzenetbe. A `gate_check` kilenc `es` találatot adott, és mind a kilenc
JOGOS volt: az üzenet magyarul olvashatatlanul nézett volna ki.
Ezért a sorrend: **először nézd meg, valóban hiányzik-e az ékezet** (ilyenkor a javítás az
ékezet pótlása, nem a szerkezet), és csak utána gondolj a toldalék-hamis-pozitívra.
A gyors megkülönböztetés: ha a talált szó ÖNÁLLÓAN áll a mondatban (`es`, `ot`), valódi
hiba; ha kötőjel vagy szám tapad elé (`3.9-es`, `08-17-es`), hamis pozitív.
Aznap a kilenc valódi találat után maradt EGY hamis (`3.9-es`), azt átfogalmazással
oldottam meg (`a 3.9-en fut`), és csak a harmadik kör lett GATE OK.

**A javítás nem az ékezet, hanem a szerkezet:** fogalmazd át úgy, hogy a toldalék eltűnjön.
`scope-ot` helyett `jogosultságot`, `221-es összeg` helyett `221 forintos összeg`.

**Ugyanez a kapu a GONDOLATJELRE is ráfut, és a napindító ezen szokott elbukni.**
A szekciócím utáni em dash (`—`, U+2014) a legkézenfekvőbb tagolás egy hosszú,
formázott üzenetben, viszont álló tiltás alatt van, tehát az EGÉSZ üzenet visszapattan.
2026-08-22-én a napindító első próbálkozása 12 gondolatjel miatt akadt el. A csere
egyszerű, csak előre kell rá gondolni: `*Cím* — szöveg` helyett `*Cím*: szöveg`,
felsorolásnál pedig `*Cím*. Szöveg`. Küldés előtt ez az egy sor megfogja:
```bash
grep -c '—' <a kesz uzenet>    # 0 = mehet
```
Ugyanaz a tartalom, csak nincs mibe beleakadnia.

Ha nem találod, melyik szón akadt fenn, ne találgass, keresd meg:

```python
import re
for m in re.finditer(r'\bes\b|\bot\b', szoveg):
    print(repr(szoveg[max(0, m.start()-40):m.end()+40]))
```

A kapu a Bash-parancsokra is ráfut, tehát ugyanez a csapda vár, ha memóriát vagy naplót
mentesz ilyen toldalékkal.

## TOBBSOROS SHELL-PARANCS A CSATORNAN SZETESIK (2026-09-04)

Ha Zolinak kuldesz parancsot, amit O futtat a sajat termnaljaban, EGY SORBAN kuldd.
A backslash-folytatasos, "szep" alak masolaskor elveszti a sortoro backslasheket, es a
zsh MINDEN sort kulon parancsnak veszi. Ez jott vissza:

```
yt-dlp: error: You must provide at least one URL.
zsh: command not found: --cookies
zsh: command not found: --skip-download
zsh: no such file or directory: https://www.youtube.com/watch?v=...
```

*** NEM HIBAUZENET-SZERUEN NEZ KI ELSORE: *** az elso sor a yt-dlp sajat panasza, tehat
ugy tunik, mintha a PARANCS lenne rossz, pedig a szallitas romlott el. Az arulkodo jel a
`command not found: --<kapcsolo>`: a shell egy kapcsolot probal parancskent futtatni.

A javitas egyetlen sor, es elsore lefut. Egy hosszu parancs Telegramon ronda, de mukodik;
a tordelt szep sose jut el hasznalhatoan. Ugyanez all a tobbsoros heredocra is.

## A kimeno kapu a PARANCS SZOVEGET is nezi, nem csak a cel-cimet

A v1.33.0 ota az `outbound-data-gate` a teljes Bash-parancsot atvizsgalja. Ket dolog egyutt
eleg a blokkolashoz: egy irasnak latszo curl-hivas ES egy teljes, sema-val kezdodo webcim
BARHOL a parancsban. Mindegy, hogy a cel a sajat localhost, es az is mindegy, hogy a cim
csak egy heredoc-ban, dokumentacio-szovegkent szerepel.

2026-08-21-en ez ketszer is megfogott egymas utan:
1. Egy memoria-mentes, mert a MENTENDO SZOVEG idezett egy git-remote cimet.
2. Rogton utana az a parancs, amivel EZT a buktatot akartam leirni, mert a leiras maga
   tartalmazta a peldat.

**Szabaly: memoriaba, napi naploba es skill-szovegbe sema nelkul irj cimet** (pl.
`github.com/X/y`, nem a teljes alak), es ne idezz irasnak latszo curl-mintat sem.
Az informacio ugyanannyi, a kapu meg nem akad meg rajta. Ha tenyleg teljes cim kell,
az a gazda dontese az egress-allowlist fajlban, nem a tied.
**Es van egy eset, ahol a fenti megoldas NEM hasznalhato: amikor a cim-szeru sztring
maga a FUNKCIO, nem dekoracio.** Az OAuth scope-nevek egy resze bare host URL
(a teljes Gmail-hozzaferes scope-ja pontosan ilyen). Azt nem lehet sema nelkul irni,
mert akkor mar nem az a scope. 2026-08-22-en ez ketszer fogott meg: eloszor a
szolgaltatasfiok scope-probajat allitotta meg (a scope a JWT-torzsben volt), masodszor
a napi naplo bejegyzeset, amiben csak EMLITETTEM a scope nevet.

Ilyenkor a sorrend:
1. **Probaban**: hagyd ki azt az egy scope-ot, es merd a tobbit. Egy hianyzo adatpont
   kevesbe rossz, mint a leallt meres. Utana ird le, melyiket nem tudtad merni.
2. **Prozaban** (napi naplo, memoria, skill): nevezd meg korulirva ("a teljes Gmail
   hozzaferes scope-ja"), ne masold be. Az olvaso ugyanugy erti.
3. Allowlist-bovitest NE javasolj emiatt: egy meresi kenyelmetlenseg nem indok arra,
   hogy egy cim tartosan atengedett legyen.

## Escape UTAN meg egy lepes: gondolatjel-szures

A CLAUDE.md kimondja, hogy gondolatjel (em dash) SOHA nem mehet ki. Az escaper ezt nem
fogja meg, mert a `—` nem MarkdownV2 spec-karakter: atmegy rajta epen, es a kimenet
technikailag hibatlan lesz. A csapda az, hogy a gondolatjel pont a SZEKCIOCIMEKBE csuszik
be eszrevetlenul ("Napindito — 2026...", "Email — utolso 12 ora"), mert ott termeszetesnek
erzodik. 2026-08-20-an negy szekciocimben bennmaradt volna, mar escape-elve.

Ezert a kuldes elotti ellenorzes KET dolgot nez, nem egyet:

```bash
python3 napindito.py | grep -c '—'    # 0-nak kell lennie, kulonben javitsd a forrast
```

A javitas nem a `—` torlese, hanem vesszo vagy ketpont a helyere: "Napindito, 2026...",
"Email, utolso 12 ora". A mondat kozepen levo gondolatjelet mondattá kell bontani.

**Ez MINDEN formazo karakterre igaz, nem csak a felkoverre.** Ha kod-formazast akarsz,
a backtick ugyanugy escape-elodik (`\``), es a Telegramban LITERALIS backtickkent
jelenik meg, nem kodkent -- a formazas nemán elveszik, az uzenet meg kimegy, tehat
semmi nem szol. 2026-08-19-en a napinditoban igy jott volna ki egy skill neve.
Megoldas: minden formazashoz SAJAT jelolopar kell (pl. « » a felkovernek, ‹ › a kodnak),
es a csere utan mindegyiket vissza kell alakitani. **Vagy -- es hosszu uzenetnel ez az
egyszerubb -- ne hasznalj kod-formazast a csatornan**, a nev sima szovegkent is olvashato.
Kuldes elott NEZD MEG a generalt szoveget: az escape-elt formazo karakterek ott latszanak.

## The heartbeat gate pattern (the high-value idea)
Frequent heartbeats often wake the model just to run deterministic checks and
then stay silent - wasted tokens. Naively skipping the turn can be unsafe if your
channel transport (e.g. a Telegram MCP over a stdio pipe) relies on a periodic
local tool call to stay connected. The safe pattern: keep the turn but make it
cheap - the heartbeat's first action runs a `gate.py` via the shell (that one
Bash call IS the keep-alive), the gate does the deterministic checks and prints a
`has_signal` flag; on `false` the model writes one line and stops, on `true` it
only does the judgment + notification. Zero scheduler/runner changes. See
`scripts/README.md` for the full rationale and two hard-won scheduling lessons
(avoid cron collisions with other heartbeats; `skipIfBusy` trade-off).

## A naptar VISSZAMENOLEG is kereshetо (2026-08-19)

A `scripts/naptar-ma.py` NEM csak a mai napot tudja: **elfogad egy ISO-datumot elso
argumentumkent** (`python3 scripts/naptar-ma.py 2026-08-07`). Ez sehol nincs
dokumentalva, se `--help`, se `argparse`, csak a forraskodbol derul ki
(`nap = args[0] if args else date.today().isoformat()`). Egy rovid ciklussal igy
kereshetsz visszamenoleg:

```python
for i in range(45):
    d = (date.today() - timedelta(days=i)).isoformat()
    out = subprocess.run(['python3','scripts/naptar-ma.py',d],
                         capture_output=True,text=True,timeout=30).stdout
    # ... szurd a kulcsszora
```

**Miert szamit:** a gazda kerdesei gyakran hivatkoznak a sajat nyilvantartasaira
("naptarban is latod"), es ilyenkor a KONKRET DATUM tobbet er, mint barmilyen altalanos
valasz. 2026-08-19-en egy egeszsegugyi kerdesnel ez volt a leghasznosabb resz: kiderult,
hogy a gyanusitott kezelesbol EGYETLEN alkalom volt, 12 nappal korabban, amivel a homalyos
gyanu ellenorizheto idorendi kerdesse valt ("a panasz elotte vagy utana kezdodott?").
**Ha a kerdes a gazda sajat adataira utal, eloszor NEZD MEG, csak utana valaszolj.**
Ugyanez all a memoriara es a kanbanra is.

Egy buktato: a szinkronizalt naptarak miatt UGYANAZ az esemeny tobbszor is megjelenhet
(nekem haromszor jott ugyanaz a 15:30-as bejegyzes). Ne szamold tobbszor.

**A NAGYOBB BUKTATO: NE SZURJ KULCSSZORA, DUMPOLD KI AZ EGESZET.** Ugyanaz az ismetlodo
esemeny a gazda naptaraban KET-HAROM KULONBOZO NEVEN is szerepelhet: markanev, koznyelvi
nev, becenev. 2026-08-19-en ugyanaz a kezeles egyszer "Fekve Fogyas", negyszer
"Zsirleszivas" neven volt elmentve. A `fekve|fogy|elektr|ems` kulcsszavakkal EGY talalatot
kaptam OT helyett, es magabiztosan azt valaszoltam, hogy "egyetlen alkalom volt, 12 napja".
A gazda javitott ki. Ez HAMIS NEGATIV: nem hibauzenetet ad, hanem egy hihetobb, de rossz
valaszt.
**Ezert: 60-90 napos ablaknal ne szurj, hanem ird ki MINDEN esemenyt, es olvasd vegig.**
Napi par bejegyzes, tehat par szaz sor: olcso, es megszunteti a teljes hibaosztályt.
Kulcsszavas szures csak akkor, ha a nevet a gazda MAGA mondta meg, szo szerint.
Ha megis szursz es keveset talalsz, a "keves talalat" NE megerositesként hasson: eloszor
nezz ra a nyers listara.

**A HARMADIK CSAPDA: a naptarbejegyzes azt mondja meg, MI es MIKOR, azt NEM, hogy KINEK.**
A gazda naptaraban ott vannak a csaladtagok, a gyerekek, sot az allatok idopontjai is,
ugyanolyan formaban, mint a sajatjai. 2026-08-19-en az "Infuzio" bejegyzesbol azt
kovetkeztettem, hogy a gazda orvosnal lesz delutan, es epp ezt ajanlottam neki a sajat
panaszara. Kiderult, hogy a MACSKAJAT viszi. Ugyanezen a listan szerepelt "Peti fogorvos
kontroll" is, ami szinten nem o. **Ha egy bejegyzesbol a gazdara vonatkozo kovetkeztetest
vonnal le, eloszor kerdezd meg, kie** -- vagy fogalmazz felteteles modban. A cim tobbnyire
nem arulja el a szemelyt, es a tevedes itt nem latszik hibanak, mert a mondat maga
tokeletesen ertelmes.

## Pitfalls (a repo-beli seed-bol athozva, 2026-08-30)

EZ A SZEKCIO 2026-08-30-IG CSAK A REPO-BELI PELDANYBAN LETEZETT (`seed-skills/fleet-helper/SKILL.md`), az ELESBEN nem -- es a skill-kent betoltodo peldany az ELES. Ennek ma mert ara volt: 16:15-kor pontosan abba a csapdaba estem, ami az elso pont alatt mar le volt irva (a `scripts/` nincs a telepitett skill alatt), mert a leiras abban a fajlban allt, amit nem olvasok. A fenti, Quick start alatti magyar valtozat ugyanezt mondja; a ketto nem mond ellent, csak ket helyen all.

- **A DOUBLE QUOTE INSIDE THE TEXT SILENTLY BREAKS A HAND-ROLLED `curl -d` JSON BODY.**
  Shell single quotes protect the body from the SHELL, not from the JSON parser. One
  raw `"` anywhere in the Hungarian prose -- a quoted name, a quoted command -- and the
  server answers `{"error":"Szerver hiba"}` with no hint about which character did it.
  Measured 2026-08-26: a memory save failed because the text contained a quoted agent
  name; the same content went through immediately once the JSON was built properly.
  **The fix is not more careful escaping, it is not building JSON by hand:** use
  `fleet.py mem-save` / `daily-log` / `msg`, or, when the payload is long, build it in
  Python with `json.dumps` and post it with `urllib.request`. The same applies to
  apostrophes, backslashes and newlines -- `json.dumps` handles all of them, a heredoc
  does not.


- **When you build the payload inline, you keep dropping the closing brace.**
  Measured 2026-08-27: three separate rounds died on `SyntaxError: closing parenthesis ')'
  does not match opening parenthesis '{'`. Every one was the same shape -- a long multi-line
  string as the last dict value, then `""" ))` with the dict's `}` missing. The triple-quoted
  string is not the problem (verified with a minimal repro); the brace at the end of a long
  literal is, and it costs a whole round each time because nothing runs at all.
  **Assign the long text to a variable first, then pass the payload:**
  ```python
  komment = """...long Hungarian text..."""
  post("/api/kanban/%s/comments" % kid, {"author": "marveen", "content": komment})
  ```
  The closing brace then sits next to its opening one on one short line, where a missing one
  is visible. Same reason the JSON is built with `json.dumps` rather than by hand: put the
  fiddly part where a mistake shows.

  A second-order note from the same day: this very pitfall could not be written INTO a
  triple-quoted patch script, because the example contains a triple quote and closed the
  literal early. When patch text contains the delimiter it is about, build it by
  concatenation, not as a literal.

- **The script lives in the repo, NOT under `~/.claude/skills/`.** There is no
  installed copy at `~/.claude/skills/fleet-helper/scripts/fleet.py`; that path
  fails with `No such file or directory`. Always use the repo path
  (`seed-skills/fleet-helper/scripts/fleet.py`) as the Quick start shows.
- **The CLI subcommand is `gate-check`, with a HYPHEN.** `gate_check` is the
  Python function name and the CLI rejects it with `unknown command: gate_check`.
  Exit code 0 and `OK: mehet` mean the text is safe to send; exit 1 lists what it
  found.
- **`mdv2` escapes EVERYTHING it is given, including your `*` bold markers.**
  Escape first, then wrap: build the message piece by piece in Python with
  `"*" + escape_mdv2(label) + "*"`. Escaping an already-formatted string turns the
  bold markers into literal `\*` and the whole message renders wrong.
- **`mem-save` argument order is `agent CONTENT category keywords`, and getting it
  wrong fails in a confusing way.** Put the category second and the server answers
  `400: Invalid category "<your entire memory text>"` -- the content lands in the
  category slot, so the error message is your own paragraph quoted back at you. Measured
  2026-08-29, first try. The dispatch is `save_memory(rest[0], rest[1], rest[2] or
  "warm", rest[3] or "")` in `main()`; category and keywords are optional, content is
  not. Same shape for `daily-log`: `agent CONTENT`.

- **`--help` is not a flag here.** `fleet.py mdv2 --help` just escapes the string
  `--help` and prints `\-\-help`. Run `fleet.py` with no arguments for the
  docstring, or read the `main()` dispatch for the subcommand list.

- **Reading kanban: a single card is NOT fetchable, and the timestamps are integers.**
  `GET /api/kanban/<id>` answers `404` with the PLAIN TEXT body `Not found`, so the reflex
  `curl ... | json.load` dies with `Expecting value: line 1 column 1` and points at YOUR code
  instead of the endpoint. Fetch the whole list (`GET /api/kanban`) and filter by `id` in
  Python; only the comments take an id (`GET /api/kanban/<id>/comments`, 200 JSON). And
  `created_at` / `updated_at` / `archived_at` are unix ints, so `c['updated_at'][:16]` raises
  `TypeError: 'int' object is not subscriptable`. Both measured 2026-09-18, both in one round.
  Full write-up with the working snippet: `references/kanban-olvasas.md`.

## Safety
- Token is read from `store/.dashboard-token` at call time; never printed or committed.
- Kanban helpers are READ-ONLY; mutations stay in your own audited flows.
- `mail_rules.json` (your real senders) is gitignored.
