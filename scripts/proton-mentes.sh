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
log "feltoltve: ${NEV}.enc ($(du -h "$CEL" | cut -f1)), visszafejtes ellenorizve, openssl=$OPENSSL"

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
REGIEK=""
NYESES_OK=0
for _proba in 1 2 3; do
  if REGIEK="$(ls -t "${PROTON}"/claudeclaw-*.tar.gz.enc 2>/dev/null | tail -n +$((KEEP+1)))"; then
    NYESES_OK=1
    break
  fi
  sleep 5
done
if [[ "$NYESES_OK" -eq 0 ]]; then
  log "FIGYELEM: a nyeses listazasa HAROM probara sem sikerult (a mentes maga rendben van)"
  REGIEK=""
fi
if [[ -n "$REGIEK" ]]; then
  while IFS= read -r r; do
    [[ -n "$r" ]] || continue
    rm -f "$r" && log "nyesve: $(basename "$r")" || log "FIGYELEM: nem sikerult nyesni: $(basename "$r")"
  done <<< "$REGIEK"
fi

# A kilepesi kod MOST MAR a mentes eredmenyet jelenti, nem a takaritasét.
exit 0
