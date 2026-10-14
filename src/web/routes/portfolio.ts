import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { PROJECT_ROOT } from '../../config.js'
import { json } from '../http-helpers.js'
import type { RouteContext } from './types.js'

// The monitor itself is scripts/portfolio-figyelo.py: it reads quantities from
// store/portfolio-tetelek.json, fetches public prices and writes the computed
// state to store/portfolio-allapot.json. This route only SERVES that file --
// it never fetches a price and never recomputes a ratio, so there is exactly
// one place where the numbers are produced and it stays swappable.
const ALLAPOT = join(PROJECT_ROOT, 'store', 'portfolio-allapot.json')

type Eszkoz = { eszkoz: string; arany_pct: number; ertek_usd: number; tipus: string }
type Allapot = {
  frissitve?: string
  ossz_usd?: number
  befektetve_pct?: number
  stablecoin_pct?: number
  keszpenz_pct?: number
  kereskedes_pct?: number
  eszkozok?: Eszkoz[]
  sertesek?: { szabaly: number; szoveg: string }[]
  arfolyam_meta?: unknown
}

export async function tryHandlePortfolio(ctx: RouteContext): Promise<boolean> {
  const { res, path, method } = ctx

  // GET /api/portfolio -- last computed state of the four-rule check.
  // 204 (not 404, not an empty object) when the monitor has never run: the UI
  // must be able to tell "no data yet" from "everything is zero".
  if (path === '/api/portfolio' && method === 'GET') {
    if (!existsSync(ALLAPOT)) {
      res.writeHead(204).end()
      return true
    }
    try {
      const d = JSON.parse(readFileSync(ALLAPOT, 'utf-8')) as Allapot
      json(res, {
        frissitve: d.frissitve ?? null,
        ossz_usd: d.ossz_usd ?? null,
        befektetve_pct: d.befektetve_pct ?? null,
        stablecoin_pct: d.stablecoin_pct ?? null,
        keszpenz_pct: d.keszpenz_pct ?? null,
        kereskedes_pct: d.kereskedes_pct ?? null,
        eszkozok: Array.isArray(d.eszkozok) ? d.eszkozok : [],
        sertesek: Array.isArray(d.sertesek) ? d.sertesek : [],
      })
    } catch (e) {
      json(res, { error: 'portfolio state unreadable', detail: String(e) }, 500)
    }
    return true
  }

  return false
}
