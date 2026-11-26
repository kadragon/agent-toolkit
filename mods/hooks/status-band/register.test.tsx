import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

// The test runtime has timers, but the module's types (no DOM, no Node) do not declare them.
declare const setTimeout: (callback: () => void, ms: number) => unknown

const NOW = Date.parse('2026-10-11T12:00:00Z')
const MINUTE = 60_000
const BAND = {
  plugin: 'mods',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isCollapsed: false,
    isWorking: false,
    maxRows: 20,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 19 },
    view: {},
  },
} as const
// A finished child's result, nothing cut off.
const ran = (exitCode: number, stdout: string) => ({
  value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})
const USAGE = {
  input_tokens: 1,
  output_tokens: 1,
  cache_read_input_tokens: 10,
  cache_creation_input_tokens: 0,
}

type World = {
  now: number
  model: string
  cwd: string
  branch: string | null
  percent: number | undefined
  rateLimits: { kind: string; percentUsed: number; resetsAt?: string }[]
  turns: number
  surfaces: ('terminal' | 'desktop' | 'vscode' | 'mobile')[]
  isUsageDown: boolean
  ticks: (() => void)[]
  gitCalls: number
  // Set to hold the next git call open until the test lets it go.
  gitGate?: Promise<void>
  settings: Record<string, unknown> | 'unreadable'
  files: Record<string, string>
  // What the environment holds; a name not listed is unset.
  env: Record<string, string>
  // How long the next responses take to come back.
  stepMs: number
  switchedTo?: string
  holdNextNow?: Promise<void>
  holdNextModel?: Promise<void>
  isModelDown?: boolean
  isUncached: boolean
  // What the curate check prints; null makes it fail to start.
  curateOut: string | null
  curateRuns: (readonly string[])[]
  sameDirectory: boolean
  // Set to hold the next curate check open until the test lets it go.
  curateGate?: Promise<void>
  // True where only `python` is installed.
  isPython3Missing: boolean
}

// On Windows the engine hands `fs` a POSIX path made absolute on the drive
// (`/home/me` as `C:\home\me`), so it is also compared without one. Elsewhere
// a Windows path arrives under the working directory, matched as written.
const comparable = (path: string): string => path.replace(/^[A-Za-z]:/, '').replace(/\\/g, '/')

const isFile = (path: string, file: string): boolean =>
  path === file ||
  path.endsWith(`/${file}`) ||
  comparable(path) === comparable(file) ||
  comparable(path).endsWith(`/${comparable(file)}`)

