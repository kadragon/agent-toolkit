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
  cache_read_input_tokens: 10,
  cache_creation_input_tokens: 0,
}

type World = {
  now: number
  model: string
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
  // Unset, the settings read fails and the breakdown carries no skills.
  settings?: Record<string, unknown>
  files: Record<string, string>
  // What the environment holds; a name not listed is unset.
  env: Record<string, string>
  skills?: { totalSkills: number; tokens: number }
  // The servers of the MCP tools the breakdown carries, one entry per tool.
  mcpServers: string[]
  // Servers that need a sign-in: they offer only the tools that start one.
  mcpUnauthed: string[]
  settingsReads: number
  // How long the next responses take to come back.
  stepMs: number
  isUncached: boolean
  // What the curate check prints; null makes it fail to start.
  curateOut: string | null
  curateRuns: (readonly string[])[]
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
    files: {},
    env: { HOME: '/home/me' },
    mcpServers: [],
    mcpUnauthed: [],
    settingsReads: 0,
    stepMs: 0,
    isUncached: false,
    curateOut: '',
    curateRuns: [],
    isPython3Missing: false,
  }

  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('session.measure', async ($, e) => ({ changed: e.changed }))
  on('session.attach', async ($, e) => ({ clientId: e.clientId }))
  on('session.detach', async ($, e) => ({ clientId: e.clientId }))
  on('session.end', async () => ({ sessionId: 's1' }))
  on('session.model', async () => ({ value: state.model }))
  on('session.cwd', async () => ({ value: '/work/agent-toolkit' }))
  on('session.turns', async () => ({ value: state.turns }))
  on('session.usage', async ($, e) => {
    if (state.isUsageDown) throw new Error('usage is down')

    const breakdown =
      e.breakdown === undefined || state.skills === undefined
        ? {}
        : {
            breakdown: {
              skills: { ...state.skills, includedSkills: 0, skillFrontmatter: [] },
              mcpTools: [
                ...state.mcpServers.map((serverName, index) => ({
                  name: `mcp__${serverName}__t${index}`,
                  serverName,
                  tokens: 10,
                  isLoaded: true,
                })),
                ...state.mcpUnauthed.flatMap(serverName =>
                  ['authenticate', 'complete_authentication'].map(tool => ({
                    name: `mcp__${serverName.replace(/[^\w-]+/g, '_')}__${tool}`,
                    serverName,
                    tokens: 10,
                    isLoaded: false,
                  })),
                ),
              ],
            },
          }

    return {
      value: {
        startedAt: NOW - 5 * MINUTE,
        context: { window: 200_000, percent: state.percent, ...breakdown },
        rateLimits: state.rateLimits,
      },
    } as never
  })
  on('settings.read', async () => {
    state.settingsReads += 1

    if (state.settings === undefined) throw new Error('settings are down')

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
  on('clock.now', async () => ({ value: state.now }))
  // A period ends when the test says so.
  on('clock.every', async () => {
    await new Promise<void>(resolve => state.ticks.push(resolve))

    return { value: undefined }
  })
  on('fs.exists', async ($, e) => ({
    value: Object.keys(state.files).some(file => isFile(e.path, file)),
  }))
  on('process.run', async ($, e) => {
    if (e.argv[0] !== 'git') {
      state.curateRuns.push(e.argv)
      const out = state.curateOut
      const gate = state.curateGate

      state.curateGate = undefined
      await gate

      if (out === null) throw new Error('python is not installed')
      if (state.isPython3Missing && e.argv[0] === 'python3') throw new Error('no python3')

      return { value: { exitCode: 0, stdout: out, stderr: '' } }
    }

    state.gitCalls += 1
    const branch = state.branch
    const gate = state.gitGate

    state.gitGate = undefined
    await gate

    if (branch === null) throw new Error('git is not installed')

    return { value: { exitCode: 0, stdout: `${branch}\n`, stderr: '' } }
  })
  on('turn.step', async function* ($, e) {
    state.now += state.stepMs

    return {
      turnId: e.turnId,
      index: e.index,
      answer: 'ok',
      toolUses: [],
      usage: state.isUncached ? { ...USAGE, cache_read_input_tokens: 0 } : USAGE,
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

const drawn = async ($: Engine, surface: 'terminal' | 'desktop' = 'terminal', props = {}) => {
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, ...props }, surface })
  const context = await ui.find({ type: 'Text', text: /^Context / })
  // A Text carries no key, so the rows are found by what they say. The setup
  // row is read onto the headline, as a band of two rows draws it.
  const headline = (await ui.find({ type: 'Text', text: / up (<|\d)/ }))?.text
  const isSplit = ((props as { maxRows?: number }).maxRows ?? BAND.props.maxRows) >= 3
  const setup = isSplit
    ? (await ui.find({ type: 'Text', text: /^(cache |\d+ (hooks?|skills?|mcp)\b)/ }))?.text
    : undefined
  const texts = [
    setup === undefined || headline === undefined ? headline : `${headline} │ ${setup}`,
    context?.text,
    (await ui.find({ type: 'Text', text: /\d[hd]: / }))?.text,
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
  expect(texts[0]).toBe('[Opus 5.5 ◔ medium] │ agent-toolkit git:(main) │ up 5m │ cache 60m')
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
    '[Opus 5.5] │ agent-toolkit git:(feat/x) │ up 5m',
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

  expect(texts[0]).toContain('up 1h 5m')
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

  expect(texts[0]).toBe('[Haiku 5.5] │ agent-toolkit git:(main) │ up 5m')
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

  expect(dropped.texts[0]).toBe('[Opus 5.5] │ agent-toolkit │ up 5m')
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

  expect(fresh.texts[1]).toBe('Context ░░░░░░░░░░ 0%')
  await fresh.ui.unmount()

  state.turns = 2
  await measure($)
  const later = await drawn($)

  expect(later.texts[1]).toBeUndefined()
  expect(later.texts[2]).toBe('5h: 88% (2h 4m)')
  await later.ui.unmount()
})

test('a failed usage read keeps the last figures', async ($, on) => {
  const state = world(on)

  await start($)
  state.isUsageDown = true
  state.now = NOW + 10 * MINUTE
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts).toEqual([
    '[Opus 5.5] │ agent-toolkit git:(main) │ up 15m',
    'Context █░░░░░░░░░ 12%',
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
  expect(texts).toEqual([undefined, undefined, undefined])
  expect((await ui.find({ type: 'Text', text: /agent-toolkit/ }))?.text).toBe(
    '[Opus 5.5] │ agent-toolkit',
  )
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
  const state = world(on)
  state.settings = { hooks: { Stop: [{ hooks: [{ type: 'command', command: 'true' }] }] } }
  state.skills = { totalSkills: 2, tokens: 300 }
  state.mcpServers = ['qmd']

  await start($)
  await step($)
  const { ui } = await drawn($)

  expect(await colorOf(ui, /^\[Opus 5\.5 ◔ medium\]$/)).toBe('claude')
  expect(await colorOf(ui, /^agent-toolkit$/)).toBe('suggestion')
  expect(await colorOf(ui, /^ git:\(main\)$/)).toBe('autoAccept')
  expect(await colorOf(ui, /^cache 60m$/)).toBe('planMode')
  expect(await colorOf(ui, /^1 hook$/)).toBe('permission')
  expect(await colorOf(ui, /^2 skills$/)).toBe('remember')
  expect(await colorOf(ui, /^1 mcp$/)).toBe('ide')
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

  expect(running.texts[0]).toContain('up 15m │ cache 50m')
  await running.ui.unmount()

  state.now = NOW + 60 * MINUTE
  await measure($)
  const lapsed = await drawn($)

  expect(lapsed.texts[0]).toContain('up 1h 5m │ cache expired')
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

  expect(cleared.texts[0]).toBe('[Opus 5.5 ◔ medium] │ agent-toolkit git:(main) │ up 5m')
  await cleared.ui.unmount()

  await step($)
  const renewed = await drawn($)

  expect(renewed.texts[0]).toContain('│ cache 60m')
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

    expect(texts[0]).toContain('│ cache 5m')
    await ui.unmount()
  },
)

const hooksFile = (count: number): string =>
  JSON.stringify({
    hooks: { PostToolUse: [{ matcher: 'Bash', hooks: Array(count).fill({ type: 'command' }) }] },
  })

test("the hook count adds the enabled plugins' hooks to the settings' own", async ($, on) => {
  const state = world(on)
  state.settings = {
    hooks: { PreToolUse: [{ matcher: 'Bash', hooks: [{ type: 'command' }, { type: 'command' }] }] },
    enabledPlugins: { 'plain@m': true, 'off@m': false, 'named@m': true, 'gone@m': true },
  }
  state.files = {
    '/home/me/.claude/plugins/installed_plugins.json': JSON.stringify({
      plugins: {
        'plain@m': [{ installPath: '/p/plain' }],
        'off@m': [{ installPath: '/p/off' }],
        'named@m': [{ installPath: '/p/named' }],
      },
    }),
    '/p/plain/hooks/hooks.json': hooksFile(3),
    '/p/off/hooks/hooks.json': hooksFile(10),
    '/p/named/.claude-plugin/plugin.json': JSON.stringify({ hooks: './hooks.json' }),
    '/p/named/hooks.json': hooksFile(2),
  }

  await start($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main) │ up 5m │ 7 hooks')
  await ui.unmount()
})

test('a Windows home is read through backslashes alone', async ($, on) => {
  const state = world(on)
  state.env = { USERPROFILE: 'C:\\Users\\me' }
  state.settings = { enabledPlugins: { 'plain@m': true, 'named@m': true } }
  state.files = {
    'C:\\Users\\me\\.claude\\plugins\\installed_plugins.json': JSON.stringify({
      plugins: {
        'plain@m': [{ installPath: 'C:\\p\\plain' }],
        'named@m': [{ installPath: 'C:\\p\\named' }],
      },
    }),
    'C:\\p\\plain\\hooks\\hooks.json': hooksFile(3),
    'C:\\p\\named\\.claude-plugin\\plugin.json': JSON.stringify({ hooks: './sub/hooks.json' }),
    'C:\\p\\named\\sub\\hooks.json': hooksFile(2),
  }

  await start($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main) │ up 5m │ 5 hooks')
  await ui.unmount()
})

test('the cache is counted from when the request was sent, not when the answer ended', async ($, on) => {
  const state = world(on)
  state.stepMs = 4 * MINUTE

  await start($)
  await step($)
  await measure($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toContain('up 9m │ cache 56m')
  await ui.unmount()
})

test('the counts follow the settings turn by turn, and a failed read keeps the last one', async ($, on) => {
  const state = world(on)
  state.settings = { hooks: { Stop: [{ hooks: [{ type: 'command' }] }] } }
  state.skills = { totalSkills: 2, tokens: 300 }

  await start($)
  state.settings = {}
  state.skills = { totalSkills: 3, tokens: 450 }
  await measure($)
  const changed = await drawn($)

  expect(changed.texts[0]).toContain('│ 0 hooks │ 3 skills (450)')
  await changed.ui.unmount()

  state.settings = undefined
  await measure($)
  const kept = await drawn($)

  expect(kept.texts[0]).toContain('│ 0 hooks │ 3 skills (450)')
  await kept.ui.unmount()
})

test("a new session does not keep the last one's counts", async ($, on) => {
  const state = world(on)
  state.settings = { hooks: { Stop: [{ hooks: [{ type: 'command' }] }] } }

  await start($)
  state.settings = undefined
  await $.session.end({ reason: 'clear' } as Parameters<Engine['session']['end']>[0])
  await settle()
  const { ui, texts } = await drawn($)

  expect(texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main) │ up 5m')
  await ui.unmount()
})

test('hooks switched off in the settings count as none', async ($, on) => {
  const state = world(on)
  state.settings = {
    disableAllHooks: true,
    hooks: { Stop: [{ hooks: [{ type: 'command' }] }] },
  }

  await start($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toContain('│ 0 hooks')
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

  expect(texts[0]).toBe('[Haiku 5.5 ◔ medium] │ agent-toolkit git:(main) │ up 5m')
  await ui.unmount()
})

test('in a band of two rows the figures stay and the blank row gives way', async ($, on) => {
  const state = world(on)
  state.settings = {}
  state.skills = { totalSkills: 2, tokens: 300 }

  await start($)
  const { ui, texts } = await drawn($, 'terminal', { maxRows: 2 })

  // The setup rides on the headline.
  expect(texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main) │ up 5m │ 0 hooks │ 2 skills (300)')
  expect((await ui.find({ key: 'status-band' }))?.props.marginTop).toBe(0)
  await ui.unmount()
})

test('in a band of three rows the setup takes the middle one and the blank row gives way', async ($, on) => {
  const state = world(on)
  state.settings = {}
  state.skills = { totalSkills: 2, tokens: 300 }

  await start($)
  const { ui } = await drawn($, 'terminal', { maxRows: 3 })
  const band = await ui.find({ key: 'status-band' })
  const rows = await Promise.all([
    ui.find({ type: 'Text', text: / up (<|\d)/ }),
    ui.find({ type: 'Text', text: /^\d+ hooks?/ }),
  ])

  expect(rows.map(row => row?.text)).toEqual([
    '[Opus 5.5] │ agent-toolkit git:(main) │ up 5m',
    '0 hooks │ 2 skills (300)',
  ])
  expect(band?.props.marginTop).toBe(0)
  await ui.unmount()
})

test(
  'in plain ASCII the rows draw no box, block or geometric glyph',
  { options: { statusBandAscii: true } },
  async ($, on) => {
    const state = world(on)
    state.settings = {}
    state.skills = { totalSkills: 2, tokens: 300 }

    await start($)
    await step($)
    const { ui, texts } = await drawn($)
    const rows = await Promise.all([
      ui.find({ type: 'Text', text: / up (<|\d)/ }),
      ui.find({ type: 'Text', text: /^cache / }),
    ])

    expect(rows.map(row => row?.text)).toEqual([
      '[Opus 5.5 medium] | agent-toolkit git:(main) | up 5m',
      'cache 60m | 0 hooks | 2 skills (300)',
    ])
    expect(texts.slice(1)).toEqual([
      'Context #--------- 12%',
      ' | 5h: 88% (2h 4m)',
    ])
    await ui.unmount()
  },
)

test('in a band of three rows with no setup figure yet, the blank row stays', async ($, on) => {
  world(on)

  await start($)
  const { ui, texts } = await drawn($, 'terminal', { maxRows: 3 })

  expect(texts[0]).toBe('[Opus 5.5] │ agent-toolkit git:(main) │ up 5m')
  expect((await ui.find({ key: 'status-band' }))?.props.marginTop).toBe(1)
  await ui.unmount()
})

test('the MCP figure counts each connected server once, however many tools it has', async ($, on) => {
  const state = world(on)
  state.settings = {}
  state.skills = { totalSkills: 2, tokens: 300 }
  state.mcpServers = ['context-mode', 'context-mode', 'qmd', 'claude.ai Gmail']
  state.mcpUnauthed = ['claude.ai Asana', 'claude.ai Slack']

  await start($)
  const { ui, texts } = await drawn($)

  expect(texts[0]).toContain('│ 2 skills (300) │ 3 mcp')
  await ui.unmount()
})

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
  expect(texts[1]).toBe('Context █░░░░░░░░░ 12%')
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

test('a slow curate check holds neither the counts nor a /clear', async ($, on) => {
  const state = curateWorld(on)
  state.settings = { ...state.settings, hooks: { Stop: [{ hooks: [{ type: 'command' }] }] } }
  let release = () => {}
  state.curateGate = new Promise<void>(resolve => (release = resolve))

  await start($)
  const held = await drawn($)

  expect(held.texts[0]).toContain('│ 1 hook')
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
