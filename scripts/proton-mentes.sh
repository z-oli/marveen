#!/usr/bin/env bash
# Titkositott mentes a Proton Drive szinkron mappajaba.
#
# MIERT TITKOSITVA: a scripts/backup.sh altal keszitett csomagban ELO KULCSOK
# vannak (dashboard bearer, Telegram bot token, projekt .env). A backup.sh maga
# figyelmeztet, hogy ne kerüljön felhos mappaba. Ez a tiltas a TITKOSITATLAN
# csomagra vonatkozik: ha titkositva megy fel, a Proton fiok kompromittalodasa
# sem ad kulcsokat. Ezert itt a feltoltes ELOTT titkositunk, es SOHA nem masoljuk
# fel a nyers .tar.gz-t.
#
# MIERT NEM RCLONE: az rclone protondrive backendje a Proton jelszot es a 2FA-t
# az rclone.conf-ba kerne, tehat az agensnek latnia kellene a gazda jelszavat.
# Nem kell es nem is szabad. Helyette a gazda telepitette a Proton Drive appot es
# O lepett be; mi csak a szinkron mappaba irunk, az app tolti fel.
#
# JELSZO: store/.proton-passphrase (0600). A gazdanak EL KELL TENNIE a gepen
# KIVUL is (Proton Pass), kulonben tuz eseten a mentes megvan, de kinyithatatlan.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTON="/Users/zoli/Library/CloudStorage/ProtonDrive-z.szalai@pm.me-folder/marveen-mentes"
PASSFILE="${REPO}/store/.proton-passphrase"
LOG="${REPO}/store/proton-mentes.log"
KEEP=14

# A homebrew openssl a pontos: a rendszer /usr/bin/openssl LibreSSL, es a
# -pbkdf2 alapertelmezesei elterhetnek. Ha nincs meg, essunk vissza, de NAPLOZZUK,
# mert visszafejteskor ugyanazt kell hasznalni.
OPENSSL="/opt/homebrew/bin/openssl"
[[ -x "$OPENSSL" ]] || OPENSSL="$(command -v openssl)"

log(){ echo "$(date -Iseconds) [proton] $*" >> "$LOG"; }

[[ -f "$PASSFILE" ]] || { log "HIBA: nincs jelszo-fajl ($PASSFILE)"; exit 1; }
[[ -d "$(dirname "$PROTON")" ]] || { log "HIBA: nincs Proton szinkron mappa"; exit 1; }
mkdir -p "$PROTON"

UJ="$(ls -t "${REPO}"/backups/claudeclaw-*.tar.gz 2>/dev/null | head -1 || true)"
[[ -n "$UJ" ]] || { log "HIBA: nincs mentendo csomag a backups/ alatt"; exit 1; }

NEV="$(basename "$UJ")"
CEL="${PROTON}/${NEV}.enc"