// The engine beneath the plugin: what the session, the clock, git and the band
// answer when no plugin does.
const world = (on: On): World => {
  const state: World = {
    now: NOW,
    model: 'claude-opus-5-5',
    cwd: '/work/agent-toolkit',
    branch: 'main',
    percent: 12,
    rateLimits: [
      { kind: 'five_hour', percentUsed: 88, resetsAt: new Date(NOW + 124 * MINUTE).toISOString() },
    ],
    turns: 3,
    surfaces: ['terminal'],
    isUsageDown: false,
    ticks: [],
    gitCalls: 0,
    settings: 'unreadable',
    files: {},
    env: { HOME: '/home/me' },
    stepMs: 0,
    isUncached: false,
    curateOut: '',
    curateRuns: [],
    sameDirectory: false,
    isPython3Missing: false,
  }

  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('session.measure', async ($, e) => ({ changed: e.changed }))
  on('session.attach', async ($, e) => ({ clientId: e.clientId }))
  on('session.detach', async ($, e) => ({ clientId: e.clientId }))
  on('session.end', async () => ({ sessionId: 's1' }))
  on('session.model', async () => {
    const gate = state.holdNextModel

    state.holdNextModel = undefined
    await gate

    if (state.isModelDown) throw new Error('model read is down')

    return { value: state.model }
  })
  on('session.cwd', async () => ({ value: state.cwd }))
  on('session.turns', async () => ({ value: state.turns }))
  on('session.usage', async () => {
    if (state.isUsageDown) throw new Error('usage is down')

    return {
      value: {
        startedAt: NOW - 5 * MINUTE,
        context: { window: 200_000, percent: state.percent },
        rateLimits: state.rateLimits,
      },
    } as never
  })
  on('settings.read', async () => {
    if (state.settings === 'unreadable') throw new Error('settings are down')

    return { value: state.settings }
  })
  on('env.get', async ($, e) => ({ value: state.env[e.name] }))
  // The engine makes a path absolute before it asks. A Windows path is not
  // absolute on the host these tests run on, so it arrives beneath the working
  // directory with its own separators intact, and is found by its tail.
  on('fs.read', async ($, e) => {
    const name = Object.keys(state.files).find(file => isFile(e.path, file))
    const text = name === undefined ? undefined : state.files[name]

    if (text === undefined) throw new Error(`no such file: ${e.path}`)

    return { value: text }
  })
  on('clock.now', async () => {
    const gate = state.holdNextNow

    state.holdNextNow = undefined
    await gate

    return { value: state.now }
  })
  // A period ends when the test says so.
  on('clock.every', async () => {
    await new Promise<void>(resolve => state.ticks.push(resolve))

    return { value: undefined }
  })
  on('fs.exists', async ($, e) => ({
    value: Object.keys(state.files).some(file => isFile(e.path, file)),
  }))
  on('process.run', async ($, e) => {
    if (e.argv[0] === 'git' && e.argv[1] === 'rev-parse') {
      return ran(0, '/work/agent-toolkit/.git\n')
    }

    if (e.argv[1] === '-c') return ran(state.sameDirectory ? 0 : 1, '')

    if (e.argv[0] !== 'git') {
      state.curateRuns.push(e.argv)
      const out = state.curateOut
      const gate = state.curateGate

      state.curateGate = undefined
      await gate

      if (out === null) throw new Error('python is not installed')
      if (state.isPython3Missing && e.argv[0] === 'python3') throw new Error('no python3')

      return ran(0, out)
    }

    state.gitCalls += 1
    const branch = state.branch
    const gate = state.gitGate

    state.gitGate = undefined
    await gate

    if (branch === null) throw new Error('git is not installed')

    return ran(0, `${branch}\n`)
  })
  on('turn.step', async function* ($, e) {
    state.now += state.stepMs
    if (state.switchedTo !== undefined) state.model = state.switchedTo

    return {
      turnId: e.turnId,
      index: e.index,
      answer: 'ok',
      toolUses: [],
      stopReason: 'end_turn' as const,
      usage: { ...USAGE, ...(state.isUncached ? { cache_read_input_tokens: 0 } : {}), model: e.model },
    }
  })
  on('turn.start', async ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', async ($, e) => ({ text: e.answer }))
  on('session.surfaces', async () => ({ value: state.surfaces }))
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => {
    const { Box } = $.ui.resolve(e)

    return <Box key="engine-empty" />
  })

  return state
}

// Lets the work a hook or a tick started without waiting for it settle.
const settle = () => new Promise<void>(resolve => setTimeout(resolve, 20))

const start = async ($: Engine) => {
  const result = await $.session.start({
    cwd: '/work/agent-toolkit',
    surface: 'terminal',
    isInteractive: true,
  })

  await settle()

  return result
}

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

  // The countdown is written behind the step.
  await settle()

  return read.value
}

const measure = async ($: Engine) => {
  const result = await $.session.measure({
    context: { window: 200_000, percent: 0 },
    rateLimits: [],
    changed: ['context'],
  })

  await settle()

  return result
}

const HEADLINE = /^\[|agent-toolkit/
const TIMES = /\d[hd]: |cache (<|\d|expired)/

const drawn = async ($: Engine, surface: 'terminal' | 'desktop' = 'terminal', props = {}) => {
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, ...props }, surface })
  const context = await ui.find({ type: 'Text', text: /^Context / })
  // A Text carries no key, so the rows are found by what they say: the
  // headline, the context fill, then the windows and the cache countdown.
  const texts = [
    (await ui.find({ type: 'Text', text: HEADLINE }))?.text,
    context?.text,
    (await ui.find({ type: 'Text', text: TIMES }))?.text,
  ]

  return { ui, texts, color: context?.props.color }
}

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
  expect(texts[0]).toBe('[Opus 5.5 ◔ medium] │ agent-toolkit git:(main)')
  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m) │ cache 60m')
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
    '[Opus 5.5] │ agent-toolkit git:(feat/x)',
    'Context 91%',
    undefined,
  ])
  expect(color).toBe('error')
  await ui.unmount()
})

