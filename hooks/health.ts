// Pure logic for the paper health pane, status line and toasts: no engine calls, so it is unit-testable.
// Each AgenTeX check writes .agentex/status/<tool>.json; the compile loop writes .agentex/build-state.json.
import type { Check, CheckStatus } from '../types'

import { BLUE, type Row } from './frames'

// The checks a paper can have, in the order a "not run yet" list reads best.
export const EXPECTED = [
  'build', 'preflight', 'citations', 'cite-claims', 'numbers', 'provenance', 'repro', 'smoke',
  'settings', 'consistency', 'figures', 'arxiv-html', 'review',
]
const RANK: Record<CheckStatus, number> = { fail: 0, warn: 1, ok: 2 }
// Glyph and word carry the status; colour only repeats it (Okabe-Ito vermillion, orange, bluish green).
const GLYPH: Record<CheckStatus, string> = { fail: '✗', warn: '!', ok: '✓' }
const COLOR: Record<CheckStatus, string> = { fail: '#D55E00', warn: '#E69F00', ok: '#009E73' }
// What a person reads; status files keep the short tool ids.
export const LABEL: Record<string, string> = {
  build: 'Build', preflight: 'Submission rules', citations: 'Citations', 'cite-claims': 'Cited claims',
  numbers: 'Numbers', provenance: 'Figure sources', repro: 'Repro table', smoke: 'Clean rerun',
  settings: 'Settings', consistency: 'Claims vs code', figures: 'Figures', 'arxiv-html': 'arXiv HTML',
  review: 'Review issues',
}
export const label = (tool: string) => LABEL[tool] ?? tool
const NAME_W = 18 // longest label ("Submission rules") plus two spaces

const clip = (s: string, n: number) => (s.length > n ? s.slice(0, Math.max(0, n - 1)) + '…' : s)
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** One status file's JSON as a Check, or null when it is not one (a partial write is retried next scan). */
export function toCheck(doc: any, fallbackTool: string, stamp: number | null): Check | null {
  if (!doc || typeof doc !== 'object' || !['ok', 'warn', 'fail'].includes(doc.status)) return null
  const t = Date.parse(doc.updated)
  const updated = Number.isFinite(t) ? t : null
  return {
    tool: String(doc.tool || fallbackTool),
    status: doc.status,
    summary: String(doc.summary ?? '').slice(0, 100),
    items: (Array.isArray(doc.items) ? doc.items : []).slice(0, 20)
      .map((i: any) => ({ where: String(i?.where ?? ''), message: String(i?.message ?? '') })),
    updated,
    // `stamp` is when the compile loop last saw the LaTeX sources change (epoch seconds)
    stale: updated !== null && stamp !== null && updated < stamp * 1000,
  }
}

/** The compile loop's build-state.json as a Check; null before its first build (only the start stamp). */
export function buildCheck(state: any, mtimeMs: number | null): Check | null {
  const problems = state?.problems
  if (!problems || typeof problems !== 'object') return null
  const items = Object.entries(problems).flatMap(([file, list]) =>
    Array.isArray(list) ? list.map(p => ({ where: file, message: String(p) })) : [])
  const blocks = Number(state.blocks) || 0
  return {
    tool: 'build',
    status: blocks > 0 ? 'fail' : items.length ? 'warn' : 'ok',
    summary: blocks > 0
      ? `broken after the last edit (${plural(blocks, 'fix attempt')})`
      : items.length ? `${plural(items.length, 'unresolved reference')} or citations` : `${plural(Object.keys(problems).length, 'document')} ${Object.keys(problems).length === 1 ? 'compiles' : 'compile'}`,
    items: items.slice(0, 20),
    // built_at (epoch s) is set only when a build ran; the file's mtime also moves at every SessionStart
    updated: typeof state.built_at === 'number' ? state.built_at * 1000 : mtimeMs,
    stale: false,
  }
}

/** One check per tool, the newest result winning (a paper in paper/ and the repo root can both hold results). */
export function newestPerTool(checks: Check[]): Check[] {
  const best = new Map<string, Check>()
  for (const c of checks) {
    const old = best.get(c.tool)
    if (!old || (c.updated ?? -1) > (old.updated ?? -1)) best.set(c.tool, c)
  }
  return [...best.values()]
}

export const sortChecks = (checks: Check[]) =>
  [...checks].sort((a, b) => RANK[a.status] - RANK[b.status] || a.tool.localeCompare(b.tool))

export const missing = (checks: Check[]) => EXPECTED.filter(t => !checks.some(c => c.tool === t))

export function age(ms: number | null): string {
  if (ms === null) return '?'
  const m = Math.floor(ms / 60000)
  return m < 1 ? 'now' : m < 60 ? `${m}m` : m < 1440 ? `${Math.floor(m / 60)}h` : `${Math.floor(m / 1440)}d`
}

