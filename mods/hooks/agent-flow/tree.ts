import type { AgentInfo } from 'claude-code'

import type { FlowAgent } from '../../types'

export type FlowStatus = FlowAgent['status']

// One line of the pane: an agent at its depth under the agent that spawned it.
export type FlowRow = { agent: FlowAgent; depth: number }

export type FlowGlyphs = { marks: Record<FlowStatus, string>; branch: string; sep: string }

export const UNICODE_FLOW: FlowGlyphs = {
  marks: {
    pending: '·',
    running: '●',
    waiting: '◐',
    idle: '○',
    completed: '✓',
    failed: '✗',
    killed: '■',
  },
  branch: '└ ',
  sep: ' · ',
}

export const ASCII_FLOW: FlowGlyphs = {
  marks: {
    pending: '.',
    running: '*',
    waiting: '~',
    idle: 'o',
    completed: '+',
    failed: 'x',
    killed: '#',
  },
  branch: '`-',
  sep: ' | ',
}

const ACTIVE: ReadonlySet<FlowStatus> = new Set(['pending', 'running', 'waiting'])

export const isActive = (status: FlowStatus): boolean => ACTIVE.has(status)

// The first line of a progress summary that says something, else the description.
const firstLine = (text: string): string =>
  text
    .split('\n')
    .map(line => line.trim())
    .find(line => line.length > 0) ?? ''

// Only what the pane draws, so a snapshot compares equal when nothing it shows moved.
export function toFlowAgent(info: AgentInfo): FlowAgent {
  const description = info.description.trim()
  const label = firstLine(info.label)

  return {
    id: info.id,
    ...(info.parentId === undefined ? {} : { parentId: info.parentId }),
    type: info.type,
    description,
    ...(label.length > 0 && label !== description ? { label } : {}),
    status: info.status,
    startTime: info.startTime,
    tokens: info.tokenCount,
  }
}

// Depth-first by start time; an agent whose parent is not listed sits at the top.
export function flowRows(agents: readonly FlowAgent[]): FlowRow[] {
  const ids = new Set(agents.map(agent => agent.id))
  const children = new Map<string | undefined, FlowAgent[]>()

  for (const agent of agents) {
    const parent = agent.parentId !== undefined && ids.has(agent.parentId) ? agent.parentId : undefined
    const list = children.get(parent) ?? []

    list.push(agent)
    children.set(parent, list)
  }

  const rows: FlowRow[] = []
  const seen = new Set<string>()
  const walk = (parent: string | undefined, depth: number) => {
    const list = [...(children.get(parent) ?? [])].sort((a, b) => a.startTime - b.startTime)

    for (const agent of list) {
      // A parent cycle in a bad reading must not loop.
      if (seen.has(agent.id)) continue
      seen.add(agent.id)
      rows.push({ agent, depth })
      walk(agent.id, depth + 1)
    }
  }

  walk(undefined, 0)

  return rows
}

export function elapsedText(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000))

  if (seconds < 60) return `${seconds}s`

  const minutes = Math.floor(seconds / 60)

  if (minutes < 60) return `${minutes}m${String(seconds % 60).padStart(2, '0')}s`

  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}m`
}

// The unit is picked after rounding, so 9,999 reads 10k and 999,600 reads 1.0M.
export function tokensText(tokens: number): string {
  if (tokens < 1000) return `${tokens}`

  const thousands = tokens / 1000

  if (Math.round(thousands * 10) < 100) return `${thousands.toFixed(1)}k`
  if (Math.round(thousands) < 1000) return `${Math.round(thousands)}k`

  return `${(tokens / 1_000_000).toFixed(1)}M`
}

export function summaryText(agents: readonly FlowAgent[], glyphs: FlowGlyphs): string {
  const active = agents.filter(agent => isActive(agent.status)).length
  const failed = agents.filter(agent => agent.status === 'failed' || agent.status === 'killed').length
  const parts = [`${active} running`, `${agents.length - active - failed} done`]

  if (failed > 0) parts.push(`${failed} failed`)

  return parts.join(glyphs.sep)
}

// The agents of a new reading, each carrying the end time an earlier reading
// stamped. The readings run every tick of the session, so an agent seen ending
// is stamped within a tick of it; one already ended at its first reading (it
// ended before this load read anything) gets no end time: its time is unknown.
export function mergeAgents(previous: readonly FlowAgent[], infos: readonly AgentInfo[], now: number): FlowAgent[] {
  const before = new Map(previous.map(agent => [agent.id, agent]))

  return infos.map(info => {
    const agent = toFlowAgent(info)
    const seen = before.get(agent.id)

    if (isActive(agent.status) || seen === undefined) return agent

    const endTime = seen.endTime ?? (isActive(seen.status) ? now : undefined)

    return endTime === undefined ? agent : { ...agent, endTime }
  })
}

// An agent's elapsed time: up to now while it runs, up to its stamped end once
// it ended; unknown for one that ended unseen.
export function elapsedOf(agent: FlowAgent, now: number): number | undefined {
  if (isActive(agent.status)) return now - agent.startTime

  return agent.endTime === undefined ? undefined : agent.endTime - agent.startTime
}

// The lines one row draws: a running agent's progress line is a second one.
export const linesOf = (row: FlowRow): number => (isActive(row.agent.status) && row.agent.label !== undefined ? 2 : 1)

// The rows that fit in `room` lines, tree order kept: finished agents give way
// first, the earliest started first, then the earliest rows of what is left.
export function fitRows(rows: readonly FlowRow[], room: number): FlowRow[] {
  const total = (list: readonly FlowRow[]) => list.reduce((sum, row) => sum + linesOf(row), 0)
  let kept = [...rows]
  const finished = rows
    .filter(row => !isActive(row.agent.status))
    .sort((a, b) => a.agent.startTime - b.agent.startTime)

  for (const row of finished) {
    if (total(kept) <= room) break
    kept = kept.filter(one => one !== row)
  }

  while (kept.length > 0 && total(kept) > room) kept = kept.slice(1)

  return kept
}
