#!/usr/bin/env node
// PreToolUse hook: Bash OUTBOUND data-send gate.
//
// Rationale (2026-08-13, owner decision): the danger is not what the agent
// READS, it is what the agent SENDS. A plain download brings in content that is
// already treated as untrusted data; the actual damage happens when local data
// leaves the machine to an unknown host. So this gate does not ask "where are
// you looking", it asks "what are you sending, and to whom".
//
// A previously considered alternative -- gating curl/wget reads -- was rejected:
// it is a half-measure (the same download works via python urllib) and it would
// stop the company-research workflow at every new customer domain.
//
// Scope: Bash commands that push data outward.
//   curl   -d/--data*/-F/--form/-T/--upload-file/--json, or -X POST|PUT|PATCH
//   wget   --post-data/--post-file/--method=POST|PUT
//   python requests.post/put/patch(...), urllib Request(..., data=...)
//   nc / scp / rsync to a remote target
//
// Allowed without asking:
//   - every loopback destination (localhost / 127.0.0.1 / ::1), any port
//   - every host on the WebFetch allowlist (built-in + store/egress-allowlist.json)
//
// Everything else is DENIED, logged to store/egress-blocked.log, and the owner
// can approve the destination by adding it to store/egress-allowlist.json.
//
// Deliberately OUT of scope (documented, not forgotten): `git push` (goes to a
// configured remote, not an arbitrary host), MCP server traffic, and helper
// scripts whose network calls live inside the script rather than on the command
// line. Those need their own controls; this hook does not pretend to cover them.