/** "2 failing · 1 to check · 5 ok · 4 not run": the pane's one-line summary. */
export function tally(checks: Check[]): string {
  const n = (s: CheckStatus) => checks.filter(c => c.status === s).length
  const parts = [n('fail') && `${n('fail')} failing`, n('warn') && `${n('warn')} to check`, n('ok') && `${n('ok')} ok`]
  const notRun = missing(checks).length
  return [...parts.filter(Boolean), notRun && `${notRun} not run`].filter(Boolean).join(' · ') || 'no checks yet'
}

const TITLE = 'AgenTeX  Paper health'

/** The pane's header: title with the tally right-aligned, then a rule; the tally drops to its own line when narrow. */
export function headerRows(checks: Check[], cols = 80): Row[] {
  const title: Row = [{ text: 'Agen', color: BLUE, bold: true }, { text: 'TeX', bold: true }, { text: '  Paper health', bold: true }]
  const right = tally(checks)
  const gap = cols - TITLE.length - right.length
  const rule: Row = [{ text: '─'.repeat(Math.max(0, cols)), dim: true }]
  return gap >= 2
    ? [[...title, { text: ' '.repeat(gap) }, { text: right, dim: true }], rule]
    : [title, [{ text: right, dim: true }], rule]
}

/** Checks grouped for the pane: what needs attention first, then what passes; empty groups are left out. */
export function sections(checks: Check[]): { title: string; checks: Check[] }[] {
  const sorted = sortChecks(checks)
  return [
    { title: 'Needs attention', checks: sorted.filter(c => c.status !== 'ok') },
    { title: 'Passing', checks: sorted.filter(c => c.status === 'ok') },
  ].filter(s => s.checks.length)
}

/** Checks with no result yet, laid out in columns that fit `cols`. */
export function notRunRows(tools: string[], cols: number): Row[] {
  const cell = NAME_W + 2 // "○ " + label
  const per = Math.max(1, Math.floor((cols - 2) / cell))
  const rows: Row[] = []
  for (let i = 0; i < tools.length; i += per)
    rows.push([{ text: '  ' + tools.slice(i, i + per).map(t => `○ ${label(t)}`.padEnd(cell)).join('').trimEnd(), dim: true }])
  return rows
}

/** One check as a row sized to `cols`: glyph, name, summary, age. Narrow panes drop the summary first. */
export function checkRow(c: Check, now: number, cols: number): Row {
  const when = age(c.updated === null ? null : now - c.updated) + (c.stale ? ' stale' : '')
  const room = cols - 2 - NAME_W - 2 - when.length
  const middle = room >= 12 ? label(c.tool).padEnd(NAME_W) + clip(c.summary, room).padEnd(room) + '  ' : `${label(c.tool)} `
  return [
    { text: `${GLYPH[c.status]} `, color: COLOR[c.status], bold: c.status !== 'ok' },
    { text: middle },
    { text: when, dim: true },
  ]
}

/** A check's items (file:line and message), shown under its row when the person opens it. */
export function itemRows(c: Check, cols: number): Row[] {
  if (!c.items.length) return [[{ text: '    no locations listed', dim: true }]]
  return c.items.map(i => [{ text: '    ' + clip(`${i.where}  ${i.message}`, Math.max(8, cols - 4)), dim: true }])
}

/** The whole view as plain text: what `/agentex` prints where no surface draws panes. */
export function plainText(checks: Check[], now: number, cols = 80): string {
  const notRun = missing(checks)
  const rows: Row[] = [
    ...headerRows(checks, cols),
    ...sections(checks).flatMap(s => [[], [{ text: `${s.title} (${s.checks.length})` }], ...s.checks.map(c => checkRow(c, now, cols))]),
    ...(notRun.length ? [[], [{ text: `Not run yet (${notRun.length})` }], ...notRunRows(notRun, cols)] : []),
  ]
  return rows.map(r => r.map(s => s.text).join('').trimEnd()).join('\n')
}

/** The status line under the prompt, or undefined (cleared) while nothing needs attention. */
export function statusText(checks: Check[]): string | undefined {
  const fail = checks.filter(c => c.status === 'fail').length
  const warn = checks.filter(c => c.status === 'warn').length
  if (!fail && !warn) return undefined
  return `AgenTeX ${[fail && `✗ ${fail} failing`, warn && `! ${warn} to check`].filter(Boolean).join(' · ')} · /agentex`
}

/** Checks that are failing now and were not at the previous scan; none on the first scan of a session. */
export function flips(prev: Check[] | undefined, next: Check[]): Check[] {
  if (!prev) return []
  return next.filter(c => c.status === 'fail' && prev.find(p => p.tool === c.tool)?.status !== 'fail')
}

export function toastText(flipped: Check[]): string {
  return flipped.length === 1
    ? `✗ ${label(flipped[0]!.tool)} now failing: ${clip(flipped[0]!.summary, 80)} · /agentex`
    : `✗ ${flipped.map(c => label(c.tool)).join(', ')} now failing · /agentex`
}
