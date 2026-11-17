import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { FlowAgent } from '../../types'
import {
  ASCII_FLOW,
  elapsedOf,
  elapsedText,
  flowRows,
  isActive,
  mergeAgents,
  summaryText,
  tokensText,
  UNICODE_FLOW,
} from './tree'

// A live tree of this session's subagents, after the agent-flow mod: `/flow`
// opens it; it reads `$.agent.list()` while open and draws from the reading.
export const PANE = 'agent-flow'
export const COMMAND = 'flow'
const TITLE = 'Agent flow'
const TICK_MS = 2000
// The pane's header and its blank line under it.
const HEADER_ROWS = 2

const flowAtom = atom({ plugin: 'mods', key: 'agentFlow' } as const, null, { shape: 'agent-flow-1' })

// Theme keys, as the status band colors its figures.
const COLORS: Record<FlowAgent['status'], string | undefined> = {
  pending: undefined,
  running: 'suggestion',
  waiting: 'warning',
  idle: undefined,
  completed: 'success',
  failed: 'error',
  killed: 'error',
}

// What one load of the module keeps; a reload asks the engine again whether the
// pane is open.
const live: { isEnabled: boolean; isOpen: boolean; tick?: { cancel: () => void } } = {
  isEnabled: false,
  isOpen: false,
}

export async function readAgents($: EngineInterface): Promise<void> {
  const infos = await $.agent.list().catch(() => undefined)

  if (infos === undefined) return

  const now = await $.clock.now()

  await update($, flowAtom, previous => {
    const agents = mergeAgents(previous?.agents ?? [], infos, now)
    const isSame = previous !== null && JSON.stringify(previous.agents) === JSON.stringify(agents)

    // A still reading writes nothing, unless an agent runs and its time moves.
    if (isSame && !agents.some(agent => isActive(agent.status))) return previous

    return { agents, readAt: now }
  })
}

function startTick($: EngineInterface) {
  live.tick ??= $.clock.every(TICK_MS, () => {
    if (live.isOpen) void readAgents($)
  })
}

// The engine takes one session.start hook per plugin, and register.ts holds it.
export async function startAgentFlow($: EngineInterface): Promise<void> {
  if (!live.isEnabled) return

  await $.command.register({ name: COMMAND, description: 'Show the subagents of this session as a live tree' })
  // After a reload the pane may still be open: keep reading for it.
  live.isOpen = (await $.ui.panes().catch(() => [])).some(pane => pane.id === PANE)
  startTick($)
}

export const register: Register = (on, options) => {
  live.isEnabled = options.agentFlowEnabled !== false
  if (!live.isEnabled) return

  const glyphs = options.statusBandAscii === true ? ASCII_FLOW : UNICODE_FLOW

  on('command.run', { command: COMMAND }, async $ => {
    live.isOpen = true
    startTick($)
    await readAgents($)
    await $.ui.open({ id: PANE, title: TITLE })

    return { text: 'Agent flow pane opened.' }
  })

  on('ui.close', async ($, e, next) => {
    if (e.id === PANE) live.isOpen = false

    return next(e)
  })

  // A new agent shows at once, not on the next tick.
  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)

    if (live.isOpen) void readAgents($)

    return started
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const flow = await read($, flowAtom)
    const agents = flow?.agents ?? []

    if (flow === null || agents.length === 0) {
      return (
        <Box flexDirection="column">
          <Text dimColor>No subagents in this session yet.</Text>
        </Box>
      )
    }

    const room = Math.max(1, (e.props.scroll?.bodyRows ?? e.viewport?.rows ?? 24) - HEADER_ROWS)
    const rows = flowRows(agents)
    // The newest rows win when the tree outgrows the pane.
    const shown = rows.length > room ? rows.slice(rows.length - room) : rows

    return (
      <Box flexDirection="column">
        <Text bold>{summaryText(agents, glyphs)}</Text>
        <Text> </Text>
        {shown.map(({ agent, depth }) => {
          const indent = depth === 0 ? '' : `${'  '.repeat(depth - 1)}${glyphs.branch}`
          const isDone = !isActive(agent.status)
          const figures = `${elapsedText(elapsedOf(agent, flow.readAt))}${glyphs.sep}${tokensText(agent.tokens)} tok`

          return (
            <Box key={agent.id} flexDirection="column">
              <Text wrap="truncate-end" dimColor={isDone && agent.status === 'completed'}>
                {indent}
                <Text color={COLORS[agent.status]}>{glyphs.marks[agent.status]}</Text> <Text bold>{agent.type}</Text>
                {glyphs.sep}
                {agent.description} <Text dimColor>{figures}</Text>
              </Text>
              {!isDone && agent.label !== undefined && (
                <Text wrap="truncate-end" dimColor>
                  {`${'  '.repeat(depth)}  ${agent.label}`}
                </Text>
              )}
            </Box>
          )
        })}
      </Box>
    )
  })
}
