import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { FlowAgent } from '../../types'
import {
  ASCII_FLOW,
  elapsedOf,
  elapsedText,
  fitRows,
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

// What one load of the module keeps.
const live: { isEnabled: boolean; tick?: { cancel: () => void } } = { isEnabled: false }

// Never throws: a timer and a spawn hook start it unawaited.
export async function readAgents($: EngineInterface): Promise<void> {
  try {
    const infos = await $.agent.list()
    const now = await $.clock.now()

    await update($, flowAtom, previous => {
      // A slower read that started earlier does not move the reading back.
      if (previous !== null && now < previous.readAt) return previous

      const agents = mergeAgents(previous?.agents ?? [], infos, now)
      const isSame = previous !== null && JSON.stringify(previous.agents) === JSON.stringify(agents)

      // A still reading writes nothing, unless an agent runs and its time moves.
      if (isSame && !agents.some(agent => isActive(agent.status))) return previous

      return { agents, readAt: now }
    })
  } catch {
    // Nothing read: the pane keeps its last reading.
  }
}

// From the first spawn (or /flow) every tick reads, open pane or not, so an
// agent that ends unwatched is stamped within a tick of it; a session that
// starts no agent polls nothing, and a still reading writes nothing.
function startTick($: EngineInterface) {
  live.tick ??= $.clock.every(TICK_MS, () => void readAgents($))
}

// The engine takes one session.start hook per plugin, and register.ts holds it.
export async function startAgentFlow($: EngineInterface): Promise<void> {
  if (!live.isEnabled) return

  // A refused registration (a /clear raises the start again) must not fail the
  // plugin's one session.start hook.
  await $.command
    .register({ name: COMMAND, description: 'Show the subagents of this session as a live tree' })
    .catch(() => undefined)
}

export const register: Register = (on, options) => {
  live.isEnabled = options.agentFlowEnabled !== false
  if (!live.isEnabled) return

  const glyphs = options.statusBandAscii === true ? ASCII_FLOW : UNICODE_FLOW

  on('command.run', { command: COMMAND }, async $ => {
    startTick($)
    await readAgents($)
    await $.ui.open({ id: PANE, title: TITLE })

    return { text: 'Agent flow pane opened.' }
  })

  // A new agent shows at once, not on the next tick.
  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)

    startTick($)
    void readAgents($)

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
    // A tree taller than the pane drops finished agents first.
    const shown = fitRows(flowRows(agents), room)

    return (
      <Box flexDirection="column">
        <Text bold>{summaryText(agents, glyphs)}</Text>
        <Text> </Text>
        {shown.map(({ agent, depth }) => {
          const indent = depth === 0 ? '' : `${'  '.repeat(depth - 1)}${glyphs.branch}`
          const isDone = !isActive(agent.status)
          const elapsed = elapsedOf(agent, flow.readAt)
          const figures = `${elapsed === undefined ? '' : `${elapsedText(elapsed)}${glyphs.sep}`}${tokensText(agent.tokens)} tok`

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