# *** A NYESES MINDEN FUTASBAN LEFUT, A TOBBI LEPES ELOTT (2026-09-18, Zoli jovahagyasaval). ***
# ELSO BAJ (javitva ma): korabban a feltoltes UTAN allt, es 2026-08-26 ota egyetlen ejjel sem
# futott le -- kozvetlenul egy 18 MB-os iras utan listazta a mappat, a Proton file-provider
# olyankor szinkronizal, es az `ls -t` elhasal. Harom proba ot masodperces szunettel keves.
# 24 csomag gyult ossze 14 helyett; nyugalmi allapotban ugyanaz a parancs hibatlanul fut.
# MASODIK BAJ (ezert all MOST a `mar fent van` vizsgalat ELOTT): ha az aznapi csomag mar
# fent volt, a script kilepett, MIELOTT a nyeseshez ert volna -- tehat egy naptaron beluli
# masodik futas csendben kihagyta a takaritast.
# A KUSZOB ATTOL FUGG, JON-E MEG MA CSOMAG. Ha a mai mar fent van, KEEP darabot tartunk meg;
# ha meg nem, KEEP-1-et, es a rakovetkezo iras teszi teljesse a KEEP-et. Igy a futas VEGEN
# mindket agon pontosan KEEP csomag all a mappaban.
if [[ -f "$CEL" ]]; then MEGTART=$KEEP; else MEGTART=$((KEEP-1)); fi
# ARA, AMIT VALLALUNK: ha a mentes a nyeses UTAN bukik el, egy futamnyira KEEP-1 csomagunk
# van. A legregebbi elvesztese elhanyagolhato egy nem-futo nyeseshez kepest.
# Regi tavoli csomagok nyesese. Csak a sajat nevmintankat bantjuk.
#
# MIERT NEM EZ A SCRIPT UTOLSO PARANCSA (2026-08-27): a `set -o pipefail` miatt a
# nyeses barmelyik tagjanak nem-nulla kilepese A TELJES SCRIPT kilepesi kodja lett.
# Az elso eles, felugyelet nelkuli futas (03:40) SIKERES volt -- a titkositott
# csomag fent van, a visszafejtes ellenorizve --, a launchd megis "last exit code = 1"-et
# konyvelt el, mert a Proton file-provider mappa listazasa megbotlott a szinkron
# kozben. Ez a legrosszabb fajta hiba: a sikeres mentes bukasnak latszik, tehat egy
# valodi bukas SEM kulonboztetheto meg tole. A nyeses mostantol elszigetelve fut,
# es ha elbukik, azt NAPLOZZA, nem pedig a mentes eredmenyet hazudja el.
# ELOSZOR UJRAPROBALJUK, ES CSAK UTANA PANASZKODUNK (2026-08-28). A 03:40-es futas
# ugyanabban a masodpercben jelentette a listazas bukasat, amelyikben a friss csomag
# kikerult: a Proton file-provider mappa epp szinkronizalt. Percekkel kesobb ugyanaz a
# parancs hibatlanul futott. Egy ilyen atmeneti bukasra kiadott figyelmeztetes ROSSZABB
# a semminel: minden ejjel megjelenik, senki nem nezi meg, es amikor egyszer VALODI lesz,
# ugyanugy nez ki. Harom proba, kozottuk szunet; ha mind elbukik, AKKOR szolunk.
# *** A `2>/dev/null` MIATT HAROM HETIG VAKOK VOLTUNK (2026-09-22, Zoli kerdesere merve). ***
# A nyeses 2026-08-26 ota EGYETLEN ejjel sem futott le: 26 "HAROM probara sem sikerult" sor all
# a naplóban, es a mappa 18 csomagra hizott a 14 helyett (a 09-18-i 24->14 KEZI nyeses ota negy
# ej telt el, negy uj csomaggal). A hibauzenetet viszont eldobtuk, tehat a naplo azt mondta meg,
# HOGY elbukott, azt nem, hogy MIERT -- es a launchd stderr fajlja (store/proton-mentes.err)
# pont ezert maradt URES. Nyugalmi allapotban, interaktiv shellbol UGYANEZ a parancs hibatlanul
# fut es pontosan a 4 nyesendo csomagot adja vissza, tehat NEM logikai hiba: a 03:40-es
# kornyezetben van valami mas (file-provider allapot, TCC, vagy meg nem csatolt almappa).
# EZERT: a stderr-t MOSTANTOL ELKAPJUK es NAPLOZZUK. A kovetkezo elbukott futas maga mondja meg,
# mi a baj. Ne vedd vissza a `2>/dev/null`-t, amig a hiba oka ki nem derult.
# *** ES 2026-09-23 HAJNALBAN KIDERULT. AZ OK: macOS TCC. ***
# Az elso futas a javitott naplozassal azonnal kiadta: `ls: .../claudeclaw-*.tar.gz.enc:
# No such file or directory` -- felrevezeto uzenet, mert a mappa LETEZIK es tele van. A glob
# nem bomlott ki, mert a konyvtar BEOLVASASA tiltott, tehat az ls a literalis mintat kapta.
# Reprodukalva eldobhato launchd agenttel, ugyanezzel a /bin/bash-sal, ugyanebben a
# kontextusban (utana eltavolitva):
#   ls <mappa>                      -> Operation not permitted   (readdir TILTOTT)
#   test -d <mappa>                 -> IGEN                      (stat MEGY)
#   test -f <ismert csomag>         -> IGEN                      (stat MEGY)
#   uj fajl irasa ismert utvonalra  -> OK                        (create/write MEGY)
#   rm -f <sajat dummy fajl>        -> Operation not permitted   (unlink TILTOTT)
# A launchd alol inditott /bin/bash-nak nincs Full Disk Access, a ~/Library/CloudStorage
# pedig TCC-vedett. Ezert sikerul a mentes (uj fajl ismert utvonalra) es bukik a nyeses
# (listazas + torles) ugyanabban a masodpercben, ugyanabba a mappaba.
# *** AMI EZZEL KIESIK, MIELOTT BARKI UJRA FELVETNE: a kezenfekvo javitas -- a szkript
# vezessen sajat nyilvantartast a feltoltott fajlnevekrol, es abbol nyessen readdir nelkul --
# NEM MUKODNE, mert a TORLES is tiltott. Ezt kulon meg kellett merni; a listazas bukasa
# onmagaban nem mondta volna meg. ***
# A KET JARHATO UT (Zoli dontese, kartya cc512a3a): (1) Full Disk Access a /bin/bash-nak,
# cserebe minden bash szkript megkapja; vagy (2) a nyeses atkerul az agens sajat utemezett
# feladataba, aminek a kontextusa hozzafer -- a 09-18-i es 09-22-i kezi nyeses igy ment.
# A `2>/dev/null` TOVABBRA SE kerüljon vissza: ez a naplozas adta meg a valaszt.
# *** A NYESES 2026-09-23 OTA NEM ITT FUT (Zoli dontese, Discord 1552173032196546661). ***
# Ok: a fenti TCC-meres. Ebbol a kornyezetbol a listazas ES a torles is tiltott, tehat a
# nyeses itt NEM javithato meg -- barmilyen ujraprobalkozas csak zajt termel. Atkerult az
# agens sajat utemezett feladataba (`proton-nyeses`, scripts/proton-nyeses.sh), aminek a
# kornyezete hozzafer a mappahoz. Ara: a nyeses az agens futasatol fugg; ha az all, a
# csomagok gyulnek, de A MENTES ATTOL MEG MEGY, es ez a fontosabb.
# NE tedd vissza ide a nyesest, amig a bash nem kap teljes lemez-hozzaferest.

