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

export type FileKind = 'code' | 'test' | 'docs' | 'config'

export type FileChange = {
  path: string
  added: number
  deleted: number
  isBinary: boolean
  kind: FileKind
}

// The files of one PR under one directory, with their totals.
export type PrGroup = { dir: string; files: FileChange[]; added: number; deleted: number }

// One merged PR as the first-parent git log of HEAD records it.
export type Pr = {
  number: number
  sha: string
  // The `[FEAT]`-style tag the title opens with, without brackets.
  tag?: string
  title: string
  author: string
  mergedAt: number
  // The commit body's paragraphs, trailers dropped.
  summary: string[]
  files: FileChange[]
}

// What the pr-recap pane read last; `error` when git could not answer.
export type PrRecap = { prs: Pr[]; readAt: number; error?: string }

// What the person picked in the pane.
export type PrRecapView = {
  // The PR shown, by number; the newest when unset or gone.
  selected?: number
  // Directories opened to their files, keyed `<pr>:<dir>`.
  open: string[]
  isSummaryOpen: boolean
}

declare module 'claude-code' {
  interface PluginState {
    mods: {
      statusBand: StatusBand | null
      prRecap: Shaped<PrRecap | null>
      prRecapView: Shaped<PrRecapView>
    }
  }
}