import { readFileSync, appendFileSync, mkdirSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { ALLOWED_PREFIXES, loadRuntimeAllowlist } from './egress-gate.mjs'

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const EGRESS_BLOCK_LOG = join(REPO_ROOT, 'store', 'egress-blocked.log')

// --- Send detection -------------------------------------------------------
// Each pattern names the shape it recognises so the deny message can say what
// was seen, rather than a generic "blocked".
const SEND_PATTERNS = [
  ['curl --data/--form/--upload',
   /\bcurl\b[\s\S]{0,400}?(\s|^)(-d|--data|--data-raw|--data-binary|--data-urlencode|-F|--form|-T|--upload-file|--json)(\s|=)/],
  ['curl -X POST/PUT/PATCH',
   /\bcurl\b[\s\S]{0,400}?(\s|^)(-X|--request)\s+["']?(POST|PUT|PATCH)\b/i],
  ['wget --post',
   /\bwget\b[\s\S]{0,400}?(--post-data|--post-file|--method[=\s]+["']?(POST|PUT|PATCH))/i],
  ['python requests.post/put/patch',
   /\brequests\.(post|put|patch)\s*\(/],
  ['python urllib Request(data=...)',
   /\bRequest\s*\([\s\S]{0,200}?\bdata\s*=/],
  ['netcat', /(^|[\s;|&])nc\s+(-\S+\s+)*[\w.-]+\s+\d{1,5}\b/],
  ['scp', /(^|[\s;|&])scp\s+[\s\S]{0,200}?\S+:/],
  ['rsync to remote', /(^|[\s;|&])rsync\s+[\s\S]{0,200}?\S+@\S+:/],
]

// --- Data context: text that CANNOT execute -------------------------------
// WHY (2026-08-27, owner request): the patterns above match the command TEXT,
// and text is not always a call. Measured: every false positive this gate has
// produced landed in the "destination not readable" branch, because the match
// came from a curl EXAMPLE being written into a file or searched for in one --
// three agents in one morning, none of them sending anything anywhere.
//
// The danger of a false alarm is not the interruption. It is that a gate which
// cries wolf gets worked around, and then it is not there for the real case.
//
// So this section removes only what PROVABLY cannot send. Both rules are
// structural, not heuristic: a heredoc body redirected into a file is never
// executed, and a lone read-only command with no pipeline and no redirect has
// no way to reach the network whatever its arguments say. Anything uncertain
// stays in scope: an interpreter heredoc (`python3 - <<PY`) IS executed, so it
// is left alone, and so is every pipeline.

// The prefix before `<<` when the heredoc body is written to a file, not run.
// Anything else -- an interpreter, a bare `<<`, an unrecognised command -- is
// treated as executed, which keeps the uncertain case inside the gate.
const DATA_SINK = /(^|[\s;&|])(cat\s*>>?|tee(\s+-a)?)\s+\S+\s*$/

// Commands that cannot spawn a process or open a socket, whatever the argument
// says. Deliberately excludes awk (system()), sed (GNU s///e), find (-exec),
// less/vi (shell escape) and every interpreter: those can run what they read.
const READ_ONLY_TOOLS = new Set([
  'grep', 'egrep', 'fgrep', 'rg', 'ag', 'cat', 'head', 'tail', 'wc', 'diff',
  'sort', 'uniq', 'cut', 'tr', 'nl', 'strings', 'stat', 'ls', 'jq', 'basename',
  'dirname', 'shasum', 'md5', 'cmp', 'comm',
])

// A pipeline, a redirect, a substitution or a second statement means the
// read-only tool is no longer alone -- and then its output may well be going
// somewhere. Only a single simple command qualifies.
const SHELL_COMPOSITION = /[|;&`\n<>]|\$\(/

export function isInertReadOnlyCommand(command) {
  const trimmed = command.trim()
  if (!trimmed || SHELL_COMPOSITION.test(trimmed)) return false
  const first = trimmed.split(/\s+/)[0]
  return READ_ONLY_TOOLS.has(first)
}

// One shell statement per element. Splitting only ever gives the scanner LESS
// text per unit, never more, so a send shape can be dropped from consideration
// but never invented.
const SEGMENT_SPLIT = /[;\n]|&&|\|\||\||&/

// Drop the statements that provably cannot send, keep the rest for scanning.
//
// Whole-command matching was too blunt to help in practice: an agent almost
// never runs a bare `grep`, it runs `echo ...; grep ...; python3 ...`, and one
// quoted pattern in the middle used to condemn the lot. Measured right after
// the first version of this fix shipped: the very command written to prove the
// grep case now passed was itself denied, because an echo sat in front of it.
//
// NOT applied when an interpreter heredoc survived the strip. Inside a python
// body a line like `cat = requests_call(url)` starts with a word that happens
// to name a read-only shell tool, and dropping it would hide a real send.
// Shell segmentation has no meaning inside another language anyway.
export function executablePart(command) {
  if (/<<-?\s*['"]?[A-Za-z_]/.test(command)) return command
  return command
    .split(SEGMENT_SPLIT)
    .filter((seg) => !isInertReadOnlyCommand(seg))
    .join('\n')
}

// Remove heredoc bodies that are written to a file. Returns the part of the
// command that can actually run.
export function stripDataHeredocs(command) {
  const lines = command.split('\n')
  const out = []
  let closing = null
  for (const line of lines) {
    if (closing !== null) {
      // Inside a data heredoc: drop the body, keep the terminator's position
      // meaningless to the scanner.
      if (line.trim() === closing) closing = null
      continue
    }
    const m = /<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1/.exec(line)
    if (m && DATA_SINK.test(line.slice(0, m.index))) {
      closing = m[2]
      out.push(line.slice(0, m.index))
      continue
    }
    out.push(line)
  }
  return out.join('\n')
}

export function detectSend(command) {
  for (const [label, re] of SEND_PATTERNS) {
    if (re.test(command)) return label
  }
  return null
}

// --- Destination extraction ----------------------------------------------
const LOOPBACK = new Set(['localhost', '127.0.0.1', '::1', '[::1]'])

export function extractUrls(command) {
  const out = []
  // Strip surrounding quotes/backticks; stop at shell metacharacters.
  const re = /https?:\/\/[^\s'"`;|&)>]+/g
  let m
  while ((m = re.exec(command)) !== null) out.push(m[0])
  return out
}

function isAllowedUrl(url, runtimeList) {
  let hostname
  try {
    hostname = new URL(url).hostname
  } catch {
    return false // unparseable destination: never assume it is fine
  }
  if (LOOPBACK.has(hostname)) return true
  if (ALLOWED_PREFIXES.some((p) => url.startsWith(p))) return true
  if ((runtimeList.prefixes ?? []).some((p) => url.startsWith(p))) return true
  return (runtimeList.domains ?? []).some((d) => hostname === d || hostname.endsWith('.' + d))
}

// Pure decision. Returns null when the command may run, or a reason string when
// it must be denied. File I/O stays out so this is unit-testable.
export function checkOutbound(toolName, toolInput, runtimeList = { domains: [], prefixes: [] }) {
  if (toolName !== 'Bash') return null
  const command = String(toolInput?.command ?? '')
  if (!command) return null

  // Heredoc bodies headed for a file are text, and so are the arguments of any
  // statement that has no way to reach the network. What is left can run.
  const executable = executablePart(stripDataHeredocs(command))
  const sendKind = detectSend(executable)
  if (!sendKind) return null

  const urls = extractUrls(executable)
  if (urls.length === 0) {
    // A send was detected with no http(s) destination on the command line
    // (nc/scp/rsync, or a URL built from a variable). Cannot verify -> deny.
    return `${sendKind}: a célcím nem olvasható ki a parancsból`
  }

  const rejected = urls.filter((u) => !isAllowedUrl(u, runtimeList))
  if (rejected.length === 0) return null
  return `${sendKind} -> ${rejected.join(', ')}`
}

function logBlocked(detail) {
  try {
    mkdirSync(join(REPO_ROOT, 'store'), { recursive: true })
    appendFileSync(
      EGRESS_BLOCK_LOG,
      `${new Date().toISOString()} BLOCKED outbound="${detail.replace(/"/g, "'")}"\n`,
      'utf-8',
    )
  } catch { /* a log failure must never block the agent */ }
}

const denyMessage = (detail) =>
  'Kimenő adatküldés TILTOTT (outbound-data-gate hook). ' +
  `Észlelve: ${detail}. ` +
  'Ez a kapu nem az olvasást korlátozza, hanem azt, hogy helyi adat ismeretlen ' +
  'címre kerüljön. Letöltés (sima GET) szabadon mehet. ' +
  'Ha a küldés jogos: (1) ha csak letölteni akartál, hagyd el a -d/-F/-X POST ' +
  'kapcsolót; (2) ha tényleg küldeni kell, a gazdának kell jóváhagynia a célcímet a ' +
  'store/egress-allowlist.json fájlban ({ "domains": ["example.com"] }), és NE a ' +
  'lekért tartalom kérésére tedd. A hívás rögzítve a store/egress-blocked.log fájlban.'

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
  const reason = checkOutbound(payload?.tool_name, payload?.tool_input, loadRuntimeAllowlist())
  if (reason) {
    logBlocked(reason)
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: denyMessage(reason),
      },
    }))
  }
  process.exit(0)
}