test('the clock tick moves the countdowns, and the headline shows no session time', async ($, on) => {
  const state = world(on)

  await start($)
  state.now = NOW + 60 * MINUTE
  state.ticks.shift()?.()
  await settle()
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main)')
  expect(texts[2]).toBe(' │ 5h: 88% (1h 4m)')
  await ui.unmount()
})

test('a changed model drops the effort the last one ran at', async ($, on) => {
  const state = world(on)

  await start($)
  await step($)
  await measure($)
  state.model = 'claude-haiku-5-5'
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Haiku 5.5] │ agent-toolkit git:(main)')
  await ui.unmount()

  state.model = 'claude-opus-5-5'
  await measure($)
  const returned = await drawn($)

  expect(returned.texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main)')
  await returned.ui.unmount()
})

test('a failed session model read preserves a new model step effort until the next successful read', async ($, on) => {
  const state = world(on)
  state.isUncached = true

  await start($)
  state.model = 'claude-haiku-5-5'
  await step($, { model: state.model, effort: 'high' })
  state.isModelDown = true
  await measure($)
  state.isModelDown = false
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Haiku 5.5 ◑ high] │ agent-toolkit git:(main)')
  await ui.unmount()
})

test('a different dated snapshot of the same model does not inherit effort', async ($, on) => {
  const state = world(on)
  state.model = 'claude-opus-5-5-20261001'

  await start($)
  await step($, { model: state.model, effort: 'high' })
  await measure($)
  const first = await drawn($)

  expect(first.texts[0]).toBe('[Opus 5.5 ◑ high] │ agent-toolkit git:(main)')
  await first.ui.unmount()

  state.model = 'claude-opus-5-5-20261002'
  await measure($)
  const second = await drawn($)

  expect(second.texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main)')
  await second.ui.unmount()
})

test('a step and the session can name the same model by alias and snapshot', async ($, on) => {
  const state = world(on)
  state.model = 'claude-opus-5-5[1m]'

  await start($)
  await step($, { model: 'claude-opus-5-5-20261001', effort: 'high' })
  await measure($)
  const alias = await drawn($)

  expect(alias.texts[0]).toBe('[Opus 5.5[1m] ◑ high] │ agent-toolkit git:(main)')
  await alias.ui.unmount()

  state.model = 'claude-opus-5-5-20261002'
  await measure($)
  await step($, { model: 'claude-opus-5-5', effort: 'medium' })
  const snapshot = await drawn($)

  expect(snapshot.texts[0]).toBe('[Opus 5.5 ◔ medium] │ agent-toolkit git:(main)')
  await snapshot.ui.unmount()

  state.model = 'claude-opus-5-5'
  await measure($)
  state.model = 'claude-opus-5-5-20261001'
  await measure($)
  const changed = await drawn($)

  expect(changed.texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main)')
  await changed.ui.unmount()
})

test('a model read held across an old-model step still clears its effort on switching', async ($, on) => {
  const state = world(on)
  let release = () => {}

  await start($)
  state.isUncached = true
  state.holdNextModel = new Promise<void>(resolve => {
    release = resolve
  })
  const pending = measure($)
  await settle()
  await step($)
  state.model = 'claude-haiku-5-5'
  release()
  await pending
  await measure($)
  state.model = 'claude-opus-5-5'
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main)')
  await ui.unmount()
})

test('a git call that fails keeps the last branch, one that names none drops it', async ($, on) => {
  const state = world(on)

  await start($)
  state.branch = null
  await measure($)
  const kept = await drawn($)

  expect(kept.texts[0]).toContain('git:(main)')
  await kept.ui.unmount()

  state.branch = ''
  await measure($)
  const dropped = await drawn($)

  expect(dropped.texts[0]).toBe('[Opus 5.5] │ agent-toolkit')
  await dropped.ui.unmount()
})

test('an attaching surface gets the band at once and the tick stops when it leaves', async ($, on) => {
  const state = world(on)
  state.surfaces = []

  await start($)
  state.surfaces = ['desktop']
  await $.session.attach({ clientId: 'c1' } as Parameters<Engine['session']['attach']>[0])
  await settle()
  const { ui, texts } = await drawn($, 'desktop')

  expect(texts[0]).toContain('agent-toolkit')
  expect(state.ticks.length).toBe(1)
  await ui.unmount()

  state.surfaces = []
  await $.session.detach({ clientId: 'c1', reason: 'detach' } as Parameters<Engine['session']['detach']>[0])
  await settle()
  const calls = state.gitCalls
  state.ticks.shift()?.()
  await settle()

  expect(state.gitCalls).toBe(calls)
  expect(state.ticks.length).toBe(0)
})

