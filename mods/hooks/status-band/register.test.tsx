import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

const NOW = Date.parse('2026-10-11T12:00:00Z')
const MINUTE = 60_000
const BAND = {
  plugin: 'mods',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 20,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 19 },
    view: {},
  },
} as const
const USAGE = {
  input_tokens: 1,
  output_tokens: 1,
  cache_read_input_tokens: 0,
  cache_creation_input_tokens: 0,
}

type World = {
  now: number
  model: string
  branch: string | null
  percent: number | undefined
  rateLimits: { kind: string; percentUsed: number; resetsAt?: string }[]
  isUsageDown: boolean
  ticks: (() => void)[]
  gitCalls: number
}

// The engine beneath the plugin: what the session, the clock, git and the band
// answer when no plugin does.
const world = (on: On): World => {
  const state: World = {
    now: NOW,
    model: 'claude-opus-5-5',
    branch: 'main',
    percent: 12,
    rateLimits: [
      { kind: 'five_hour', percentUsed: 88, resetsAt: new Date(NOW + 124 * MINUTE).toISOString() },
    ],
    isUsageDown: false,
    ticks: [],
    gitCalls: 0,
  }

  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('session.end', async () => ({ sessionId: 's1' }))
  on('session.measure', async ($, e) => ({ changed: e.changed }))
  on('session.model', async () => ({ value: state.model }))
  on('session.cwd', async () => ({ value: '/work/agent-toolkit' }))
  on('session.usage', async () => {
    if (state.isUsageDown) throw new Error('usage is down')

    return {
      value: {
        startedAt: NOW - 5 * MINUTE,
        context: { window: 200_000, percent: state.percent },
        rateLimits: state.rateLimits,
      },
    }
  })
  on('clock.now', async () => ({ value: state.now }))
  // A period ends when the test says so.
  on('clock.every', async () => {
    await new Promise<void>(resolve => state.ticks.push(resolve))

    return { value: undefined }
  })
  on('process.run', async () => {
    state.gitCalls += 1

    if (state.branch === null) throw new Error('git is not installed')

    return { value: { exitCode: 0, stdout: `${state.branch}\n`, stderr: '' } }
  })
  on('turn.step', async function* ($, e) {
    return { turnId: e.turnId, index: e.index, answer: 'ok', toolUses: [], usage: USAGE }
  })
  on('turn.start', async ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', async ($, e) => ({ text: e.answer }))
  on('model.complete', async () => ({
    value: { isAnswered: true, text: 'Run the tests', usage: USAGE },
  }))
  on('session.surfaces', async () => ({ value: ['terminal'] }))
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => {
    const { Box } = $.ui.resolve(e)

    return <Box key="engine-empty" />
  })

  return state
}

const start = ($: Engine, isInteractive = true) =>
  $.session.start({ cwd: '/work/agent-toolkit', surface: 'terminal', isInteractive })

// Reads the stream to its end, as the query loop does.
const step = async ($: Engine, fields: Record<string, unknown> = {}) => {
  const stream = $.turn.step({
    turnId: 't1',
    index: 0,
    model: 'claude-opus-5-5',
    effort: 'medium',
    messageCount: 1,
    ...fields,
  } as Parameters<Engine['turn']['step']>[0])

  let read = await stream.next()

  while (read.done !== true) read = await stream.next()

  return read.value
}

const measure = ($: Engine) =>
  $.session.measure({
    context: { window: 200_000, percent: 0 },
    rateLimits: [],
    changed: ['context'],
  })

const drawn = async ($: Engine, surface: 'terminal' | 'desktop' = 'terminal', props = {}) => {
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, ...props }, surface })
  const context = await ui.find({ type: 'Text', text: /^Context / })
  // A Text carries no key, so the rows are found by what they say.
  const texts = [
    (await ui.find({ type: 'Text', text: /⏱️/ }))?.text,
    context?.text,
    (await ui.find({ type: 'Text', text: /\d[hd]: / }))?.text,
  ]

  return { ui, texts, color: context?.props.color }
}

// Lets the work a tick started settle.
const settle = () => new Promise<void>(resolve => setTimeout(resolve, 20))

test('the band draws both rows on the terminal and the desktop', async ($, on) => {
  world(on)

  await start($)

  for (const surface of ['terminal', 'desktop'] as const) {
    const { ui, texts, color } = await drawn($, surface)

    expect(texts).toEqual([
      '[Opus 5.5] │ agent-toolkit git:(main) │ ⏱️  5m',
      'Context █░░░░░░░░░ 12%',
      ' │ 5h: 88% (2h 4m)',
    ])
    expect(color).toBe('success')
    await ui.unmount()
  }
})

