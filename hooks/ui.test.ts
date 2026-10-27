// Run: claude plugin test .
import { expect, mock, test } from 'claude-code/testing'

import { activityRows, labelFor, logo, welcomeRows, WELCOME_FRAMES } from './frames'
import { age, buildCheck, checkRow, flips, itemRows, missing, newestPerTool, plainText, sortChecks, statusText, toastText, toCheck } from './health'

const BAND = { component: 'AbovePrompt', props: { hasSurvey: false, isWorking: true, maxRows: 4, bodyColumns: 100 } } as const
// Stands in for the engine beneath the plugin: the default (empty) band, prompts, and Bash.
function engine(on: any, onBash: () => Promise<void> = async () => {}) {
  on('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => {
    const { Box } = $.ui.resolve(e)
    return h(Box, { key: 'engine-default' })
  })
  on('prompt.submit', (_: any, e: any) => ({ text: e.text }))
  on('tool.call', { tool: 'Bash' }, async () => {
    await onBash()
    return { result: { stdout: 'ok', stderr: '' } }
  })
}

const text = (rows: { text: string }[][]) => rows.map(r => r.map(s => s.text).join('')).join('\n')

test('frames: the E drops into place and bobs; commands map to labels', async () => {
  expect(text(logo(7, false))).toBe('AgenTEX\n       ')
  expect(text(logo(7, true))).toBe('AgenT X\n     E ')
  expect(text(logo(3, false))).toBe('Age    \n       ')
  expect(text(welcomeRows(WELCOME_FRAMES - 1))).toContain('installed ✓')
  expect(text(activityRows(0, 'verifying citations'))).toContain('⠋ verifying citations  0s')
  expect(text(activityRows(23, 'x'))).toContain('2s')
  expect(labelFor('python3 skills/latex-references/scripts/cite_verify.py paper/ --keys a')).toBe('verifying citations')
  expect(labelFor('python3 results.py audit paper/')).toBe('checking numbers against the code')
  expect(labelFor('latexmk -pdf main.tex')).toBe('typesetting')
  expect(labelFor('python3 skills/latex-debug/scripts/build.py cv.tex --preview previews')).toBe('typesetting')
  expect(labelFor('python3 pdftool.py merge all.pdf a.pdf b.pdf')).toBe('working on the PDF')
  expect(labelFor('latexdiff-vc --git --flatten -r v1 main.tex')).toBe('marking changes between versions')
  expect(labelFor('git status')).toBe(null)
})

test('frames: the newer check scripts have labels, generic names only from a skill folder', async () => {
  const run = (skill: string, script: string) => `python3 ~/.claude/plugins/agentex/skills/${skill}/scripts/${script}`
  expect(labelFor(run('latex-submit', 'preflight.py main.tex --venue neurips'))).toBe('checking submission rules')
  expect(labelFor(run('latex-submit', 'disclosure.py paper/'))).toBe('drafting the LLM-use disclosure')
  expect(labelFor(run('latex-consistency', 'settings_audit.py paper/ configs/'))).toBe('looking for undisclosed hyperparameters')
  expect(labelFor(run('latex-consistency', 'claims.py report'))).toBe('checking claims against the code')
  expect(labelFor(run('latex-results-sync', 'repro.py smoke --outputs paper/figures/loss.pdf'))).toBe('reproducing results in a clean checkout')
  expect(labelFor(run('latex-results-sync', 'repro.py table --paper paper/'))).toBe('building the reproduction table')
  expect(labelFor(run('latex-references', 'cite_claims.py paper/'))).toBe('checking cited claims against their sources')
  expect(labelFor(run('latex-references', 'cite_verify.py paper/'))).toBe('verifying citations')
  expect(labelFor(run('latex-tables-figures', 'figcheck.py paper/'))).toBe('checking figures')
  expect(labelFor(run('latex-tables-figures', 'mplstyle.py --venue icml'))).toBe('styling plots for print')
  expect(labelFor(run('latex-arxiv', 'html_check.py paper/'))).toBe('checking the arXiv HTML')
  expect(labelFor(run('latex-review', 'issues.py guard main.tex'))).toBe('guarding edits')
  expect(labelFor(run('latex-review', 'issues.py list --open'))).toBe('tracking review issues')
  expect(labelFor(run('latex-review', 'rebuttal.py draft'))).toBe('drafting the rebuttal')
  expect(labelFor(run('latex-project', 'texstats.py main.tex'))).toBe('counting words')
  expect(labelFor(run('latex-pdf', 'mail_merge.py letters.csv'))).toBe('merging documents')
  // a project's own scripts with the same generic names are not AgenTeX work
  for (const own of ['python3 claims.py', 'python3 tools/repro.py smoke', 'python issues.py guard', 'python3 build.py --release'])
    expect(labelFor(own)).toBe(null)
})

