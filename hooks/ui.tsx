// AgenTeX's band above the prompt: a one-time welcome after install, and a small animation
// while AgenTeX work runs (its scripts, and the compile check its Stop hook does).
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import { activityRows, labelFor, welcomeRows, WELCOME_FRAMES } from './frames'

const activity = atom({ plugin: 'agentex', key: 'activity' } as const, null)
const frame = atom({ plugin: 'agentex', key: 'frame' } as const, 0)
const welcome = atom({ plugin: 'agentex', key: 'welcome' } as const, null)

// Module variables reset on reload; what the band draws lives in $.state.
let running = 0 // AgenTeX tasks in flight; the band shows while any is
let ticker: { cancel: () => void } | null = null
let welcomeChecked = false

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

export const register: Register = (on, options) => {
  if (options.animations === false) return // switched off in /config: register nothing
  // Installed mid-session, the module may join after session.start: the first prompt covers that.
  // A UI hook must never block a prompt: on any failure, just continue.
  on('session.start', async ($, e, next) => (await maybeWelcome($), next(e))).catch(($, e, next) => next(e))
  on('prompt.submit', async ($, e, next) => (await maybeWelcome($), next(e))).catch(($, e, next) => next(e))

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const label = labelFor(e.command ?? '')
    if (!label) return next(e)
    await begin($, label)
    try {
      return await next(e)
    } finally {
      await end($)
    }
  }).catch(($, e, next) => next(e))

  // The compile loop is a command hook on Stop; animate only if it takes a noticeable time.
  on('classic.Stop', async ($, e, next) => {
    let shown = false
    const t = $.clock.after(600, () => {
      shown = true
      void begin($, 'typesetting · checking the build')
    })
    try {
      return await next(e)
    } finally {
      t.cancel()
      if (shown) await end($)
    }
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const w = await read($, welcome)
    const a = await read($, activity)
    if (w === null && a === null) return next(e)
    const rows = w !== null ? welcomeRows(w) : activityRows(await read($, frame), a!.label)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column" key="agentex">
        {rows.map((row, i) => (
          <Text key={`r${i}`}>
            {row.map((s, j) => (
              <Text key={`s${j}`} color={s.color} bold={s.bold} dimColor={s.dim}>
                {s.text}
              </Text>
            ))}
          </Text>
        ))}
      </Box>
    )
  })
}
