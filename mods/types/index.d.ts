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

export type FileChange = {
  path: string
  added: number
  deleted: number
  isBinary: boolean
}

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

export type NodeChange = 'added' | 'changed' | 'removed' | 'same'

// One box of the structure diagram, top to bottom in the order work flows.
export type ExplainNode = {
  name: string
  // What the PR did to it, or what it does here.
  note: string
  change: NodeChange
  // How it hands over to the next box; empty on the last.
  link: string
}

// What the model made of a PR: plain sentences and the diagram's boxes.
export type PrExplain = { summary: string; nodes: ExplainNode[] }

// The explanation of the latest PR, by its commit, as far as it has got.
export type PrRecapExplain = {
  sha: string
  status: 'pending' | 'ready' | 'failed'
  explain?: PrExplain
}

// The PR the pane shows, by its commit, and the latest PR when it was chosen;
// the latest is shown when unset.
export type PrRecapView = { sha: string; latest: string }

// One validation run recorded beside the contract.
export type ContractEvidence = { command: string; exitCode: number }

// One `**Acceptance criteria:**` checkbox, split at its arrow.
export type ContractCriterion = {
  text: string
  // What follows the arrow: the test, command or observation that proves it.
  check: string
  isChecked: boolean
  // The evidence records of the commands its check names, one per command found.
  evidence: number[]
  // The commands its check names that have no record.
  missing: number
}

// The branch's archived Sprint Contract as the contract pane draws it.
export type Contract = {
  branch: string
  title?: string
  tag?: string
  criteria: ContractCriterion[]
  evidence: ContractEvidence[]
  // Indexes of the records no criterion's check names.
  unnamed: number[]
  // Every recorded run's tree still matches the index: false with none recorded.
  isEvidenceCurrent: boolean
  hasNotes: boolean
}

// What the contract section read last: `contract` null with none archived,
// `reason` why there is none; `error` why the last reread failed, the
// contract before it kept.
export type ContractPane = { contract: Contract | null; readAt: number; reason?: string; error?: string }

declare module 'claude-code' {
  interface PluginState {
    mods: {
      contractPane: Shaped<ContractPane | null>
      statusBand: StatusBand | null
      prRecap: Shaped<PrRecap | null>
      prRecapExplain: Shaped<PrRecapExplain | null>
      prRecapView: Shaped<PrRecapView | null>
    }
  }
}
