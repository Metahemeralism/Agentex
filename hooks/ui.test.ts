// Run: claude plugin test .
import { expect, mock, test } from 'claude-code/testing'

import { activityRows, labelFor, logo, welcomeRows, WELCOME_FRAMES } from './frames'

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
