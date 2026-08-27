// Tozsdeturbo Mentorprogram: a leckek magyar auto-feliratanak kinyerese.
//
// MIERT IGY: a videok Vimeo-n futnak, es minden leckehez tartozik magyar
// auto-generalt felirat. A player.vimeo.com/video/<id>/config vegpont 403-at ad
// meg az iframe sajat kontextusabol is, tehat az az ut zsakutca. A player JS
// API viszont postMessage-en valaszol: bekapcsoljuk a texttracket es elinditjuk
// a lejatszast, amitol a Vimeo letolti a .vtt-t, es azt kapjuk el a halozaton.
// Igy nincs hang-letoltes, nincs atiratozas, es a video sem toltodik le.
//
// UDVARIAS: leckenkent szunetet tart, mert ez a tanfolyam szerveret terheli.
// FOLYTATHATO: ami mar megvan a kimeneti mappaban, azt atugorja.
//
// Hasznalat:
//   node scripts/tozsdeturbo-feliratok.mjs            # minden lecke
//   node scripts/tozsdeturbo-feliratok.mjs --limit 5  # elso 5 (proba)

import pw from '/Users/zoli/marveen/node_modules/playwright/index.js'
import { writeFileSync, existsSync, mkdirSync, readdirSync, appendFileSync } from 'node:fs'
import { join } from 'node:path'
const { chromium } = pw

const REPO = '/Users/zoli/marveen'
const KIMENET = join(REPO, 'store', 'tozsdeturbo', 'vtt')
const HALADAS = join(REPO, 'store', 'tozsdeturbo', 'haladas.log')
const KURZUS = 'https://tozsdeturbo.hu/kurzus/mentorprogram-v2'
const SZUNET_MS = 2500          // leckek kozott
const JATSZAS_MS = 9000         // ennyit varunk a .vtt-re
const limitArg = process.argv.indexOf('--limit')
const LIMIT = limitArg > -1 ? parseInt(process.argv[limitArg + 1], 10) : Infinity

// A cel a dontesi checklista, ezert ezek a temak mennek elore: ha a futas
// megszakad, a fontos resz mar megvan.
const ELSOBBSEG = /footprint|orderflow|order-flow|volumen|delta|profile|struktur|setup|trend|kitores|elutasit|oldalaz|szabaly|kockazat|gex|deepcharts|likvid|imbalance|absorb/i

mkdirSync(KIMENET, { recursive: true })
const naplo = (s) => {
  const sor = `${new Date().toISOString()} ${s}`
  console.log(sor)
  try { appendFileSync(HALADAS, sor + '\n') } catch {}
}

const b = await chromium.connectOverCDP('http://127.0.0.1:9222')
const ctx = b.contexts()[0]
const p = ctx.pages().find(x => x.url().includes('tozsdeturbo.hu')) || await ctx.newPage()

await p.goto(KURZUS, { waitUntil: 'domcontentloaded' })
await p.waitForTimeout(2500)

const leckek = await p.evaluate(() => {
  const latott = new Set()
  return [...document.querySelectorAll('a[href*="/lecke/"]')]
    .map(a => a.getAttribute('href'))
    .filter(h => h && !latott.has(h) && latott.add(h))
})

const sorrend = [...leckek].sort((a, b2) => (ELSOBBSEG.test(b2) ? 1 : 0) - (ELSOBBSEG.test(a) ? 1 : 0))
// A MEGLEVO nem csak a vtt. 2026-08-27-en a frissites utani futas 150 leckere
// indult 78 helyett, mert ez a halmaz csak a feliratokat nezte -- pedig 75 lecke
// szovege mar megvan WHISPER-atiratkent. Ket kara van, es a masodik a sulyosabb:
// feleslegesen terheljuk a tanfolyam szerveret, ES a whisper-kell.txt-be masodszor
// is bekerul 72 olyan lecke, amit mar atirtunk -- a kovetkezo lepes pedig azt a
// listat olvassa, tehat orakat toltene ujra-atirassal.
const ATIRAT = join(REPO, 'store', 'tozsdeturbo', 'atirat')
const meglevo = new Set([
  ...readdirSync(KIMENET).map(f => f.replace(/\.vtt$/, '')),
  ...(existsSync(ATIRAT) ? readdirSync(ATIRAT).map(f => f.replace(/\.txt$/, '')) : []),
])
const munka = sorrend.filter(h => !meglevo.has(h.split('/').pop())).slice(0, LIMIT)

naplo(`START: ${leckek.length} lecke osszesen, ${meglevo.size} mar megvan, ${munka.length} feldolgozando`)

