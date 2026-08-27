#!/usr/bin/env bash
# Az upstream kiadasok atvezetese a gazda forkjaba -- felugyelet nelkul, de VAKON SOHA.
#
# MIERT LETEZIK (2026-08-27): a telepites 2026-08-21 ota minden frissiteskor elakadt,
# mert az update.sh kilep, ha a helyi checkout elore van az origin-hez kepest. A gazda
# sajat commitjai allandoan ott ulnek, tehat ez SZERKEZETI, nem alkalmi. A megoldas: az
# origin a gazda forkja lett, es ez a szkript hozza at bele az upstream kiadasait, hogy
# az update.sh mar csak egy sima fast-forwardot lasson.
#
# A TERVEZES KULCSA: a rebase-t egy FELRETETT MASOLATON probaljuk ki, es az eles fahoz
# csak akkor nyulunk, ha ott a build ATMENT. Aznap este ugyanis az osszeillesztes
# utkozes nelkul lefutott, ES UTANA AZ EGYIK FAJL EL SEM INDULT (a mi kodunk egy olyan
# szimbolumra hivatkozott, amit az upstream atirasa megszuntetett). Egy felugyelet
# nelkuli automata ezt eszrevetlenul beleirta volna az eles fába.
#
# AMIT SOHA NEM TESZ: nem oldja fel az utkozest, nem dob el commitot, nem inditja ujra a
# szolgaltatast, es soha nem hagyja a repot rebase kozbeni allapotban.
set -uo pipefail

REPO="/Users/zoli/marveen"
NAPLO="$REPO/store/upstream-szinkron.log"
EREDMENY="$REPO/store/upstream-szinkron.last-result"
AG="main"
PROBA="$REPO/../marveen-szinkron-proba"

cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" >> "$NAPLO"; }
STASHELT=0
veg() {  # veg <status> <uzenet>
  if [ "$STASHELT" = "1" ]; then
    # A felretett szerkesztesek MINDEN agon visszakerulnek, a hibasakon is: a
    # gazda munkajat nem hagyjuk egy stash-bejegyzesben, ahol holnap senki nem keresi.
    git -C "$REPO" stash pop --quiet 2>>"$NAPLO" || log "FIGYELEM: a stash pop nem sikerult, a szerkesztesek a stash-ben maradtak"
    STASHELT=0
  fi
  printf '{"status":"%s","message":"%s","ts":%s}\n' "$1" "${2//\"/\'}" "$(date +%s)" > "$EREDMENY"
  log "VEGE: $1 -- $2"
  # SZOLNI IS KELL, NEM ELEG LEIRNI. Egy eredmeny-fajl, amit senki nem olvas, ugyanaz a
  # nema elhalas, ami miatt ez a szkript egyaltalan letezik: a frissites hat napig bukott
  # ugy, hogy nem szolt rola semmi. Ezert minden NEM-rendben allapot uzenetet kuld az
  # agensnek. A "nincs-ujdonsag" es az "ok" csendes marad -- azok nem informacio.
  case "$1" in
    ok|nincs-ujdonsag) : ;;
    *)
      printf '%s\n' "[UPSTREAM-SZINKRON] $1: $2. Naplo: store/upstream-szinkron.log. Kezi kor kell, az eles fahoz nem nyultam." \
        | bash "$REPO/scripts/agent-msg.sh" marveen marveen - >>"$NAPLO" 2>&1 || log "az ertesites nem ment ki"
      ;;
  esac
  rm -rf "$PROBA" 2>/dev/null
  git -C "$REPO" worktree prune 2>/dev/null
  [ "$1" = "ok" ] || [ "$1" = "nincs-ujdonsag" ]
  exit $?
}

log "--- indul ---"

git fetch upstream --quiet 2>>"$NAPLO" || veg "hiba" "git fetch upstream sikertelen"