// ---- paper health -------------------------------------------------------------------------------------------

const NOW = Date.parse('2026-10-26T12:00:00Z')
const ago = (min: number) => new Date(NOW - min * 60_000).toISOString()
type Item = { where: string; message: string }
const result = (tool: string, status: string, summary: string, min = 5, items: Item[] = []) =>
  ({ tool, status, summary, counts: {}, items, updated: ago(min) })
const MIXED = {
  'status/citations.json': result('citations', 'fail', '1 retracted reference: smith2020', 3, [{ where: 'refs.bib:12', message: 'smith2020 was retracted' }]),
  'status/numbers.json': result('numbers', 'warn', '3 hand-typed numbers', 90, [{ where: 'results.tex:41', message: '0.913 typed by hand' }]),
  'status/preflight.json': result('preflight', 'ok', 'NeurIPS rules pass', 2 * 1440),
  'status/review.json': result('review', 'fail', '2 open major issues', 1),
}
const PANE = {
  component: 'Pane', requestId: 'agentex-health',
  props: { title: 'Paper health', isFocused: true, bodyColumns: 90, placement: 'dock', scroll: { offset: 0 }, view: {} },
} as any

// Stands in for the project's .agentex folder: `files` maps paths under it to JSON; mutate it between scans.
// Calls on $ are answered { value } or { deny } (a missing file); the engine hands paths over absolute.
function project(on: any, files: Record<string, unknown>) {
  const get = (path: string) => files[path.replace(/^.*\.agentex\//, '')]
  on('fs.list', (_: any, e: any) => {
    const names = Object.keys(files).filter(p => p.startsWith('status/')).map(p => p.slice('status/'.length))
    if (!e.path.endsWith('.agentex/status') || !names.length) return { deny: 'ENOENT' }
    return { value: names.map(name => ({ name, kind: 'file', size: 1, mtimeMs: NOW, isLink: false })) }
  })
  on('fs.read', (_: any, e: any) => {
    const v = get(e.path)
    if (v === undefined) return { deny: 'ENOENT' }
    return { value: typeof v === 'string' ? v : JSON.stringify(v) }
  })
  on('fs.stat', (_: any, e: any) =>
    get(e.path) === undefined ? { deny: 'ENOENT' } : { value: { kind: 'file', size: 1, mtimeMs: NOW - 120_000, isLink: false } })
}

// Stands in for the surface: records the status line, toasts and pane opens, and answers /agentex:* commands.
function surface(on: any, isPlaced = true) {
  const seen = { status: [] as (string | undefined)[], toasts: [] as string[], opens: 0, ran: [] as string[] }
  on('command.register', (_: any, e: any) => ({ value: { command: e.name } }))
  on('command.run', (_: any, e: any) => (seen.ran.push(e.command), {}))
  on('ui.status', (_: any, e: any) => (seen.status.push(e.text), { value: undefined }))
  on('ui.toast', (_: any, e: any) => (seen.toasts.push(e.text), { value: undefined }))
  on('ui.open', () => ((seen.opens += 1), { value: isPlaced ? { isPlaced: true } : { isPlaced: false, reason: 'no-surface' } }))
  return seen
}

const parse = (files: Record<string, any>, stamp: number | null = null) =>
  sortChecks(Object.entries(files).flatMap(([p, d]) => toCheck(d, p, stamp) ?? []))

test('health: worst first, ages, stale results, missing checks, narrow rows', async () => {
  const checks = parse(MIXED)
  expect(checks.map(c => `${c.status} ${c.tool}`)).toEqual(['fail citations', 'fail review', 'warn numbers', 'ok preflight'])
  expect(text([checkRow(checks[2]!, NOW, 90)])).toMatch(/^! numbers +3 hand-typed numbers +1h$/)
  expect(text([checkRow(checks[3]!, NOW, 90)])).toMatch(/^✓ preflight .* 2d$/)
  expect(age(30_000)).toBe('now')
  expect(missing(checks)).toEqual(['build', 'cite-claims', 'provenance', 'repro', 'smoke', 'settings', 'consistency', 'figures', 'arxiv-html'])
  // all ok: no status line, nothing to toast
  const ok = parse({ a: result('figures', 'ok', 'all vector', 1), b: result('numbers', 'ok', 'in sync', 1) })
  expect(statusText(ok)).toBe(undefined)
  expect(statusText(checks)).toBe('AgenTeX ✗ 2 failing · ! 1 to check · /agentex')
  // the same tool in the repo root and in paper/: the newer result wins
  const twice = parse({ root: result('figures', 'fail', 'old', 90), paper: result('figures', 'ok', 'new', 1) })
  expect(newestPerTool(twice).map(c => c.summary)).toEqual(['new'])
  // stale: the sources changed (compile loop stamp, epoch s) after the check ran
  const [stale] = parse({ a: result('numbers', 'ok', 'in sync', 120) }, (NOW - 60 * 60_000) / 1000)
  expect(stale!.stale).toBe(true)
  expect(text([checkRow(stale!, NOW, 90)])).toMatch(/2h stale$/)
  // narrow: the summary goes, glyph + name + age stay; items are clipped to the width
  expect(text([checkRow(checks[0]!, NOW, 24)])).toBe('✗ citations 3m')
  expect(text(itemRows(checks[0]!, 20))).toBe('    refs.bib:12  sm…')
  // junk and partial writes are skipped, not drawn
  expect(toCheck({ status: 'toString' }, 'x', null)).toBe(null)
  expect(toCheck(undefined, 'x', null)).toBe(null)
  expect(toCheck({ status: 'ok', updated: 'yesterday' }, 'figures', null)).toMatchObject({ tool: 'figures', updated: null })
})

test('health: the compile loop state is the build row; flips and toasts', async () => {
  expect(buildCheck({ stamp: 1 }, NOW)).toBe(null) // SessionStart stamp only: no build yet
  expect(buildCheck({ stamp: 1, problems: { 'main.tex': [] }, blocks: 0 }, NOW)).toMatchObject({ status: 'ok', summary: '1 document compile' })
  const broken = buildCheck({ problems: { 'main.tex': ['undefined reference: sec:x'] }, blocks: 2 }, NOW)!
  expect(broken).toMatchObject({ status: 'fail', items: [{ where: 'main.tex', message: 'undefined reference: sec:x' }] })
  expect(buildCheck({ problems: { 'main.tex': ['undefined citation: a'] }, blocks: 0 }, NOW)!.status).toBe('warn')
  expect(buildCheck({ problems: {}, blocks: 0, built_at: 1000 }, NOW)!.updated).toBe(1_000_000) // dated by the build, not the file
  const before = parse({ a: result('citations', 'ok', 'all verified') })
  const after = parse({ a: result('citations', 'fail', '1 retracted') })
  expect(flips(undefined, after)).toEqual([]) // first scan of a session: a baseline, no toast
  expect(flips(before, after).map(c => c.tool)).toEqual(['citations'])
  expect(flips(after, after)).toEqual([])
  expect(toastText(flips(before, after))).toBe('✗ citations now failing: 1 retracted · /agentex')
  expect(toastText([broken, ...after])).toBe('✗ build, citations now failing · /agentex')
})

test('/agentex opens the pane: rows worst first, Enter on a row shows its file:line items', async ($, on) => {
  mock.clock(on, { now: NOW })
  mock.store(on, { welcomed: true })
  mock.env(on, {})
  project(on, { ...MIXED, 'build-state.json': { stamp: 0, problems: { 'main.tex': [] }, blocks: 0 } })
  const seen = surface(on)
  engine(on)
  await $.command.run({ command: 'agentex' })
  expect(seen.opens).toBe(1)
  for (const where of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'agentex', surface: where, ...PANE })
    expect((await ui.find({ type: 'Text', text: /paper health/ }))).toBeDefined()
    expect((await ui.find({ type: 'Text', text: /2 failing · 1 to check · 2 ok · 8 not run/ }))).toBeDefined()
    const rows = (await ui.findAll({ type: 'Button' })).map(b => b.key)
    expect(rows).toEqual(['row:citations', 'row:review', 'row:numbers', 'row:build', 'row:preflight', 'check', 'health'])
    expect(await ui.find({ type: 'Text', text: /not run yet: cite-claims · provenance/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /refs\.bib:12/ })).toBeUndefined()
    await ui.press({ key: 'row:citations' })
    expect(await ui.find({ type: 'Text', text: /refs\.bib:12  smith2020 was retracted/ })).toBeDefined()
    await ui.press({ key: 'row:citations' }) // pressed again: closed
    expect(await ui.find({ type: 'Text', text: /refs\.bib:12/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('pane: no results yet says so, and every check is in the dimmed not-run group', async ($, on) => {
  mock.clock(on, { now: NOW })
  mock.store(on, { welcomed: true })
  mock.env(on, {})
  project(on, {})
  const seen = surface(on)
  engine(on)
  await $.command.run({ command: 'agentex' })
  const ui = await $.ui.mount({ plugin: 'agentex', surface: 'terminal', ...PANE })
  expect(await ui.find({ type: 'Text', text: /No AgenTeX check has written a result/ })).toBeDefined()
  const notRun = await ui.find({ type: 'Text', text: /not run yet: build · preflight · citations/ })
  expect(notRun?.props.dimColor).toBe(true)
  expect((await ui.findAll({ type: 'Button' })).map(b => b.key)).toEqual(['check', 'health'])
  await ui.press({ key: 'check' }) // the quick action queues /agentex:check
  expect(seen.ran).toContain('agentex:check')
})

test('pane: a narrow pane drops summaries; NO_COLOR drops colour but keeps the glyphs', async ($, on) => {
  mock.clock(on, { now: NOW })
  mock.store(on, { welcomed: true })
  mock.env(on, { NO_COLOR: '1' })
  project(on, MIXED)
  surface(on)
  engine(on)
  await $.command.run({ command: 'agentex' })
  const ui = await $.ui.mount({ plugin: 'agentex', surface: 'terminal', ...PANE, props: { ...PANE.props, bodyColumns: 26 } })
  const row = await ui.find({ key: 'row:citations' })
  expect(row?.text).toBe('✗ citations 3m')
  const glyph = await ui.find({ type: 'Text', text: '✗ ' })
  expect(glyph?.props.color).toBeUndefined()
})

test('status line follows the results; a new failure toasts once, rate-limited', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { welcomed: true })
  mock.env(on, {})
  const files: Record<string, unknown> = { 'status/citations.json': result('citations', 'ok', 'all verified', 1) }
  project(on, files)
  const seen = surface(on)
  engine(on)
  await $.prompt.submit({ text: 'hello' } as any) // first scan: the baseline
  expect(seen.status.at(-1)).toBe(undefined)
  expect(seen.toasts).toEqual([])
  files['status/citations.json'] = result('citations', 'fail', '1 retracted reference', 0)
  await $.tool.call({ tool: 'Bash', command: 'python3 cite_verify.py paper/' } as any) // AgenTeX work: rescan after it
  expect(seen.toasts).toEqual(['✗ citations now failing: 1 retracted reference · /agentex'])
  expect(seen.status.at(-1)).toBe('AgenTeX ✗ 1 failing · /agentex')
  files['status/figures.json'] = result('figures', 'fail', 'raster figure', 0)
  await clock.advance(30_000) // the periodic scan sees it, but a minute has not passed: no second toast
  expect(seen.toasts.length).toBe(1)
  expect(seen.status.at(-1)).toBe('AgenTeX ✗ 2 failing · /agentex')
  files['status/numbers.json'] = result('numbers', 'fail', 'stale table', 0)
  await clock.advance(60_000)
  expect(seen.toasts.at(-1)).toBe('✗ numbers now failing: stale table · /agentex')
})

test('animations off: no band, status line or toasts, but /agentex still opens the pane', { options: { animations: false } }, async ($, on) => {
  mock.clock(on, { now: NOW })
  mock.store(on)
  mock.env(on, {})
  const files: Record<string, unknown> = { 'status/citations.json': result('citations', 'ok', 'all verified', 1) }
  project(on, files)
  const seen = surface(on)
  engine(on)
  await $.prompt.submit({ text: 'hello' } as any)
  files['status/citations.json'] = result('citations', 'fail', '1 retracted reference', 0)
  await $.tool.call({ tool: 'Bash', command: 'python3 cite_verify.py paper/' } as any)
  expect(seen.toasts).toEqual([])
  expect(seen.status).toEqual([])
  await $.command.run({ command: 'agentex' })
  const ui = await $.ui.mount({ plugin: 'agentex', surface: 'terminal', ...PANE })
  expect(await ui.find({ key: 'row:citations' })).toBeDefined()
})

test('/agentex prints the health where no surface can place a pane', async ($, on) => {
  mock.clock(on, { now: NOW })
  mock.store(on, { welcomed: true })
  mock.env(on, {})
  project(on, MIXED)
  surface(on, false)
  engine(on)
  const out = await $.command.run({ command: 'agentex' })
  expect(out.text).toBe(plainText(parse(MIXED), NOW))
  expect(out.text).toContain('✗ citations   1 retracted reference: smith2020')
  expect(out.text).toContain('not run yet: build · cite-claims')
})

test('the band animates while an AgenTeX script runs, and clears after', async ($, on) => {
  mock.clock(on)
  mock.store(on, { welcomed: true })
  let during: unknown
  engine(on, async () => {
    const ui = await $.ui.mount({ plugin: 'agentex', surface: 'terminal', ...BAND })
    during = await ui.find({ type: 'Text', text: /verifying citations/ })
    await ui.unmount()
  })
  await $.tool.call({ tool: 'Bash', command: 'python3 cite_verify.py paper/' })
  expect(during).toBeDefined()
  const after = await $.ui.mount({ plugin: 'agentex', surface: 'terminal', ...BAND })
  expect(await after.find({ type: 'Text', text: /verifying citations/ })).toBeUndefined()
})

test('other commands draw nothing', async ($, on) => {
  mock.clock(on)
  mock.store(on, { welcomed: true })
  let during: unknown = 'unset'
  engine(on, async () => {
    const ui = await $.ui.mount({ plugin: 'agentex', surface: 'terminal', ...BAND })
    during = await ui.find({ type: 'Text', text: /Agen/ })
    await ui.unmount()
  })
  await $.tool.call({ tool: 'Bash', command: 'ls -la' })
  expect(during).toBeUndefined()
})

test('the welcome plays once, then never again', async ($, on) => {
  const clock = mock.clock(on)
  mock.store(on)
  engine(on)
  await $.prompt.submit({ text: 'hello' })
  await clock.advance(90 * 12)
  const ui = await $.ui.mount({ plugin: 'agentex', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /installed ✓/ })).toBeDefined()
  await clock.advance(90 * WELCOME_FRAMES)
  expect(await ui.find({ type: 'Text', text: /installed/ })).toBeUndefined()
  await $.prompt.submit({ text: 'again' })   // same session: no replay
  await clock.advance(90 * 12)
  expect(await ui.find({ type: 'Text', text: /installed/ })).toBeUndefined()
})

test('a later session (welcome already recorded) shows no welcome', async ($, on) => {
  const clock = mock.clock(on)
  mock.store(on, { welcomed: true })
  engine(on)
  await $.prompt.submit({ text: 'hello' })
  await clock.advance(90 * 12)
  const ui = await $.ui.mount({ plugin: 'agentex', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /installed/ })).toBeUndefined()
})

test('animations off in /config: nothing is drawn', { options: { animations: false } }, async ($, on) => {
  const clock = mock.clock(on)
  mock.store(on)
  engine(on)
  await $.prompt.submit({ text: 'hello' })
  await clock.advance(500)
  const ui = await $.ui.mount({ plugin: 'agentex', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /Agen/ })).toBeUndefined()
})