test('before the first prompt the context reads 0%, later a missing reading is left out', async ($, on) => {
  const state = world(on)
  state.percent = undefined
  state.turns = 0

  await start($)
  const fresh = await drawn($)

  expect(fresh.texts[1]).toBe('Context 0%')
  await fresh.ui.unmount()

  state.turns = 2
  await measure($)
  const later = await drawn($)

  expect(later.texts[1]).toBeUndefined()
  expect(later.texts[2]).toBe('5h: 88% (2h 4m)')
  await later.ui.unmount()
})

test('the context reads as a percentage with no bar, cut at the row end', async ($, on) => {
  world(on)

  await start($)
  const ui = await $.ui.mount({
    ...BAND,
    viewport: { columns: 30, rows: 20, isFullscreen: false },
    surface: 'terminal',
  })
  const context = await ui.find({ type: 'Text', text: /^Context / })

  expect(context?.text).toBe('Context 12%')
  expect(context?.props.wrap).toBe('truncate-end')
  await ui.unmount()
})

test('a failed usage read keeps the last figures', async ($, on) => {
  const state = world(on)

  await start($)
  state.isUsageDown = true
  state.now = NOW + 10 * MINUTE
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts).toEqual([
    '[Opus 5.5] │ agent-toolkit git:(main)',
    'Context 12%',
    ' │ 5h: 88% (1h 54m)',
  ])
  await ui.unmount()
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
  expect(texts).toEqual(['[Opus 5.5] │ agent-toolkit', undefined, undefined])
  await ui.unmount()
})

test('where no surface draws the band it reads nothing and starts no timer', async ($, on) => {
  const state = world(on)
  state.surfaces = ['vscode']

  await start($)
  await measure($)

  expect(state.ticks.length).toBe(0)
  expect(state.gitCalls).toBe(0)
})

test('a slow git does not hold the session start', async ($, on) => {
  const state = world(on)
  state.gitGate = new Promise<void>(() => {})

  const started = await $.session.start({
    cwd: '/work/agent-toolkit',
    surface: 'terminal',
    isInteractive: true,
  })

  expect(started.cwd).toBe('/work/agent-toolkit')
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

// A row of one run reads the same as the run: the color is the run's.
const colorOf = async (ui: Awaited<ReturnType<typeof drawn>>['ui'], text: RegExp) =>
  (await ui.findAll({ type: 'Text', text })).find(found => found.props.color !== undefined)?.props
    .color

test('each segment of the rows is drawn in its own color', async ($, on) => {
  world(on)

  await start($)
  await step($)
  const { ui } = await drawn($)

  expect(await colorOf(ui, /^\[Opus 5\.5 ◔ medium\]$/)).toBe('claude')
  expect(await colorOf(ui, /^agent-toolkit$/)).toBe('suggestion')
  expect(await colorOf(ui, /^ git:\(main\)$/)).toBe('autoAccept')
  expect(await colorOf(ui, /^cache 60m$/)).toBe('planMode')
  expect(await colorOf(ui, /^88%$/)).toBe('warning')
  expect((await ui.find({ type: 'Text', text: /^5h: $/ }))?.props.dimColor).toBe(true)
  await ui.unmount()
})

test("the cache counts down from the last main-loop response, a subagent's leaves it", async ($, on) => {
  const state = world(on)

  await start($)
  await step($)
  state.now = NOW + 10 * MINUTE
  await step($, { agentId: 'agent-1' })
  await measure($)
  const running = await drawn($)

  expect(running.texts[0]).not.toContain('cache')
  expect(running.texts[2]).toBe(' │ 5h: 88% (1h 54m) │ cache 50m')
  await running.ui.unmount()

  state.now = NOW + 60 * MINUTE
  await measure($)
  const lapsed = await drawn($)

  expect(lapsed.texts[2]).toBe(' │ 5h: 88% (1h 4m) │ cache expired')
  expect(await colorOf(lapsed.ui, /^cache expired$/)).toBe('warning')
  await lapsed.ui.unmount()
})

test('a /clear takes the cache figure down until the next response', async ($, on) => {
  world(on)

  await start($)
  await step($)
  await $.session.end({ reason: 'clear' } as Parameters<Engine['session']['end']>[0])
  await settle()
  const cleared = await drawn($)

  expect(cleared.texts[2]).toBe(' │ 5h: 88% (2h 4m)')
  await cleared.ui.unmount()

  await step($)
  const renewed = await drawn($)

  expect(renewed.texts[2]).toContain('│ cache 60m')
  await renewed.ui.unmount()
})

test(
  'the cache is counted against the configured lifetime',
  { options: { statusBandCacheTtlMinutes: 5 } },
  async ($, on) => {
    world(on)

    await start($)
    await step($)
    const { ui, texts } = await drawn($)

    expect(texts[2]).toContain('│ cache 5m')
    await ui.unmount()
  },
)

test('the cache is counted from when the request was sent, not when the answer ended', async ($, on) => {
  const state = world(on)
  state.stepMs = 4 * MINUTE

  await start($)
  await step($)
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[2]).toContain('│ cache 56m')
  await ui.unmount()
})

test('a countdown started under one model is dropped under another, whatever steps began since', async ($, on) => {
  const state = world(on)

  await start($)
  await step($)
  state.model = 'claude-haiku-5-5'
  state.isUncached = true
  await step($, { model: 'claude-haiku-5-5' })
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Haiku 5.5 ◔ medium] │ agent-toolkit git:(main)')
  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m)')
  await ui.unmount()
})