# A hianyzo ref NEM ugyanaz, mint a "nincs ujdonsag". Az elso valtozatban a
# rev-list hibaja `|| echo 0`-ra futott, tehat egy elgepelt vagy megszunt ag-nev
# CSENDES "minden rendben"-kent latszott volna -- pont az a nema elhalas, ami
# miatt ez a szkript letezik. Merve 2026-08-27 egy hamis ag-nevvel.
git rev-parse --verify --quiet "upstream/$AG" >/dev/null || veg "hiba" "az upstream/$AG ref nem letezik"

UJ="$(git rev-list --count "HEAD..upstream/$AG")" || veg "hiba" "a rev-list elszallt az upstream/$AG-en"
[ "$UJ" -eq 0 ] && veg "nincs-ujdonsag" "az upstream nem hozott ujat"
log "$UJ uj upstream commit"

# 1. A munkafa allapota. Egy "csak tiszta munkafaval indulok" szabaly ITT HALOTT
#    SZABALY LENNE: ezen a gepen allandoan all nehany nem commitolt szerkesztes
#    (2026-08-27-en nyolc), tehat a szinkron soha nem futna le. Ezert nem a
#    tisztasagot kerdezzuk, hanem azt, ami valoban szamit: ERINTI-E AZ UPSTREAM
#    UGYANAZT A FAJLT. Ha a ket halmaz diszjunkt, a stash visszatoltese nem tud
#    utkozni; ha metszik egymast, kezi kor kell, mert ott dontes szuletik.
PISZKOS="$(git diff --name-only)"
if [ -n "$PISZKOS" ]; then
  UPSTREAM_FAJLOK="$(git diff --name-only "HEAD..upstream/$AG")"
  METSZET="$(comm -12 <(printf '%s\n' "$PISZKOS" | sort) <(printf '%s\n' "$UPSTREAM_FAJLOK" | sort))"
  if [ -n "$METSZET" ]; then
    veg "kihagyva" "nem commitolt szerkesztes olyan fajlon, amit az upstream is modositott: $(printf '%s' "$METSZET" | tr '\n' ' ')"
  fi
  log "nem commitolt szerkesztes van, de az upstreamtol fuggetlen fajlokon -- felretesszuk"
  git stash push --quiet -m "upstream-szinkron $(date +%F)" 2>>"$NAPLO" || veg "hiba" "a stash nem sikerult"
  STASHELT=1
fi

# 2. PROBA egy felretett masolaton. Az eles fa eddig hozza sem er a rebase-hez.
rm -rf "$PROBA"; git worktree prune
git worktree add -d "$PROBA" HEAD --quiet 2>>"$NAPLO" || veg "hiba" "a proba-masolat nem jott letre"
ln -s "$REPO/node_modules" "$PROBA/node_modules" 2>/dev/null

if ! git -C "$PROBA" rebase "upstream/$AG" >>"$NAPLO" 2>&1; then
  git -C "$PROBA" rebase --abort 2>/dev/null
  veg "utkozes" "$UJ uj commit, de a rebase utkozik; kezi kor kell"
fi

if ! (cd "$PROBA" && npm run build >>"$NAPLO" 2>&1); then
  veg "build-bukas" "a rebase tiszta volt, DE a build elbukott rajta; kezi kor kell"
fi
UJ_HEAD="$(git -C "$PROBA" rev-parse HEAD)"
log "proba rendben, uj HEAD: $UJ_HEAD"

# 3. Csak most nyulunk az eles fahoz, es ujra megnezzuk, hogy kozben nem valtozott-e.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  veg "kihagyva" "a munkafa kozben modosult; kezi kor kell"
fi
git rebase "upstream/$AG" >>"$NAPLO" 2>&1 || { git rebase --abort 2>/dev/null; veg "hiba" "az eles rebase elbukott, pedig a proba atment"; }
npm run build >>"$NAPLO" 2>&1 || veg "hiba" "az eles build elbukott, pedig a proban atment"
git push origin "$AG" >>"$NAPLO" 2>&1 || veg "hiba" "a push elbukott (hitelesites?)"

veg "ok" "$UJ upstream commit atvezetve es feltoltve"