if [[ -f "$CEL" ]]; then
  log "kihagyva, mar fent van: ${NEV}.enc"
  exit 0
fi

TMP="$(mktemp -t proton-mentes)"
trap 'rm -f "$TMP" "$TMP.vissza"' EXIT

"$OPENSSL" enc -aes-256-cbc -pbkdf2 -iter 600000 -salt \
  -in "$UJ" -out "$TMP" -pass "file:${PASSFILE}"

# *** ELLENORZES: VISSZAFEJTJUK ES OSSZEHASONLITJUK. ***
# Titkositani es remelni, hogy jo, ugyanaz a nema hiba, mint barmelyik masik:
# a fajl letrejon, a merete hihetо, es csak egy tenyleges visszaallitasnal derulne
# ki, hogy hasznalhatatlan. Akkor viszont mar keso.
"$OPENSSL" enc -d -aes-256-cbc -pbkdf2 -iter 600000 \
  -in "$TMP" -out "$TMP.vissza" -pass "file:${PASSFILE}"

E="$(shasum -a 256 "$UJ" | cut -d' ' -f1)"
V="$("$(command -v shasum)" -a 256 "$TMP.vissza" | cut -d' ' -f1)"
if [[ "$E" != "$V" ]]; then
  log "HIBA: a visszafejtes NEM egyezik az eredetivel, NEM toltom fel. ($NEV)"
  exit 1
fi

mv "$TMP" "$CEL"
chmod 600 "$CEL"
# A SZO SZAMIT (2026-09-18): a szkript a SZINKRON MAPPABA ir, a feltoltest a Proton app
# vegzi, tehat ezt a lepest NEM latjuk. A regi "feltoltve" ige tobbet allitott, mint
# amit a kod merni tud, es 15 napig senki nem kerdezett ra. Amit valoban ellenoriztunk:
# a helyi iras es a visszafejtes. A feltoltes tenye a Proton weben ellenorizheto.
log "szinkron-mappaba kiirva: ${NEV}.enc ($(du -h "$CEL" | cut -f1)), visszafejtes ellenorizve, openssl=$OPENSSL"

# A kilepesi kod a mentes eredmenyet jelenti. (A nyeses 2026-09-18 ota a feltoltes ELE
# kerult; ott sem befolyasolja a kilepesi kodot, mert vegig `if`-agakban fut.)
exit 0
