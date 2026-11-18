// What the queue holds, as task-next's candidate script counts it.
export type Queue = {
  // Candidate groups a `--full-scan` lists.
  groups: number
  // Open items a blocked/deferred marker parks.
  parked: number
}

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

declare module 'claude-code' {
  interface PluginState {
    mods: {
      statusBand: StatusBand | null
      prRecap: Shaped<PrRecap | null>
      prRecapExplain: Shaped<PrRecapExplain | null>
      prRecapView: Shaped<PrRecapView | null>
    }
  }
}
