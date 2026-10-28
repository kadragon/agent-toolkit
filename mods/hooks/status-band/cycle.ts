// Pure cycle reading: what the dev plugin's scripts print, parsed without `$`.

import type { CiState, Cycle, Queue } from '../../types'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const BASE_BRANCHES: readonly string[] = ['main', 'master']

// A cycle is keyed by its feature branch: the base branch holds none.
export const isFeatureBranch = (branch: string | undefined): branch is string =>
  branch !== undefined && branch !== '' && !BASE_BRANCHES.includes(branch)

// The checkboxes under `**Acceptance criteria:**`, as `cycle_state.py` counts
// them: up to the next `**Field:**` line or heading.
const CRITERIA_START = /^(?:\*\*Acceptance criteria(?::\*\*|\*\*:?)|#{1,6}\s+Acceptance criteria:?\s*$)/i
const FIELD = /^\*\*[^*]+:\*\*/
const CHECKBOX = /^\s*[-*+] \[[ xX]\]/

const countCriteria = (text: string): number => {
  const lines = text.split('\n')
  let total = 0

  lines.forEach((line, index) => {
    if (!CRITERIA_START.test(line.trim())) return

    for (const item of lines.slice(index + 1)) {
      if (FIELD.test(item.trim()) || item.startsWith('#')) break
      if (CHECKBOX.test(item)) total += 1
    }
  })

  return total
}

const tagOf = (text: string): string | undefined =>
  /^\*\*Tag:\*\*\s*(\[[A-Z]+\])/m.exec(text)?.[1]

const titleOf = (text: string): string | undefined =>
  /^#\s+(.+?)\s*$/m.exec(text)?.[1]

// What `cycle_state.py inspect` printed: null when the branch has no contract.
export const parseInspect = (stdout: string): Cycle | null => {
  const report: unknown = JSON.parse(stdout)

  if (!isRecord(report) || typeof report.contract !== 'string') return null

  const contract = report.contract
  const evidence = Array.isArray(report.evidence) ? report.evidence.length : 0

  return {
    tag: tagOf(contract),
    title: titleOf(contract),
    criteria: countCriteria(contract),
    evidence,
    isEvidenceCurrent: report.tree_matches_current === true,
    hasNotes: typeof report.notes === 'string' && report.notes.trim() !== '',
  }
}

// What `hub.sh pr-get` printed: the open PR's number, or none.
export const parsePr = (stdout: string): number | undefined => {
  const report: unknown = JSON.parse(stdout)

  if (!isRecord(report)) return undefined

  const number =
    typeof report.pr_number === 'number'
      ? report.pr_number
      : typeof report.pr_url === 'string'
        ? Number(report.pr_url.replace(/\/+$/, '').split('/').pop())
        : Number.NaN

  return Number.isInteger(number) && number > 0 ? number : undefined
}

// What `hub.sh ci-status` printed.
export const parseCiStatus = (stdout: string): CiState => {
  const report: unknown = JSON.parse(stdout)
  const status = isRecord(report) ? report.status : undefined

  return status === 'success' || status === 'failure' || status === 'pending' ? status : 'none'
}

// The strike file holds a count; missing or unreadable means none, as ci-wait reads it.
export const parseStrikes = (text: string | undefined): number => {
  const count = Number(text?.trim())

  return Number.isInteger(count) && count > 0 ? count : 0
}

// What `backlog_candidates.py --json` printed: the length of its array.
export const parseCount = (stdout: string): number => {
  const report: unknown = JSON.parse(stdout.trim() === '' ? '[]' : stdout)

  return Array.isArray(report) ? report.length : 0
}

export const queueOf = (groups: string, parked: string): Queue => ({
  groups: parseCount(groups),
  parked: parseCount(parked),
})

// A Bash command of the cycle's own: one that moves the contract, the
// branch, the PR or the queue, after which the figures are read again. The
// skills call the task-next scripts through `$STATE`, `$NODES` and
// `$CANDIDATES`, and save a contract under the `SPRINT_CONTRACT` delimiter.
const CYCLE_COMMAND =
  /cycle_state\.py|task_nodes\.py|backlog_candidates\.py|\$\{?(STATE|NODES|CANDIDATES)\b|SPRINT_CONTRACT|commit-and-push\.sh|ci-wait\.sh|merge-and-cleanup\.sh|hub\.sh|\bgit\s+(checkout|switch|commit|merge|push|stash)\b|backlog\.md|tasks\.md/

export const isCycleCommand = (command: string): boolean => CYCLE_COMMAND.test(command)

// A CI result worth a toast: the first reading that settles a pending run.
export const ciSettled = (before: CiState | undefined, after: CiState): boolean =>
  before === 'pending' && (after === 'success' || after === 'failure')
