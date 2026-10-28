// AgenTeX's UI, cosmetic only (nothing else depends on it):
// - the band above the prompt: a one-time welcome after install, and a small animation while AgenTeX work runs;
// - /agentex: the paper health pane, one row per check, worst first, Enter on a row shows its file:line items;
// - a status line while a check fails or needs a look, and a toast when one starts failing.
// The band, status line and toasts follow the `animations` option; the pane opens only when asked.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Health } from '../types'
import { activityRows, BLUE, labelFor, welcomeRows, WELCOME_FRAMES, type Row } from './frames'
import {
  buildCheck, checkRow, flips, headerRows, itemRows, missing, newestPerTool, notRunRows, plainText, sections, sortChecks,
  statusText, toastText, toCheck,
} from './health'

const activity = atom({ plugin: 'agentex', key: 'activity' } as const, null)
const frame = atom({ plugin: 'agentex', key: 'frame' } as const, 0)
const welcome = atom({ plugin: 'agentex', key: 'welcome' } as const, null)
const health = atom({ plugin: 'agentex', key: 'health' } as const, null)
const opened = atom({ plugin: 'agentex', key: 'opened' } as const, null)

const PANE = 'agentex-health'
const STATUS_DIR = '.agentex/status' // relative to the session's working directory, the paper's project
const BUILD_STATE = '.agentex/build-state.json'
const SCAN_MS = 30_000 // also how often the pane's ages move on
const TOAST_GAP_MS = 60_000 // at most one "now failing" toast a minute

// Module variables reset on reload; what a drawing reads lives in $.state.
let running = 0 // AgenTeX tasks in flight; the band shows while any is
let ticker: { cancel: () => void } | null = null
let welcomeChecked = false
let started = false
let lastToast = -Infinity

async function begin($: EngineInterface, label: string) {
  running += 1
  await update($, frame, () => 0)
  await update($, activity, () => ({ label }))
  ticker ??= $.clock.every(100, () => void update($, frame, n => n + 1))
}

async function end($: EngineInterface) {
  running = Math.max(0, running - 1)
  if (running > 0) return
  ticker?.cancel()
  ticker = null
  await update($, activity, () => null)
}

async function maybeWelcome($: EngineInterface) {
  if (welcomeChecked) return
  welcomeChecked = true
  if (await $.store.get('welcomed')) return
  await $.store.set('welcomed', true) // first: an interrupted run must not replay forever
  let n = 0
  await update($, welcome, () => 0)
  const t = $.clock.every(90, () => {
    n += 1
    void update($, welcome, () => (n >= WELCOME_FRAMES ? null : n))
    if (n >= WELCOME_FRAMES) t.cancel()
  })
}

async function readJson($: EngineInterface, path: string): Promise<any> {
  try {
    return JSON.parse(await $.fs.read(path))
  } catch {
    return undefined // missing, or caught mid-write: the next scan reads it
  }
}

/** Re-read every check's result; with `ambient`, also update the status line and toast new failures. */
async function scan($: EngineInterface, ambient: boolean) {
  const build = await readJson($, BUILD_STATE)
  const stamp = typeof build?.stamp === 'number' ? build.stamp : null
  // Some checks keep their results next to the paper (cite_verify, preflight and figcheck use the paper's
  // folder), so read the session folder's status files and those one folder down, e.g. paper/.agentex/status.
  const subs = (await $.fs.list('.').catch(() => []))
    .filter(f => f.kind === 'dir' && !f.name.startsWith('.') && f.name !== 'node_modules')
  const dirs = [STATUS_DIR, ...subs.map(d => `${d.name}/${STATUS_DIR}`)]
  const paths = (await Promise.all(dirs.map(async d => (await $.fs.list(d).catch(() => []))
    .filter(f => f.kind === 'file' && f.name.endsWith('.json')).map(f => `${d}/${f.name}`)))).flat()
  const read1 = async (path: string) => toCheck(await readJson($, path), path.split('/').pop()!.slice(0, -5), stamp)
  const checks = newestPerTool((await Promise.all(paths.map(read1))).flatMap(c => c ?? []))
  if (!checks.some(c => c.tool === 'build')) {
    const mtime = (await $.fs.stat(BUILD_STATE).catch(() => null))?.mtimeMs ?? null
    const b = buildCheck(build, mtime)
    if (b) checks.push(b)
  }
  const now = await $.clock.now()
  const prev = await read($, health)
  const next: Health = { checks: sortChecks(checks), scannedAt: now }
  await update($, health, () => next)
  if (!ambient) return
  $.ui.status(statusText(next.checks))
  const flipped = flips(prev?.checks, next.checks)
  if (flipped.length && now - lastToast >= TOAST_GAP_MS) {
    lastToast = now
    $.ui.toast(toastText(flipped))
  }
}
const rescan = ($: EngineInterface, ambient: boolean) => scan($, ambient).catch(() => {}) // never fail a hook over the UI

// One row of segments as Text; NO_COLOR drops the colour, the glyphs and words still say it all.
const segs = (Text: any, row: Row, noColor: boolean) =>
  row.map((s, j) => (
    <Text key={`s${j}`} color={noColor ? undefined : s.color} bold={s.bold} dimColor={s.dim}>
      {s.text}
    </Text>
  ))

