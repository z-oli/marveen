import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { json } from '../http-helpers.js'
import type { RouteContext } from './types.js'

// Semantic search over the migrated claude.ai archive. The index lives in a
// SQLite file next to the archive and is queried by a small Python script that
// owns the numpy/embedding side (scripts/archivum-kereso.py). Node just shells
// out to it so the vector maths stays in one place.

const ROOT = process.env.MARVEEN_ROOT ?? '/Users/zoli/marveen'
const PYTHON = path.join(ROOT, 'store/rag-venv/bin/python')
const SCRIPT = path.join(ROOT, 'scripts/archivum-kereso.py')
const KINDS = new Set(['beszelgetes', 'projekt', 'dokumentum', 'claude-memoria'])
const TIMEOUT_MS = 60_000

interface SearchHit {
  score: number
  kind: string
  path: string
  cim: string
  datum: string
  chunk_ix: number
  text: string
}

function runSearch(args: string[]): Promise<{ ok: true; data: unknown } | { ok: false; error: string }> {
  return new Promise((resolve) => {
    const child = spawn(PYTHON, [SCRIPT, ...args], { cwd: ROOT })
    let out = ''
    let err = ''
    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      resolve({ ok: false, error: `search timed out after ${TIMEOUT_MS / 1000}s` })
    }, TIMEOUT_MS)

    child.stdout.on('data', (chunk) => { out += chunk })
    child.stderr.on('data', (chunk) => { err += chunk })
    child.on('error', (e) => {
      clearTimeout(timer)
      resolve({ ok: false, error: e.message })
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      if (code !== 0) {
        resolve({ ok: false, error: err.trim() || `search exited with code ${code}` })
        return
      }
      try {
        resolve({ ok: true, data: JSON.parse(out) })
      } catch {
        resolve({ ok: false, error: `unparseable search output: ${out.slice(0, 200)}` })
      }
    })
  })
}

export async function tryHandleArchive(ctx: RouteContext): Promise<boolean> {
  const { res, path: route, method, url } = ctx

  // GET /api/archive/search?q=...&n=8&kind=beszelgetes&full=1
  if (route === '/api/archive/search' && method === 'GET') {
    const q = (url.searchParams.get('q') ?? '').trim()
    if (!q) {
      json(res, { error: 'q required' }, 400)
      return true
    }

    const rawLimit = parseInt(url.searchParams.get('n') ?? '8', 10)
    const limit = Number.isFinite(rawLimit) ? Math.min(Math.max(rawLimit, 1), 50) : 8
    const kind = url.searchParams.get('kind')
    if (kind && !KINDS.has(kind)) {
      json(res, { error: `kind must be one of: ${[...KINDS].join(', ')}` }, 400)
      return true
    }

    const args = [q, '-n', String(limit), '--json']
    if (kind) args.push('-k', kind)
    if (url.searchParams.get('full') === '1') args.push('--teljes')

    const result = await runSearch(args)
    if (!result.ok) {
      json(res, { error: result.error }, 500)
      return true
    }
    json(res, result.data)
    return true
  }

  // GET /api/archive/status -- is the index present and how big is it
  if (route === '/api/archive/status' && method === 'GET') {
    const db = process.env.ARCHIVE_DB
      ?? path.join(ROOT, 'store/archive/claude/2026-08-12/index.db')
    let indexed = false
    let sizeBytes = 0
    let updatedAt: number | null = null
    try {
      const stat = fs.statSync(db)
      indexed = true
      sizeBytes = stat.size
      updatedAt = Math.floor(stat.mtimeMs / 1000)
    } catch {
      // index not built yet -- reported as indexed: false
    }
    json(res, {
      indexed,
      db,
      size_bytes: sizeBytes,
      updated_at: updatedAt,
      python: fs.existsSync(PYTHON),
      script: fs.existsSync(SCRIPT),
      kinds: [...KINDS],
    })
    return true
  }

  return false
}
