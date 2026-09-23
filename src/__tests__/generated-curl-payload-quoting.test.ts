// CURLQUOTE910: the generator must not hand agents a curl form whose payload the
// shell expands. In a double-quoted `-d "{...}"` the shell runs backticks and
// $(...) INSIDE the payload and substitutes the output, so a report that quotes a
// filename, a hash, or -- worse -- a stranger's message text executes it, and the
// POST still returns 200. Nothing marks the loss on either end, which is why the
// shape is pinned by tests instead of by care: a reader copying the block cannot
// tell a working example from a hazardous one by looking at it.
//
// Two generated surfaces carry a curl example into every agent's CLAUDE.md:
//   1. buildAutonomyBody()  -- rewritten on EVERY agent start (ensureAutonomySection)
//   2. generateClaudeMd()   -- written once, at agent creation (stranger-sender rule)
// Both are asserted here: (1) functionally, on the file the generator writes, and
// (2) at source level, the established idiom for the LLM-calling generator.
import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const tmpRoot = mkdtempSync(join(tmpdir(), 'marveen-curlquote-test-'))

vi.mock('../config.js', () => ({
  PROJECT_ROOT: tmpRoot,
  OWNER_NAME: 'TestOwner',
  MAIN_AGENT_ID: 'agent-a',
  BOT_NAME: 'agent-a',
  CHANNEL_PROVIDER: 'telegram',
  WEB_PORT: 3420,
  OWNER_DRIVE_FOLDER: '',
  DASHBOARD_PUBLIC_URL: '',
  AGENT_API_ORIGIN: '',
  APP_TZ: 'Europe/Budapest',
}))

vi.mock('../web/agent-config.js', () => ({
  agentDir: (name: string) => join(tmpRoot, 'agents', name),
  agentConfigRoot: () => join(tmpRoot, 'agents'),
  listAgentNames: () => ['agent-a', 'agent-b'],
  readAgentCapabilities: () => [],
}))

vi.mock('../web/atomic-write.js', () => ({
  atomicWriteFileSync: (path: string, content: string) => writeFileSync(path, content, 'utf-8'),
}))

const { ensureAutonomySection } = await import('../web/agent-scaffold.js')

const MARKER_BEGIN = '<!-- BEGIN GENERATED: autonomy-wiring (auto-generated, do not edit by hand) -->'
const MARKER_END = '<!-- END GENERATED: autonomy-wiring -->'

// A payload the shell expands: -d / --data followed by a double quote.
const SHELL_EXPANDING_PAYLOAD = /(?:^|\s)(?:-d|--data|--data-raw)\s+"/

function writtenAutonomyBlock(agentName: string): string {
  const dir = join(tmpRoot, 'agents', agentName)
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'CLAUDE.md'), `# ${agentName}\n`, 'utf-8')
  ensureAutonomySection(agentName)
  const file = readFileSync(join(dir, 'CLAUDE.md'), 'utf-8')
  const from = file.indexOf(MARKER_BEGIN)
  const to = file.indexOf(MARKER_END)
  expect(from, 'autonomy block not written').toBeGreaterThanOrEqual(0)
  expect(to, 'autonomy end marker not written').toBeGreaterThan(from)
  return file.slice(from, to)
}

