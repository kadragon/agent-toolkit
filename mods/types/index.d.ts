export type NextSteps = { turnId: string; suggestions: string[] }

export type StatusBand = {
  model: string
  effort?: string | number
  cwd: string
  branch?: string
  startedAt?: number
  now: number
  contextPercent?: number
  rateLimits: { kind: string; percentUsed: number; resetsAt?: string }[]
}

declare module 'claude-code' {
  interface PluginState {
    mods: { nextSteps: NextSteps | null; statusBand: StatusBand | null }
  }
}