let ok = 0, ures = 0, hiba = 0
for (const [i, href] of munka.entries()) {
  const slug = href.split('/').pop()
  let vtt = null
  const figyelo = async (r) => {
    const u = r.url()
    if (/\.vtt(\?|$)|texttrack/i.test(u) && r.status() === 200 && !vtt) {
      try { vtt = await r.text() } catch {}
    }
  }
  p.on('response', figyelo)
  try {
    await p.goto('https://tozsdeturbo.hu' + href, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await p.waitForTimeout(4000)
    // A parancsot ISMETELNI kell. Egyetlen korai postMessage elvesz, mert a
    // Vimeo player meg nem all keszen -- az elso tomeges futasnal emiatt jott
    // harom leckere "NINCS felirat", holott egyesevel mindharom mukodott.
    const kuldParancs = () => p.evaluate(() => {
      const f = [...document.querySelectorAll('iframe')].find(x => x.src.includes('player.vimeo.com'))
      if (!f) return false
      const kuld = (method, value) => f.contentWindow.postMessage(JSON.stringify({ method, value }), '*')
      kuld('setVolume', 0)
      kuld('enableTextTrack', { language: 'hu-x-autogen', kind: 'subtitles' })
      kuld('play')
      return true
    })
    // Elobb KERDEZZUK MEG, van-e egyaltalan felirat. Nem minden videohoz
    // generalt a Vimeo auto-feliratot: ket lecken meresre `getTextTracks: []`
    // jott vissza. Enelkul a szkript 9 masodpercet varna a semmire, es a
    // "nincs felirat" osszemosodna a "nem sikerult elkapni"-val -- pedig az
    // elobbihez whisper kell, az utobbihoz csak egy ujraprobalas.
    const trackek = await p.evaluate(async () => {
      const f = [...document.querySelectorAll('iframe')].find(x => x.src.includes('player.vimeo.com'))
      if (!f) return null
      return await new Promise((res) => {
        const h = (e) => {
          if (!String(e.origin).includes('vimeo')) return
          let d = e.data
          try { if (typeof d === 'string') d = JSON.parse(d) } catch { return }
          if (d && d.method === 'getTextTracks') { window.removeEventListener('message', h); res(d.value || []) }
        }
        window.addEventListener('message', h)
        f.contentWindow.postMessage(JSON.stringify({ method: 'getTextTracks' }), '*')
        setTimeout(() => { window.removeEventListener('message', h); res([]) }, 7000)
      })
    })

    if (trackek === null) {
      naplo(`[${i + 1}/${munka.length}] ${slug}: nincs video (szoveges lecke)`); ures++
      await p.waitForTimeout(SZUNET_MS); continue
    }
    if (trackek.length === 0) {
      naplo(`[${i + 1}/${munka.length}] ${slug}: VIDEO VAN, FELIRAT NINCS -> whisper kell`)
      appendFileSync(join(REPO, 'store', 'tozsdeturbo', 'whisper-kell.txt'), href + '\n')
      ures++
      await p.waitForTimeout(SZUNET_MS); continue
    }

    const van = await kuldParancs()
    if (!van) {
      naplo(`[${i + 1}/${munka.length}] ${slug}: nincs video (szoveges lecke)`); ures++
    } else {
      const hatarido = Date.now() + JATSZAS_MS
      let ujra = 0
      while (!vtt && Date.now() < hatarido) {
        await p.waitForTimeout(500)
        if (++ujra % 4 === 0) await kuldParancs().catch(() => {})
      }
      if (vtt) {
        writeFileSync(join(KIMENET, `${slug}.vtt`), vtt)
        naplo(`[${i + 1}/${munka.length}] ${slug}: OK (${vtt.length} karakter)`); ok++
      } else {
        naplo(`[${i + 1}/${munka.length}] ${slug}: NINCS felirat`); ures++
      }
      await p.evaluate(() => {
        const f = [...document.querySelectorAll('iframe')].find(x => x.src.includes('player.vimeo.com'))
        if (f) f.contentWindow.postMessage(JSON.stringify({ method: 'pause' }), '*')
      })
    }
  } catch (e) {
    naplo(`[${i + 1}/${munka.length}] ${slug}: HIBA ${String(e).slice(0, 120)}`); hiba++
  } finally {
    p.off('response', figyelo)
  }
  await p.waitForTimeout(SZUNET_MS)
}

naplo(`KESZ: ${ok} felirat mentve, ${ures} felirat nelkul, ${hiba} hiba`)
await b.close()