// 2026-09-23, rebase-feloldas. A CURLQUOTE910 SZANDEKA VALTOZATLAN: egy agens ne
// kapjon olyan kuldo-alakot, amiben a shell vegrehajtja a payload tartalmat. A
// MEGVALOSITAS viszont ezen a forkon TOVABB MENT, mint amit ezek az allitasok
// rogzitettek: a level 1 inter-agent pelda mar egyaltalan NEM curl, hanem a
// scripts/agent-msg.sh helper, aminek a tartalom STDIN-rol, FAJLBOL erkezik, es ami
// ellenorzi a HTTP-kodot ES a visszakapott id-t is. Ami a heredoc-nal csak inert,
// az itt el sem jut a shellhez argumentumkent.
//
// Ezert az allitasok a TULAJDONSAGRA szolnak, nem a szintaxisra: idezett hatarolo,
// fajlbol jovo szabad szoveg, json.dumps-szal epitett payload, megnevezett agens.
// Ha a generator valaha visszaterne a curl-alakra, a lenti negyedik allitas (egyetlen
// sor sem hasznal idezojeles payloadot) valtozatlanul elkapja a veszelyes format.
describe('generated autonomy block: the send examples keep free text inert', () => {
  it('the measure is not vacuous -- the written block really carries send examples', () => {
    const block = writtenAutonomyBlock('meter-check-agent')
    const heredocs = block.split('\n').filter((l) => l.includes("<<'"))
    expect(heredocs.length, 'no quoted heredoc in the generated block').toBeGreaterThanOrEqual(2)
  })

  // Positive control: the level 2 approvals example carries FREE TEXT the owner
  // reads before approving. It must never travel as a quoted argument, and the
  // payload must be built by a JSON serialiser rather than by the shell.
  it('positive control: the level 2 approvals example keeps its free text out of the shell', () => {
    const block = writtenAutonomyBlock('control-agent')
    const level2 = block.slice(block.indexOf('Level 2'))
    expect(level2).toContain('/api/approvals')
    expect(level2).not.toMatch(SHELL_EXPANDING_PAYLOAD)
    expect(level2).toContain("<<'TXT'")
    expect(level2).toMatch(/json\.dumps|jq/)
  })

  it('the level 1 inter-agent example does not use a double-quoted payload', () => {
    const block = writtenAutonomyBlock('level1-agent')
    const level1 = block.slice(block.indexOf('Level 1'), block.indexOf('Level 2'))
    expect(level1).toContain('agent-msg.sh')
    expect(level1).not.toMatch(SHELL_EXPANDING_PAYLOAD)
  })

  it('no line of the whole generated block uses a double-quoted payload', () => {
    const block = writtenAutonomyBlock('whole-block-agent')
    const offenders = block.split('\n').filter((l) => SHELL_EXPANDING_PAYLOAD.test(l))
    expect(offenders, `shell-expanding payload in generated block:\n${offenders.join('\n')}`).toEqual([])
  })

  it('the level 1 example ships the quoted-heredoc form, so free text stays inert', () => {
    const block = writtenAutonomyBlock('heredoc-agent')
    const level1 = block.slice(block.indexOf('Level 1'), block.indexOf('Level 2'))
    expect(level1).toContain("<<'MSG'")
  })

  it('the level 1 example takes its content from a file on stdin, not from an argument', () => {
    const block = writtenAutonomyBlock('stdin-agent')
    const level1 = block.slice(block.indexOf('Level 1'), block.indexOf('Level 2'))
    expect(level1).toMatch(/agent-msg\.sh[^\n]*-\s*<\s*\/tmp\//)
  })

  it('the level 1 example names the agent itself, not a placeholder', () => {
    const block = writtenAutonomyBlock('named-agent')
    const level1 = block.slice(block.indexOf('Level 1'), block.indexOf('Level 2'))
    expect(level1).toContain('named-agent')
    expect(level1).not.toContain('AGENT_NAME')
  })

  // The warning must say WHY the quoted argument is refused, not just that it is.
  // A rule without its reason gets dropped the first time it is inconvenient --
  // and the reason here is that the loss is SILENT: the shell truncates, the send
  // still answers OK, and nothing on either end marks what went missing.
  it('the warning says why a quoted argument is refused, not just that it is', () => {
    const block = writtenAutonomyBlock('warning-agent')
    expect(block).toMatch(/csonk/i)
    expect(block).toMatch(/sikeresnek látszik|sikeres/i)
  })

  it('the token is read from the token file, not pasted into the example', () => {
    const block = writtenAutonomyBlock('token-agent')
    expect(block).toMatch(/\.dashboard-token/)
  })
})

describe('generateClaudeMd source: no shell-expanding curl payload', () => {
  const src = readFileSync(join(process.cwd(), 'src/web/agent-scaffold.ts'), 'utf-8')
  const fnStart = src.indexOf('export async function generateClaudeMd')
  const fnEnd = src.indexOf('export async function generateSoulMd')

  it('the measure is not vacuous -- the generator body is found and carries curl examples', () => {
    expect(fnStart, 'generateClaudeMd not found').toBeGreaterThan(0)
    expect(fnEnd, 'generateSoulMd terminator not found').toBeGreaterThan(fnStart)
    expect(src.slice(fnStart, fnEnd)).toContain('curl -s -X POST')
  })

  // The stranger-sender ARANYSZABÁLY example interpolates a stranger's own words
  // into the payload. That is the one place a double-quoted payload is not a style
  // question: the stranger writes the command that runs.
  it('the stranger-sender example does not use a double-quoted payload', () => {
    const body = src.slice(fnStart, fnEnd)
    const offenders = body.split('\n').filter((l) => SHELL_EXPANDING_PAYLOAD.test(l))
    expect(offenders, `shell-expanding payload in generateClaudeMd:\n${offenders.join('\n')}`).toEqual([])
  })

  it('the stranger-sender block ships the quoted heredoc, whatever the sender wrote', () => {
    const body = src.slice(fnStart, fnEnd)
    const blockStart = body.indexOf('## Új ismeretlen sender első üzenete')
    expect(blockStart, 'stranger-sender block not found').toBeGreaterThan(0)
    const rest = body.slice(blockStart + 5)
    const nextHeader = rest.indexOf('\n## ')
    const block = body.slice(blockStart, blockStart + 5 + (nextHeader > 0 ? nextHeader : rest.length))
    expect(block).toContain(`--data-binary @- <<'JSON'`)
  })

  // Widest of the source assertions, and the reason it is here: a third curl
  // example added anywhere else in this file would escape the two scoped checks
  // above. The earlier branch had this one; the scoped checks alone would not
  // have caught a new offender outside both blocks.
  it('no curl example anywhere in the scaffold uses a double-quoted payload', () => {
    const offenders = src.split('\n').filter((l) => l.includes('curl ') && SHELL_EXPANDING_PAYLOAD.test(l))
    expect(offenders, `shell-expanding payload in agent-scaffold.ts:\n${offenders.join('\n')}`).toEqual([])
  })
})
