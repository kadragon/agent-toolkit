// One /context breakdown row the bar draws: its tokens and the theme color
// /context draws it in; tool schemas loaded on demand are left out.
export type ContextPart = { kind: 'used' | 'free' | 'buffer'; tokens: number; color: string }

export type StatusBand = {
  model: string
  effort?: string | number
  cwd: string
  branch?: string
  startedAt?: number
  now: number
  contextPercent?: number
  // What fills the window, row by row as /context lists them.
  contextParts?: ContextPart[]
  rateLimits: { kind: string; percentUsed: number; resetsAt?: string }[]
  // When the prompt cache lapses unless a response renews it first.
  cacheExpiresAt?: number
  // The model that cache was made under: a switch forfeits it.
  cacheModel?: string
  hooks?: number
  skills?: { count: number; tokens: number }
  // The MCP servers connected: one that needs a sign-in is not counted.
  mcp?: number
  // A harness-curate run is due in this repo, as the dev plugin judges it.
  curateDue?: boolean
}

// One subagent as the agent-flow pane draws it, from `$.agent.list()`.
export type FlowAgent = {
  id: string
  parentId?: string
  type: string
  description: string
  // The first line of its latest progress summary, where it differs from the description.
  label?: string
  status: 'pending' | 'running' | 'waiting' | 'idle' | 'completed' | 'failed' | 'killed'
  startTime: number
  // Stamped by the first reading that saw it ended.
  endTime?: number
  tokens: number
}

// The agent-flow pane's last reading.
export type AgentFlow = { agents: FlowAgent[]; readAt: number }

declare module 'claude-code' {
  interface PluginState {
    mods: {
      statusBand: StatusBand | null
      agentFlow: Shaped<AgentFlow | null>
    }
  }
}
