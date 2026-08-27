// A video NELKULI leckek szovege. Ezekhez nincs se felirat, se hang, tehat a
// masik ket ut egyike sem fogta meg oket -- pedig van bennuk tartalom (a
// kereskedesi szabalyzat, a hazifeladat leirasa, a workspace-utmutato).
//
// ELOTTE OSZTALYOZZ, ne a felirat-szkript cimkejere hagyatkozz. 2026-08-27-en a
// "nincs video (szoveges lecke)" cimkevel megjelolt 23 leckebol TIZ-en volt
// Vimeo-video, csak lassabban toltodott, mint a fix varakozas. Aki ezt a
// szkriptet olyan listara engedi ra, az tiz videos leckere fog ~150 karakternyi
// menut menteni, es utana ugy latszik majd, mintha megvolna a tartalmuk.
// A rovid kimenet ezert NEM kerul fajlba: az ures lecke rosszabb, mint a hianyzo.
//
// Hasznalat:  node scripts/tozsdeturbo-szoveges-lecke.mjs <lista-fajl>
//   A lista-fajl soronkent egy /lecke/<slug> utvonalat tartalmaz.
import pw from '/Users/zoli/marveen/node_modules/playwright/index.js'
import { writeFileSync, existsSync, readFileSync } from 'node:fs'
const { chromium } = pw
const KIMENET = '/Users/zoli/marveen/store/tozsdeturbo/atirat'
const LISTA = process.argv[2]
if (!LISTA) { console.error('Kell egy lista-fajl: node scripts/tozsdeturbo-szoveges-lecke.mjs <fajl>'); process.exit(1) }
const lista = readFileSync(LISTA, 'utf-8').split('\n').map(s => s.trim()).filter(Boolean)

const b = await chromium.connectOverCDP('http://127.0.0.1:9222')
const ctx = b.contexts()[0]
const p = ctx.pages().find(x => x.url().includes('tozsdeturbo.hu')) || await ctx.newPage()

let ok = 0, ures = 0
for (const [i, href] of lista.entries()) {
  const slug = href.replace(/\/$/, '').split('/').pop()
  const cel = join(KIMENET, slug + '.txt')
  if (existsSync(cel)) { console.log(`[${i + 1}/${lista.length}] ${slug}: mar megvan`); continue }
  try {
    await p.goto('https://tozsdeturbo.hu' + href, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await p.waitForTimeout(2500)
    const d = await p.evaluate(() => {
      const t = document.querySelector('main') || document.body
      return { cim: (document.querySelector('h1')?.textContent || '').trim(),
               szoveg: (t.innerText || '').replace(/\n{3,}/g, '\n\n').trim() }
    })
    // A menu es a lablec minden oldalon ott van; ha ezen felul nincs erdemi
    // tartalom, ne irjunk ki egy fajlt, ami ures leckenek latszik majd.
    if (!d.szoveg || d.szoveg.length < 400) {
      console.log(`[${i + 1}/${lista.length}] ${slug}: NINCS erdemi szoveg (${d.szoveg.length} kar)`); ures++
    } else {
      writeFileSync(cel, `# ${d.cim || slug}\n# forras: https://tozsdeturbo.hu${href}\n# kinyerve: szoveges lecke, oldal-szovegbol (2026-08-27)\n\n${d.szoveg}\n`)
      console.log(`[${i + 1}/${lista.length}] ${slug}: OK (${d.szoveg.length} karakter)`); ok++
    }
  } catch (e) {
    console.log(`[${i + 1}/${lista.length}] ${slug}: HIBA ${String(e).slice(0, 90)}`); ures++
  }
  await p.waitForTimeout(2000)
}
console.log(`\nKESZ: ${ok} szoveg mentve, ${ures} ures vagy hibas`)
await b.close(); process.exit(0)
