// State the AgenTeX UI module keeps for the session (drawn by the band above the prompt and the health pane).
export type Activity = { label: string }

export type CheckStatus = 'ok' | 'warn' | 'fail'
/** One AgenTeX check's latest result, read from .agentex/status/<tool>.json (or build-state.json). */
export type Check = {
  tool: string
  status: CheckStatus
  summary: string
  /** Up to 20 locations, `where` as file:line. */
  items: { where: string; message: string }[]
  /** When the check ran (epoch ms), or null when its file did not say. */
  updated: number | null
  /** The LaTeX sources changed after the check ran (per the compile loop's stamp). */
  stale: boolean
}
export type Health = { checks: Check[]; scannedAt: number }

declare module 'claude-code' {
  interface PluginState {
    agentex: {
      /** AgenTeX work in flight (a script, the compile check), or null. */
      activity: Activity | null
      /** Animation tick while `activity` is set (100 ms each). */
      frame: number
      /** Welcome animation tick on first run, or null when it is not playing. */
      welcome: number | null
      /** The last scan of the project's check results, worst first; null before the first scan. */
      health: Health | null
      /** The health pane row whose items are shown, by tool name, or null. */
      opened: string | null
    }
  }
}
