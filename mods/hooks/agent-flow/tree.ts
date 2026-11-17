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

export function tokensText(tokens: number): string {
  if (tokens < 1000) return `${tokens}`
  if (tokens < 1_000_000) return `${(tokens / 1000).toFixed(tokens < 10_000 ? 1 : 0)}k`

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
// stamped. One seen ended at its first reading is stamped then: its time runs a
// little long, never on.
export function mergeAgents(previous: readonly FlowAgent[], infos: readonly AgentInfo[], now: number): FlowAgent[] {
  const before = new Map(previous.map(agent => [agent.id, agent]))

  return infos.map(info => {
    const agent = toFlowAgent(info)

    if (isActive(agent.status)) return agent

    return { ...agent, endTime: before.get(agent.id)?.endTime ?? now }
  })
}

// An agent's elapsed time: up to now while it runs, frozen at the last reading
// that saw it run once it ended (the engine keeps no end time).
export const elapsedOf = (agent: FlowAgent, now: number): number => (agent.endTime ?? now) - agent.startTime