test('a cache made under one model is not handed to the model the session switched to meanwhile', async ($, on) => {
  const state = world(on)

  await start($)
  state.switchedTo = 'claude-haiku-5-5'
  await step($)
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Haiku 5.5] │ agent-toolkit git:(main)')
  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m)')
  await ui.unmount()
})

test('a countdown that lands after the session moved to another model is not shown under it', async ($, on) => {
  const state = world(on)
  let release = () => {}

  await start($)
  state.holdNextNow = new Promise<void>(resolve => {
    release = resolve
  })
  await step($)
  state.model = 'claude-haiku-5-5'
  await measure($)
  release()
  await settle()
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Haiku 5.5] │ agent-toolkit git:(main)')
  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m)')
  await ui.unmount()
})

test('a countdown whose model check ends after a /clear is not written back', async ($, on) => {
  const state = world(on)
  let release = () => {}

  await start($)
  state.holdNextModel = new Promise<void>(resolve => {
    release = resolve
  })
  await step($)
  await $.session.end({ reason: 'clear' } as Parameters<Engine['session']['end']>[0])
  await settle()
  release()
  await settle()
  const { ui, texts } = await drawn($)

  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m)')
  await ui.unmount()
})

test('a countdown whose model lookup fails is not shown under the model the band moved to', async ($, on) => {
  const state = world(on)
  let release = () => {}

  await start($)
  state.holdNextModel = new Promise<void>(resolve => {
    release = resolve
  })
  await step($)
  state.model = 'claude-haiku-5-5'
  await measure($)
  state.isModelDown = true
  release()
  await settle()
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Haiku 5.5] │ agent-toolkit git:(main)')
  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m)')
  await ui.unmount()
})

test('a refresh that read the old model keeps a cache a newer model recorded meanwhile', async ($, on) => {
  const state = world(on)
  let release = () => {}

  await start($)
  state.gitGate = new Promise<void>(resolve => {
    release = resolve
  })
  await measure($)
  state.model = 'claude-haiku-5-5'
  await step($, { model: 'claude-haiku-5-5' })
  release()
  await settle()
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toContain('[Haiku 5.5')
  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m) │ cache 60m')
  await ui.unmount()
})