test('it yields the band to a survey', async ($, on) => {
  world(on)

  await start($)
  const { ui, texts } = await drawn($, 'terminal', { hasSurvey: true })

  expect(texts).toEqual([undefined, undefined, undefined])
  expect(await ui.find({ key: 'engine-empty' })).toBeDefined()
  await ui.unmount()
})

test('it stays up while a turn runs', async ($, on) => {
  world(on)

  await start($)
  const { ui, texts } = await drawn($, 'terminal', { isWorking: true })

  expect(texts[0]).toContain('agent-toolkit')
  await ui.unmount()
})

test("a main-loop step shows its effort and a subagent's does not change it", async ($, on) => {
  world(on)

  await start($)
  const result = await step($)
  await step($, { agentId: 'agent-1', effort: 'low' })
  const { ui, texts } = await drawn($)

  expect(result.answer).toBe('ok')
  expect(texts[0]).toBe('[Opus 5.5 ◔ medium] │ agent-toolkit git:(main) │ ⏱️  5m')
  await ui.unmount()
})

test('a measurement redraws the figures and the branch', async ($, on) => {
  const state = world(on)

  await start($)
  state.percent = 91
  state.rateLimits = []
  state.branch = 'feat/x'
  const measured = await measure($)
  const { ui, texts, color } = await drawn($)

  expect(measured.changed).toEqual(['context'])
  expect(texts).toEqual([
    '[Opus 5.5] │ agent-toolkit git:(feat/x) │ ⏱️  5m',
    'Context █████████░ 91%',
    undefined,
  ])
  expect(color).toBe('error')
  await ui.unmount()
})

test('the clock tick moves the elapsed time', async ($, on) => {
  const state = world(on)

  await start($)
  state.now = NOW + 60 * MINUTE
  state.ticks.shift()?.()
  await settle()
  const { ui, texts } = await drawn($)

  expect(texts[0]).toContain('⏱️  1h 5m')
  expect(texts[2]).toBe(' │ 5h: 88% (1h 4m)')
  await ui.unmount()
})

test('a /clear keeps the tick and any other end stops it', async ($, on) => {
  const state = world(on)

  await start($)
  await $.session.end({ reason: 'clear' } as Parameters<Engine['session']['end']>[0])
  state.ticks.shift()?.()
  await settle()

  expect(state.ticks.length).toBe(1)

  await $.session.end({ reason: 'logout' } as Parameters<Engine['session']['end']>[0])
  const calls = state.gitCalls
  state.ticks.shift()?.()
  await settle()

  expect(state.ticks.length).toBe(0)
  expect(state.gitCalls).toBe(calls)
})

test('a failing git call or usage read leaves those figures out and fails nothing', async ($, on) => {
  const state = world(on)
  state.branch = null
  state.isUsageDown = true

  const started = await start($)
  const measured = await measure($)
  const { ui, texts } = await drawn($)

  expect(started.cwd).toBe('/work/agent-toolkit')
  expect(measured.changed).toEqual(['context'])
  expect(texts).toEqual(['[Opus 5.5] │ agent-toolkit │ ⏱️  <1m', 'Context ░░░░░░░░░░ 0%', undefined])
  await ui.unmount()
})

test('a run with nobody at the prompt reads nothing and starts no timer', async ($, on) => {
  const state = world(on)

  await start($, false)

  expect(state.ticks.length).toBe(0)
  expect(state.gitCalls).toBe(0)
})

test('with suggestions up, the status rows and the buttons are both drawn', async ($, on) => {
  world(on)

  await start($)
  await $.turn.complete({
    answer: 'I changed the parser and left the tests alone. '.repeat(4),
    durationMs: 10,
    isAborted: false,
    turnId: 't1',
    reason: 'answer',
  } as Parameters<Engine['turn']['complete']>[0])
  const { ui, texts } = await drawn($)

  expect(texts[0]).toContain('agent-toolkit')
  expect((await ui.find({ key: 'next-step-1' }))?.props.label).toBe('Run the tests')
  await ui.unmount()
})

test('switched off, it draws nothing and starts no timer', { options: { statusBandEnabled: false } }, async ($, on) => {
  const state = world(on)

  await start($)
  await step($)
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts).toEqual([undefined, undefined, undefined])
  expect(state.ticks.length).toBe(0)
  expect(state.gitCalls).toBe(0)
  await ui.unmount()
})
