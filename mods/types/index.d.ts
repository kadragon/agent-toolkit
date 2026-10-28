export type CiState = 'pending' | 'success' | 'failure' | 'none'

// Where a task-next/task-new cycle stands on the branch, as the dev plugin's
// own scripts report it: nothing when no contract is archived for the branch.
export type Cycle = {
  // The contract's `**Tag:**` value, `[FEAT]` and the like, when it names one.
  tag?: string
  // The `# ` heading a contract copied from tasks.md carries, when there is one.
  title?: string
  // The `**Acceptance criteria:**` checkboxes.
  criteria: number
  // Validation runs recorded beside the contract.
  evidence: number
  // Every recorded run's tree still matches the index: false with none recorded.
  isEvidenceCurrent: boolean
  hasNotes: boolean
  // The open PR for the branch, once one is read.
  pr?: { number: number; ci: CiState; strikes: number }
}

// What the queue holds, as task-next's candidate script counts it.
export type Queue = {
  // Candidate groups a `--full-scan` lists.
  groups: number
  // Open items a blocked/deferred marker parks.
  parked: number
}

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
  // The MCP servers connected: one that needs a sign-in is not counted.
  mcp?: number
  // A harness-curate run is due in this repo, as the dev plugin judges it.
  curateDue?: boolean
  // The cycle on the branch; null once read and found none.
  cycle?: Cycle | null
  // The queue's depth; null once read and found no backlog.
  queue?: Queue | null
}

declare module 'claude-code' {
  interface PluginState {
    mods: { statusBand: StatusBand | null }
  }
}