test('in a narrow terminal the reset times go before the cache countdown', async ($, on) => {
  const state = world(on)
  state.rateLimits.push({
    kind: 'seven_day',
    percentUsed: 40,
    resetsAt: new Date(NOW + 3 * 24 * 60 * MINUTE).toISOString(),
  })

  await start($)
  await step($)
  const wide = await drawn($, 'terminal', { bodyColumns: 80 })

  expect(wide.texts[2]).toBe(' │ 5h: 88% (2h 4m) │ 7d: 40% (3d 0h) │ cache 60m')
  await wide.ui.unmount()

  const some = await drawn($, 'terminal', { bodyColumns: 52 })

  expect(some.texts[2]).toBe(' │ 5h: 88% (2h 4m) │ 7d: 40% │ cache 60m')
  await some.ui.unmount()

  const narrow = await drawn($, 'terminal', { bodyColumns: 50 })

  expect(narrow.texts[2]).toBe(' │ 5h: 88% │ 7d: 40% │ cache 60m')
  await narrow.ui.unmount()

  const tight = await drawn($, 'terminal', { bodyColumns: 34 })

  expect(tight.texts[2]).toBe(' │ 5h: 88% │ cache 60m')
  await tight.ui.unmount()

  const tiny = await drawn($, 'terminal', { bodyColumns: 24 })

  expect(tiny.texts[2]).toBe(' │ cache 60m')
  await tiny.ui.unmount()
})

test('a window whose reset still fits keeps it where the cache is not counting', async ($, on) => {
  const state = world(on)
  state.isUncached = true
  state.rateLimits.push({
    kind: 'seven_day',
    percentUsed: 40,
    resetsAt: new Date(NOW + 3 * 24 * 60 * MINUTE).toISOString(),
  })

  await start($)
  await step($)
  const { ui, texts } = await drawn($, 'terminal', { bodyColumns: 40 })

  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m) │ 7d: 40%')
  await ui.unmount()
})

test('an expired cache does not displace usage figures on a narrow row', async ($, on) => {
  const state = world(on)
  state.rateLimits.push({ kind: 'seven_day', percentUsed: 99 })

  await start($)
  await step($)
  state.now = NOW + 60 * MINUTE
  await measure($)
  const { ui, texts } = await drawn($, 'terminal', { bodyColumns: 40 })

  expect(texts[2]).toBe(' │ 5h: 88% │ 7d: 99%')
  await ui.unmount()
})

test('a cache is the model the step ran under, whichever model the session names at that moment', async ($, on) => {
  const state = world(on)

  await start($)
  state.switchedTo = 'claude-haiku-5-5'
  await step($, { model: 'claude-haiku-5-5' })
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Haiku 5.5 ◔ medium] │ agent-toolkit git:(main)')
  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m) │ cache 60m')
  await ui.unmount()
})

test('a model named with a context suffix or a date is the same model for the cache', async ($, on) => {
  const state = world(on)
  state.model = 'claude-opus-5-5[1m]'

  await start($)
  await step($)
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Opus 5.5[1m] ◔ medium] │ agent-toolkit git:(main)')
  expect(texts[2]).toBe(' │ 5h: 88% (2h 4m) │ cache 60m')
  await ui.unmount()
})

test('a due curate run takes room from the reset times', async ($, on) => {
  const state = curateWorld(on)

  await start($)
  await step($)
  const roomy = await drawn($, 'terminal', { bodyColumns: 80 })

  expect(roomy.texts[2]).toBe(' │ 5h: 88% (2h 4m) │ cache 60m')
  await roomy.ui.unmount()

  const tight = await drawn($, 'terminal', { bodyColumns: 60 })

  expect(tight.texts[2]).toBe(' │ 5h: 88% │ cache 60m')
  await tight.ui.unmount()
  expect(state.curateRuns).toHaveLength(1)
})

test(
  'in plain ASCII the rows draw no box or geometric glyph',
  { options: { statusBandAscii: true } },
  async ($, on) => {
    world(on)

    await start($)
    await step($)
    const { ui, texts } = await drawn($)

    expect(texts).toEqual([
      '[Opus 5.5 medium] | agent-toolkit git:(main)',
      'Context 12%',
      ' | 5h: 88% (2h 4m) | cache 60m',
    ])
    await ui.unmount()
  },
)

const DUE = 'HARNESS-CURATE DUE: last run 20d ago, 12 sessions since. At the start of your next reply...\n'

// A harness repo with the dev plugin on, whose curate check prints `out`.
const curateWorld = (on: On, out: string | null = DUE): World => {
  const state = world(on)
  state.settings = { enabledPlugins: { 'dev@kadragon': true } }
  state.files = {
    '/home/me/.claude/plugins/installed_plugins.json': JSON.stringify({
      plugins: { 'dev@kadragon': [{ installPath: '/p/dev' }] },
    }),
    '/work/agent-toolkit/AGENTS.md': '# agents',
  }
  state.curateOut = out

  return state
}

