// State the AgenTeX UI module keeps for the session (drawn by the band above the prompt).
export type Activity = { label: string }

declare module 'claude-code' {
  interface PluginState {
    agentex: {
      /** AgenTeX work in flight (a script, the compile check), or null. */
      activity: Activity | null
      /** Animation tick while `activity` is set (100 ms each). */
      frame: number
      /** Welcome animation tick on first run, or null when it is not playing. */
      welcome: number | null
    }
  }
}