async function setup($: EngineInterface, ambient: boolean) {
  if (started) return
  started = true
  await $.command.register({ name: 'agentex', description: 'AgenTeX paper health: every check, worst first' }).catch(() => {})
  $.clock.every(SCAN_MS, () => void rescan($, ambient))
  await rescan($, ambient)
}

async function start($: EngineInterface, ambient: boolean) {
  await setup($, ambient)
  if (ambient) await maybeWelcome($)
}

export const register: Register = (on, options) => {
  const ambient = options.animations !== false // off in /config: no band, status line or toasts
  // Installed mid-session, the module may join after session.start: the first prompt covers that.
  // A UI hook must never block a prompt: on any failure, just continue.
  on('session.start', async ($, e, next) => (await start($, ambient), next(e))).catch(($, e, next) => next(e))
  on('prompt.submit', async ($, e, next) => (await start($, ambient), next(e))).catch(($, e, next) => next(e))

  on('command.run', { command: 'agentex' }, async $ => {
    await rescan($, ambient)
    const shown = await $.ui.open({ id: PANE, title: 'Paper health', focus: true })
    if (shown.isPlaced) return {}
    const last = await read($, health) // no surface draws panes here (e.g. claude -p): print it instead
    return { text: plainText(last?.checks ?? [], last?.scannedAt ?? 0) }
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const label = labelFor(e.command ?? '')
    if (!label) return next(e)
    if (ambient) await begin($, label)
    try {
      return await next(e)
    } finally {
      if (ambient) await end($)
      await rescan($, ambient) // AgenTeX scripts write their status files as they finish
    }
  }).catch(($, e, next) => next(e))

  // The compile loop is a command hook on Stop; animate only if it takes a noticeable time.
  on('classic.Stop', async ($, e, next) => {
    let shown = false
    const t = $.clock.after(600, () => {
      shown = true
      if (ambient) void begin($, 'typesetting · checking the build')
    })
    try {
      return await next(e)
    } finally {
      t.cancel()
      if (shown && ambient) await end($)
      await rescan($, ambient) // the build state it just wrote
    }
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (!ambient || e.props.hasSurvey) return next(e)
    const w = await read($, welcome)
    const a = await read($, activity)
    if (w === null && a === null) return next(e)
    const rows = w !== null ? welcomeRows(w) : activityRows(await read($, frame), a!.label)
    const noColor = Boolean(await $.env.get('NO_COLOR').catch(() => undefined))
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column" key="agentex">
        {rows.map((row, i) => (
          <Text key={`r${i}`}>{segs(Text, row, noColor)}</Text>
        ))}
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const last = await read($, health)
    const open = await read($, opened)
    const noColor = Boolean(await $.env.get('NO_COLOR').catch(() => undefined))
    const checks = last?.checks ?? []
    const cols = e.props.bodyColumns
    const notRun = missing(checks)
    const run = (command: string) => () => void $.command.run({ command }).catch(() => {})
    const line = (key: string, row: Row) => <Text key={key}>{segs(Text, row, noColor)}</Text>
    // A key hint: the key in the band's blue, what it does dimmed (the key letter alone carries it under NO_COLOR)
    const hint = (key: string, what: string) => [
      <Text key="k" bold color={noColor ? undefined : BLUE}>{key}</Text>,
      <Text key="w" dimColor>{` ${what}`}</Text>,
    ]
    return (
      <Box flexDirection="column">
        {headerRows(checks, cols).map((row, i) => line(`h${i}`, row))}
        {checks.length === 0 && (
          <Box marginTop={1}><Text dimColor>Nothing checked yet. Press c to run the cheap offline checks.</Text></Box>
        )}
        {sections(checks).map(sec => (
          <Box key={`sec:${sec.title}`} flexDirection="column" marginTop={1}>
            <Text bold dimColor={sec.title === 'Passing'}>{`${sec.title} (${sec.checks.length})`}</Text>
            {sec.checks.flatMap(c => [
              <Button key={`row:${c.tool}`} plain onPress={() => void update($, opened, t => (t === c.tool ? null : c.tool))}>
                {segs(Text, checkRow(c, last!.scannedAt, cols), noColor)}
              </Button>,
              ...(open === c.tool ? itemRows(c, cols).map((row, i) => line(`item:${c.tool}:${i}`, row)) : []),
            ])}
          </Box>
        ))}
        {notRun.length > 0 && (
          <Box key="notrun" flexDirection="column" marginTop={1}>
            <Text bold dimColor>{`Not run yet (${notRun.length})`}</Text>
            {notRunRows(notRun, cols).map((row, i) => line(`n${i}`, row))}
          </Box>
        )}
        <Box flexDirection="row" gap={3} marginTop={1}>
          <Button key="check" plain hotkey="c" onPress={run('agentex:check')}>{hint('c', 'run the cheap checks')}</Button>
          <Button key="health" plain hotkey="h" onPress={run('agentex:health')}>{hint('h', 'what to fix next')}</Button>
          {checks.length > 0 && <Text dimColor>↵ details</Text>}
        </Box>
      </Box>
    )
  })
}
