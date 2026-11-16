// Pure queue reading: what the dev plugin's scripts print, parsed without `$`.

import type { Queue } from '../../types'

// What `backlog_candidates.py --json` printed: the length of its array.
export const parseCount = (stdout: string): number => {
  const report: unknown = JSON.parse(stdout.trim() === '' ? '[]' : stdout)

  return Array.isArray(report) ? report.length : 0
}

export const queueOf = (groups: string, parked: string): Queue => ({
  groups: parseCount(groups),
  parked: parseCount(parked),
})

// A Bash command that may move the queue: task-next's queue scripts, an
// edit of the backlog through the shell, or a git move that may bring
// another backlog in. The figures are read again after it.
const QUEUE_COMMAND =
  /task_nodes\.py|backlog_candidates\.py|\$\{?(NODES|CANDIDATES)\b|merge-and-cleanup\.sh|\bgit\s+(checkout|switch|commit|merge|pull|push|stash)\b|backlog\.md|tasks\.md/

export const isQueueCommand = (command: string): boolean => QUEUE_COMMAND.test(command)
