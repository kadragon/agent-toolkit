export type StatusBand = {
  model: string
  effort?: string | number
  cwd: string
  branch?: string
  startedAt?: number
  now: number
  contextPercent?: number
  rateLimits: { kind: string; percentUsed: number; resetsAt?: string }[]
  // When the prompt cache lapses unless a response renews it first.
  cacheExpiresAt?: number
  // The model that cache was made under: a switch forfeits it.
  cacheModel?: string
  hooks?: number
  skills?: { count: number; tokens: number }
  // The MCP servers whose tools the context carries.
  mcp?: number
  // A harness-curate run is due in this repo, as the dev plugin judges it.
  curateDue?: boolean
}

declare module 'claude-code' {
  interface PluginState {
    mods: { statusBand: StatusBand | null }
  }
}
