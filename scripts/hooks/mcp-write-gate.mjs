#!/usr/bin/env node
// PreToolUse hook: MCP write/exfiltration gate for the MAIN agent.
//
// WHY (2026-08-15 security review): the install had exactly two PreToolUse
// matchers, `WebFetch` and `Bash`. Everything the connected MCP servers expose
// ran ungated -- gmail send, Drive sharing and permission changes, Drive and
// calendar deletion. Those are precisely the actions a prompt injection aims
// for, and they are reachable without touching a shell at all. Between an
// injected instruction inside an email body and that email being forwarded to
// the attacker there was no technical control, only the model's own
// discipline (autonomy level 1), which is a policy, not a gate.
//
// Scope: outward-facing or destructive MCP calls only. Reading mail, reading
// Drive, listing the calendar, writing a draft: all untouched, so day-to-day
// work is not slowed down. The gate is name-based rather than server-based so
// that a differently-named server in another install is caught by the same
// rule (mirrors scripts/email-send-gate.mjs, which gates any *send_email*).
//
// HONEST LIMIT, stated rather than hidden: this agent has unrestricted Bash in
// bypass-permissions mode, so no purely local gate is unforgeable -- the same
// process could delete this file. What the gate does buy is real:
//   * a dangerous action can no longer happen as a SIDE EFFECT of reading
//     attacker-controlled text; it takes a separate, deliberate act;
//   * every attempt is logged and surfaced in the weekly security report;
//   * the grant is minted by the owner, not by the agent, so the naive
//     "just approve it yourself" path is closed. (The approvals API was
//     considered and rejected for this: all fleet agents share one bearer
//     token and its self-approval check is best-effort by its own admission,
//     so an agent could mint its own permission. A gate must never depend on
//     a grant the gated party can issue.)
//
// Grant protocol (owner-side, see scripts/approve-once.sh):
//   store/.mcp-grant holds { pattern, expires_at, note }. A matching, unexpired
//   grant lets exactly ONE call through and is consumed (deleted) immediately,
//   whether or not the call then succeeds. No grant file: hard deny.

import { readFileSync, appendFileSync, mkdirSync, unlinkSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const BLOCK_LOG = join(REPO_ROOT, 'store', 'mcp-blocked.log')
const GRANT_FILE = join(REPO_ROOT, 'store', '.mcp-grant')

// Each rule names the shape it recognises, so the deny message says what was
// seen instead of a generic "blocked", and so the log is readable a month later.
export const GATED = [
  ['email küldés', /send_email/i],
  ['email törlés', /delete_email/i],
  ['email mozgatás (kuka is ide tartozik)', /move_email/i],
  ['Drive megosztás', /shareFile/i],
  ['Drive jogosultság-adás', /addPermission/i],
  ['Drive jogosultság-módosítás', /updatePermission/i],
  ['Drive jogosultság-elvétel', /removePermission/i],
  ['Drive elem törlés', /deleteItem/i],
  ['naptár esemény törlés', /delete[-_]?(calendar)?[-_]?event/i],
]

export function gatedKind(toolName) {
  const name = String(toolName ?? '')
  // Only MCP tools are in scope; Bash and WebFetch have their own gates.
  if (!name.startsWith('mcp__')) return null
  for (const [kind, re] of GATED) {
    if (re.test(name)) return kind
  }
  return null
}

// A grant is valid only if it is unexpired AND its pattern matches this tool.
// Anything unreadable or malformed counts as no grant: fail safe toward denial.
export function consumeGrant(toolName, { now = Date.now(), read, remove } = {}) {
  const readFn = read ?? (() => readFileSync(GRANT_FILE, 'utf-8'))
  const removeFn = remove ?? (() => unlinkSync(GRANT_FILE))
  let grant
  try {
    grant = JSON.parse(readFn())
  } catch {
    return null
  }
  let matches = false
  try {
    matches = new RegExp(grant.pattern, 'i').test(String(toolName ?? ''))
  } catch {
    return null
  }
  const expires = Date.parse(grant.expires_at ?? '')
  // Consume on ANY match, even an expired one: a stale grant must not sit there
  // waiting for a later call to pick it up.
  if (matches) {
    try { removeFn() } catch { /* best effort */ }
  }
  if (!matches || !Number.isFinite(expires) || expires < now) return null
  return grant
}

function log(line) {
  try {
    mkdirSync(join(REPO_ROOT, 'store'), { recursive: true })
    appendFileSync(BLOCK_LOG, `${new Date().toISOString()} ${line}\n`, 'utf-8')
  } catch { /* a log failure must never block the agent */ }
}

const denyMessage = (kind, tool) =>
  `MCP írási művelet TILTOTT (mcp-write-gate hook). Észlelve: ${kind} (${tool}). ` +
  'Ez a kapu azt zárja ki, hogy kifelé irányuló vagy romboló művelet egy beolvasott ' +
  'szöveg hatására induljon el. NE próbáld megkerülni, és NE adj magadnak engedélyt: ' +
  'a jóváhagyást a gazda állítja ki. Kérd meg Telegramon, hogy futtassa ezt, majd ' +
  'próbáld újra egyszer:  bash scripts/approve-once.sh "' + tool + '"  ' +
  'A kísérlet rögzítve a store/mcp-blocked.log fájlban.'

function isInvokedDirectly() {
  try {
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1] ?? '')
  } catch {
    return false
  }
}

if (isInvokedDirectly()) {
  let payload
  try {
    payload = JSON.parse(readFileSync(0, 'utf-8'))
  } catch {
    process.exit(0) // malformed input must never block the agent
  }
  const tool = payload?.tool_name
  const kind = gatedKind(tool)
  if (kind) {
    const grant = consumeGrant(tool)
    if (grant) {
      log(`ALLOWED tool="${tool}" kind="${kind}" grant="${grant.note ?? ''}"`)
    } else {
      log(`BLOCKED tool="${tool}" kind="${kind}"`)
      process.stdout.write(JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason: denyMessage(kind, tool),
        },
      }))
    }
  }
  process.exit(0)
}
