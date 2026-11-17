import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { AgentInfo, On } from 'claude-code'

// The test runtime has timers, but the module's types (no DOM, no Node) do not declare them.
declare const setTimeout: (callback: () => void, ms: number) => unknown

const NOW = Date.parse('2026-11-17T12:00:00Z')
// The status band reads git, settings and more at session start: off here.
const OPTIONS = { options: { statusBandEnabled: false } }
const PANE = {
  plugin: 'mods',
  component: 'Pane',
  requestId: 'agent-flow',
  props: {
    title: 'Agent flow',
    isFocused: false,
    bodyColumns: 80,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const

const info = (id: string, extra: Partial<AgentInfo> = {}): AgentInfo => ({
  id,
  description: `task ${id}`,
  type: 'Explore',
  status: 'running',
  kind: 'local_agent',
  taskStatus: 'running',
  label: `task ${id}`,
  startTime: NOW - 65_000,
  cwd: '/work',
  tokenCount: 12_300,
  tokenSamples: [],
  hasRow: true,
  ...extra,
})

type World = {
  agents: AgentInfo[]
  now: number
  ticks: (() => void)[]
  opened: string[]
  commands: string[]
  reads: number
}

const world = (on: On): World => {
  const state: World = { agents: [], now: NOW, ticks: [], opened: [], commands: [], reads: 0 }

  on('command.register', async ($, e) => {
    state.commands.push(e.name)

    return { value: { command: e.name } }
  })
  on('ui.open', async ($, e) => {
    state.opened.push(e.id)

    return { value: { isPlaced: true } }
  })
  on('ui.panes', async () => ({ value: [] }))
  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('agent.list', async () => {
    state.reads += 1

    return { value: state.agents }
  })
  on('clock.now', async () => ({ value: state.now }))
  on('agent.spawn', async () => ({ model: 'claude-haiku-5-5', agentId: 'a' }))
  // A period ends when the test says so.
  on('clock.every', async () => {
    await new Promise<void>(resolve => state.ticks.push(resolve))

    return { value: undefined }
  })

  return state
}

const settle = () => new Promise<void>(resolve => setTimeout(resolve, 20))

const start = ($: Engine) => $.session.start({ cwd: '/work', surface: 'terminal', isInteractive: true })

const open = async ($: Engine) => {
  await start($)
  await $.command.run({
    command: 'flow',
    args: '',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 200 },
  })
  await settle()
}

const texts = async ($: Engine, surface: 'terminal' | 'desktop' = 'terminal') => {
  const ui = await $.ui.mount({ ...PANE, surface })
  const found = (await ui.findAll({ type: 'Text' })).map(text => text.text)

  await ui.unmount()

  return found
}

test('/flow opens the pane with the agents as a tree, on every surface', OPTIONS, async ($, on) => {
  const state = world(on)

  state.agents = [
    info('a', { description: 'map the mods', label: 'reading band.tsx' }),
    info('a1', { parentId: 'a', type: 'general-purpose', startTime: NOW - 10_000, tokenCount: 800 }),
    info('b', { status: 'completed', startTime: NOW - 5_000 }),
  ]
  await open($)

  expect(state.commands).toContain('flow')
  expect(state.opened).toEqual(['agent-flow'])

  for (const surface of ['terminal', 'desktop'] as const) {
    const lines = await texts($, surface)

    expect(lines).toContain('2 running · 1 done')
    expect(lines.find(line => line.includes('map the mods'))).toBe('● Explore · map the mods 1m05s · 12k tok')
    expect(lines).toContain('  reading band.tsx')
    expect(lines.find(line => line.includes('task a1'))).toBe('└ ● general-purpose · task a1 10s · 800 tok')
    // It ended before anything read it: its time is unknown.
    expect(lines.find(line => line.includes('task b'))).toBe('✓ Explore · task b 12k tok')
  }
})

test('the pane says so when the session has no subagents', OPTIONS, async ($, on) => {
  world(on)
  await open($)

  expect(await texts($)).toEqual(['No subagents in this session yet.'])
})

test('after a spawn a tick reads with the pane closed, so an unwatched end is stamped', OPTIONS, async ($, on) => {
  const state = world(on)

  await start($)
  state.ticks.shift()?.()
  await settle()

  // No agent spawned yet: nothing polls.
  expect(state.reads).toBe(0)

  state.agents = [info('a')]
  await $.agent.spawn({
    tool_use_id: 'toolu_1',
    prompt: 'map the mods',
    description: 'task a',
    subagentType: 'Explore',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-opus-5-5',
    background: false,
    fork: false,
  })
  await settle()
  state.ticks.shift()?.()
  await settle()

  expect(state.reads).toBe(2)

  state.agents = [info('a', { status: 'completed' })]
  state.now = NOW + 2000
  state.ticks.shift()?.()
  await settle()
  state.now = NOW + 60 * 60_000
  await open($)

  expect((await texts($)).find(line => line.includes('task a'))).toBe('✓ Explore · task a 1m07s · 12k tok')
})

test('a pane too short for the tree keeps the running agents', OPTIONS, async ($, on) => {
  const state = world(on)

  state.agents = [
    info('old', { status: 'completed', startTime: NOW - 90_000 }),
    info('a', { label: 'reading band.tsx' }),
    info('b', { label: 'writing tree.ts' }),
  ]
  await open($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: { ...PANE.props, scroll: { offset: 0, bodyRows: 6 } } })
  const lines = (await ui.findAll({ type: 'Text' })).map(text => text.text)

  await ui.unmount()

  expect(lines.some(line => line.includes('task old'))).toBe(false)
  expect(lines).toContain('  writing tree.ts')
  expect(lines).toContain('  reading band.tsx')
})

test('the ASCII setting draws plain marks', { options: { ...OPTIONS.options, statusBandAscii: true } }, async ($, on) => {
  const state = world(on)

  state.agents = [info('a'), info('c', { parentId: 'a', status: 'failed' })]
  await open($)
  const lines = await texts($)

  expect(lines).toContain('1 running | 0 done | 1 failed')
  expect(lines.find(line => line.includes('task c'))?.startsWith('`-x Explore | task c')).toBe(true)
})

test('switched off, no /flow command is registered', { options: { ...OPTIONS.options, agentFlowEnabled: false } }, async ($, on) => {
  const state = world(on)

  await start($)

  expect(state.commands).not.toContain('flow')
})