const curateFlag = async (ui: Awaited<ReturnType<typeof drawn>>['ui']) =>
  ui.find({ type: 'Text', text: /^harness-curate due$/ })

test('a due curate run shows on the band', async ($, on) => {
  const state = curateWorld(on)

  await start($)
  const { ui, texts } = await drawn($)

  expect(state.curateRuns).toEqual([
    [
      'python3',
      '/p/dev/skills/harness-curate/scripts/record_run.py',
      '--check-due',
      '--project',
      '/work/agent-toolkit',
    ],
  ])
  expect((await curateFlag(ui))?.props.color).toBe('warning')
  expect(texts[0]).toContain('agent-toolkit')
  await ui.unmount()
})

test('a curate run that is not due draws nothing', async ($, on) => {
  const state = curateWorld(on, '')

  await start($)
  const { ui } = await drawn($)

  expect(state.curateRuns.length).toBe(1)
  expect(await curateFlag(ui)).toBeUndefined()
  await ui.unmount()
})

test('outside a harness repo, or without the dev plugin, the check is not run', async ($, on) => {
  const state = curateWorld(on)
  delete state.files['/work/agent-toolkit/AGENTS.md']

  await start($)
  const bare = await drawn($)

  expect(state.curateRuns.length).toBe(0)
  expect(await curateFlag(bare.ui)).toBeUndefined()
  await bare.ui.unmount()

  state.files['/work/agent-toolkit/AGENTS.md'] = '# agents'
  state.settings = { enabledPlugins: { 'dev@kadragon': false } }
  await $.session.end({ reason: 'clear' } as Parameters<Engine['session']['end']>[0])
  await settle()

  expect(state.curateRuns.length).toBe(0)
})

test('the check runs once in ten minutes, and again after a /clear', async ($, on) => {
  const state = curateWorld(on)

  await start($)
  await measure($)
  state.now = NOW + 9 * MINUTE
  await measure($)

  expect(state.curateRuns.length).toBe(1)

  state.now = NOW + 10 * MINUTE
  await measure($)

  expect(state.curateRuns.length).toBe(2)

  // The curate run stamped its record: the next session finds it not due.
  state.curateOut = ''
  await $.session.end({ reason: 'clear' } as Parameters<Engine['session']['end']>[0])
  await settle()
  const { ui } = await drawn($)

  expect(state.curateRuns.length).toBe(3)
  expect(await curateFlag(ui)).toBeUndefined()
  await ui.unmount()
})

test('a curate check that cannot run fails nothing and keeps the rest of the band', async ($, on) => {
  const state = curateWorld(on, null)

  const started = await start($)
  const { ui, texts } = await drawn($)

  expect(started.cwd).toBe('/work/agent-toolkit')
  // `python3` failed to start, then `python`.
  expect(state.curateRuns.map(argv => argv[0])).toEqual(['python3', 'python'])
  expect(await curateFlag(ui)).toBeUndefined()
  expect(texts[1]).toBe('Context 12%')
  await ui.unmount()
})

// The text of the row the curate flag is on: the innermost box that holds it
// and not the headline.
const curateRow = async (ui: Awaited<ReturnType<typeof drawn>>['ui']) =>
  (await ui.findAll({ type: 'Box', text: /harness-curate due$/ }))
    .map(box => box.text)
    .find(text => !text.includes('git:('))

test('a due curate run follows the other figures on its row behind a separator', async ($, on) => {
  curateWorld(on)

  await start($)
  const { ui } = await drawn($)

  expect(await curateRow(ui)).toBe('Context 12% │ 5h: 88% (2h 4m) │ harness-curate due')
  await ui.unmount()
})

test('a due curate run alone on its row draws no separator before it', async ($, on) => {
  const state = curateWorld(on)
  state.percent = undefined
  state.turns = 2
  state.rateLimits = []

  await start($)
  const { ui } = await drawn($)

  expect(await curateRow(ui)).toBe('harness-curate due')
  await ui.unmount()
})

test('a due curate run keeps the second row where no other figure is read', async ($, on) => {
  const state = curateWorld(on)
  state.percent = undefined
  state.turns = 2
  state.rateLimits = []

  await start($)
  const { ui, texts } = await drawn($)

  expect(texts.slice(1)).toEqual([undefined, undefined])
  expect((await curateFlag(ui))?.props.color).toBe('warning')
  await ui.unmount()
})

test('where only python is installed, the check runs under it', async ($, on) => {
  const state = curateWorld(on)
  state.isPython3Missing = true

  await start($)
  const { ui } = await drawn($)

  expect(state.curateRuns.map(argv => argv[0])).toEqual(['python3', 'python'])
  expect(await curateFlag(ui)).toBeDefined()
  await ui.unmount()
})

test('a slow curate check holds neither the other figures nor a /clear', async ($, on) => {
  const state = curateWorld(on)
  let release = () => {}
  state.curateGate = new Promise<void>(resolve => (release = resolve))

  await start($)
  const held = await drawn($)

  expect(held.texts[1]).toBe('Context 12%')
  expect(await curateFlag(held.ui)).toBeUndefined()
  await held.ui.unmount()

  // The check that was running was the last session's: the new one asks again.
  await $.session.end({ reason: 'clear' } as Parameters<Engine['session']['end']>[0])
  await settle()
  release()
  await settle()
  const { ui } = await drawn($)

  expect(state.curateRuns.length).toBe(2)
  expect(await curateFlag(ui)).toBeDefined()
  await ui.unmount()
})

test('a Windows home is read through backslashes alone', async ($, on) => {
  const state = curateWorld(on)
  state.env = { USERPROFILE: 'C:\\Users\\me' }
  state.files = {
    'C:\\Users\\me\\.claude\\plugins\\installed_plugins.json': JSON.stringify({
      plugins: { 'dev@kadragon': [{ installPath: 'C:\\p\\dev' }] },
    }),
    '/work/agent-toolkit/AGENTS.md': '# agents',
  }

  await start($)

  expect(state.curateRuns.map(argv => argv[1])).toEqual([
    'C:\\p\\dev\\skills\\harness-curate\\scripts\\record_run.py',
  ])
})

test('a Windows project install is used only when the differently cased ancestor is confirmed', async ($, on) => {
  const state = curateWorld(on)
  state.cwd = 'c:/work/repo/src'
  state.files['c:/work/repo/src/AGENTS.md'] = '# agents'
  state.files['/home/me/.claude/plugins/installed_plugins.json'] = JSON.stringify({
    plugins: {
      'dev@kadragon': [
        { projectPath: 'C:\\work\\Repo', installPath: '/p/project' },
        { installPath: '/p/user' },
      ],
    },
  })

  await start($)

  expect(state.curateRuns.map(argv => argv[1])).toEqual([
    '/p/user/skills/harness-curate/scripts/record_run.py',
  ])

  state.sameDirectory = true
  await $.session.end({ reason: 'clear' } as Parameters<Engine['session']['end']>[0])
  await settle()

  expect(state.curateRuns.at(-1)?.[1]).toBe('/p/project/skills/harness-curate/scripts/record_run.py')
})

test('the band is two rows at most, with no count row and no session time', async ($, on) => {
  const state = world(on)
  state.settings = { hooks: { Stop: [{ hooks: [{ type: 'command' }] }] } }

  await start($)
  await step($)
  const four = await drawn($, 'terminal', { maxRows: 4 })

  expect(four.texts).toEqual([
    '[Opus 5.5 ◔ medium] │ agent-toolkit git:(main)',
    'Context 12%',
    ' │ 5h: 88% (2h 4m) │ cache 60m',
  ])
  expect(await four.ui.find({ type: 'Text', text: /\b(hooks?|skills?|mcp)\b| up (<|\d)/ })).toBeUndefined()
  expect((await four.ui.find({ key: 'status-band' }))?.props.marginTop).toBe(1)
  await four.ui.unmount()

  const two = await drawn($, 'terminal', { maxRows: 2 })

  expect(two.texts[1]).toBe('Context 12%')
  expect((await two.ui.find({ key: 'status-band' }))?.props.marginTop).toBe(0)
  await two.ui.unmount()

  const one = await drawn($, 'terminal', { maxRows: 1 })

  expect(one.texts).toEqual([undefined, undefined, undefined])
  expect(await one.ui.find({ key: 'engine-empty' })).toBeDefined()
  await one.ui.unmount()
})
