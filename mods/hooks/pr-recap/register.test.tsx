import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

const NOW = 1793589760 * 1000 + 30 * 60_000
const RS = '\x1e'
const US = '\x1f'
const GS = '\x1d'
const LATEST = 'c31d51bc34550d835dfce3c958b2e422864aa3c7'
const record = (sha: string, subject: string, body: string, numstat: string[]) =>
  `${RS}${sha}${US}${subject}${US}kangdonguk${US}1793589760${US}${body}${GS}\n\n${numstat.join('\n')}\n`
const LOG = [
  record(LATEST, '[HARNESS] commit-guard reads a switch (#381)', 'Why one.\n\nHow two.\n', [
    '12\t3\tdev/hooks/commit-guard/guard.py',
    '40\t0\tdev/hooks/commit-guard/test_guard.py',
    '2\t1\tCHANGELOG.md',
  ]),
  record('3d01722000000000000000000000000000000000', 'direct commit', '', ['1\t1\ta.md']),
  record('4a0c69c0000000000000000000000000000000000', '[HARNESS] Revert the side pane (#380)', '', ['0\t9\tdev/x.sh']),
  record('77426d3000000000000000000000000000000000', '[FIX] backlog (#377)', '', ['1\t0\tb.py']),
].join('')
const DIFF = 'diff --git a/dev/hooks/commit-guard/guard.py b/dev/hooks/commit-guard/guard.py\n+predict()\n'
const EXPLAIN = {
  summary: '커밋 가드가 새 브랜치를 미리 알아본다.',
  nodes: [
    { name: '명령 체인', note: '브랜치 생성 포함', change: 'same', link: '분석 요청' },
    { name: '커밋 가드', note: '예측 로직 추가', change: 'changed', link: '' },
  ],
}

const BAND = {
  plugin: 'mods',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 20,
    bodyColumns: 200,
    scroll: { offset: 0, bodyRows: 19 },
    view: {},
  },
  viewport: { columns: 200, rows: 50, isFullscreen: true },
} as const
const PANE = {
  plugin: 'mods',
  component: 'Pane',
  requestId: 'pr-recap',
  props: {
    title: 'PR recap',
    isFocused: false,
    bodyColumns: 40,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

type World = {
  log: string | null
  logRuns: number
  diffRuns: (readonly string[])[]
  opens: { id: string; columns?: number }[]
  commands: string[]
  // Registrations that fail before one goes through.
  registerFailures: number
  // Set to hold the next git log run open until the test lets it go.
  gitGate?: Promise<void>
  // What the model answers; null makes the call fail.
  reply: string | null
  modelCalls: { model: string; prompt: string }[]
  // Set to hold the next model call open until the test lets it go.
  modelGate?: Promise<void>
  store: Map<string, unknown>
}

const world = (on: On): World => {
  const state: World = {
    log: LOG,
    logRuns: 0,
    diffRuns: [],
    opens: [],
    commands: [],
    registerFailures: 0,
    reply: JSON.stringify(EXPLAIN),
    modelCalls: [],
    store: new Map(),
  }

  on('clock.now', async () => ({ value: NOW }))
  on('clock.sleep', async () => ({ value: undefined }))
  on('command.register', async ($, e) => {
    if (state.registerFailures > 0) {
      state.registerFailures -= 1
      throw new Error('register is down')
    }

    state.commands.push(e.name)

    return { value: { command: e.name } }
  })
  on('ui.open', async ($, e) => {
    state.opens.push({ id: e.id, ...(e.columns === undefined ? {} : { columns: e.columns }) })

    return { value: { isPlaced: true } }
  })
  on('ui.panes', async () => ({
    value: state.opens.length === 0 ? [] : [{ id: 'pr-recap', title: 'PR recap', isShown: true, isFocused: false, isPlaced: true }],
  }) as never)
  on('process.run', async ($, e) => {
    const run = { isStdoutTruncated: false, isStderrTruncated: false }

    if (e.argv.includes('diff')) {
      state.diffRuns.push(e.argv)

      return { value: { ...run, exitCode: 0, stdout: DIFF, stderr: '' } }
    }

    state.logRuns += 1

    const gate = state.gitGate

    state.gitGate = undefined
    await gate

    if (state.log === null) return { value: { ...run, exitCode: 128, stdout: '', stderr: 'fatal: not a git repository\n' } }

    return { value: { ...run, exitCode: 0, stdout: state.log, stderr: '' } }
  })
  on('model.complete', async ($, e) => {
    state.modelCalls.push({ model: e.model, prompt: String(e.prompt) })

    const gate = state.modelGate

    state.modelGate = undefined
    await gate

    const usage = { input_tokens: 1, output_tokens: 1 }

    if (state.reply === null) {
      return { value: { isAnswered: false, reason: 'api-error', status: 500, error: 'server_error', usage } } as never
    }

    return { value: { isAnswered: true, text: state.reply, usage } } as never
  })
  on('store.get', async ($, e) => ({ value: state.store.get(e.key) }) as never)
  on('store.set', async ($, e) => {
    state.store.set(e.key, e.value)

    return { value: undefined }
  })
  on('tool.call', { tool: 'Bash' }, async () => ({ result: {} }))
  on('ui.render', async ($, e) => {
    const { Box } = $.ui.resolve(e)

    return <Box key="engine-empty" />
  })

  return state
}

const settle = () => new Promise<void>(resolve => setTimeout(resolve, 20))

// The first band drawing boots the pane, as a session's first frame does.
const boot = async ($: Engine) => {
  const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await settle()
  await band.unmount()
}

const texts = async (ui: { findAll: (query: { type: 'Text' }) => Promise<{ text?: string }[]> }) =>
  (await ui.findAll({ type: 'Text' })).map(found => found.text)

const gated = () => {
  let release = () => {}
  const gate = new Promise<void>(resolve => {
    release = resolve
  })

  return { gate, release }
}

test('the first band drawing opens the pane at a fifth of the terminal with the latest PR explained', async ($, on) => {
  const state = world(on)

  await boot($)

  expect(state.opens).toEqual([{ id: 'pr-recap', columns: 40 }])
  expect(state.commands).toEqual(['pr-recap'])
  expect(state.diffRuns).toEqual([['git', '-c', 'core.quotePath=false', '--no-pager', 'diff', '--no-color', '--unified=1', `${LATEST}^1`, LATEST]])
  expect(state.modelCalls).toHaveLength(1)
  expect(state.modelCalls[0]?.model).toBe('haiku')
  expect(state.modelCalls[0]?.prompt).toContain('+predict()')

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    const drawn = await texts(ui)

    expect(await ui.findAll({ type: 'Button' })).toEqual([])
    expect(drawn).toContain('#381 [HARNESS] commit-guard reads a switch')
    expect(drawn).toContain('+54 -4 · 파일 3개 · 30분 전')
    expect(drawn).toContain('커밋 가드가 새 브랜치를 미리 알아본다.')
    expect(drawn).toContain('명령 체인')
    expect(drawn).toContain('   │ 분석 요청')
    expect(drawn).toContain('커밋 가드 ✎')
    expect(drawn).toContain('예측 로직 추가')
    expect(drawn).toContain('이전: #380 Revert the side pane · 30분 전')
    expect(drawn.filter(text => text === '   ▼')).toHaveLength(1)
    await ui.unmount()
  }
})

test('while the model runs the pane says so over the commit summary', async ($, on) => {
  const state = world(on)
  const model = gated()

  state.modelGate = model.gate
  await boot($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(await texts(ui)).toEqual(expect.arrayContaining(['Why one.', '요약과 구조도를 만드는 중…']))
  model.release()
  await settle()
  expect(await texts(ui)).toContain('커밋 가드가 새 브랜치를 미리 알아본다.')
  await ui.unmount()
})

test('a failed reply falls back to the commit summary with a note', async ($, on) => {
  const state = world(on)

  state.reply = null
  await boot($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(await texts(ui)).toEqual(expect.arrayContaining(['Why one.', '(구조도를 만들지 못했습니다)']))
  expect(state.store.size).toBe(0)
  await ui.unmount()
})

test('an unreadable reply falls back the same way', async ($, on) => {
  const state = world(on)

  state.reply = 'no json here'
  await boot($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(await texts(ui)).toContain('(구조도를 만들지 못했습니다)')
  await ui.unmount()
})

test('the explanation is kept by commit: a reread asks the model nothing', async ($, on) => {
  const state = world(on)

  await boot($)
  expect([...state.store.keys()]).toEqual([`pr-recap:explain:${LATEST}`])

  await $.tool.call({ tool: 'Bash', command: 'git pull' })
  await settle()
  expect(state.logRuns).toBe(2)
  expect(state.modelCalls).toHaveLength(1)
})

test('an explanation an earlier session kept is drawn without the model', async ($, on) => {
  const state = world(on)

  state.store.set(`pr-recap:explain:${LATEST}`, EXPLAIN)
  await boot($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(state.modelCalls).toEqual([])
  expect(state.diffRuns).toEqual([])
  expect(await texts(ui)).toContain('커밋 가드가 새 브랜치를 미리 알아본다.')
  await ui.unmount()
})

test('a wider terminal re-asks the open pane its share; the same width does not', async ($, on) => {
  const state = world(on)

  await boot($)
  await boot($)
  const wide = await $.ui.mount({ ...BAND, viewport: { columns: 300, rows: 50, isFullscreen: true }, surface: 'terminal' })

  await settle()
  await wide.unmount()

  expect(state.opens.map(open => open.columns)).toEqual([40, 60])
})

test('a Bash command that moves the history reads the PRs again; another does not', async ($, on) => {
  const state = world(on)

  await boot($)
  await $.tool.call({ tool: 'Bash', command: 'ls -la' })
  await settle()
  expect(state.logRuns).toBe(1)

  await $.tool.call({ tool: 'Bash', command: 'git pull --ff-only' })
  await settle()
  expect(state.logRuns).toBe(2)

  await $.tool.call({ tool: 'Bash', command: 'gh pr merge 12 --squash' })
  await settle()
  expect(state.logRuns).toBe(3)

  // The dev plugin's merge helper runs gh and git inside its own script.
  await $.tool.call({ tool: 'Bash', command: '/x/task-review-cycle/scripts/merge-and-cleanup.sh 12 main feat/x {}' })
  await settle()
  expect(state.logRuns).toBe(4)
})

test('a reread asked for while one runs follows it, once', async ($, on) => {
  const state = world(on)

  await boot($)
  const git = gated()

  state.gitGate = git.gate
  await $.tool.call({ tool: 'Bash', command: 'git fetch origin' })
  await $.tool.call({ tool: 'Bash', command: 'git merge FETCH_HEAD' })
  await $.tool.call({ tool: 'Bash', command: 'git pull' })
  await settle()
  expect(state.logRuns).toBe(2)

  git.release()
  await settle()
  expect(state.logRuns).toBe(3)
})

test('a boot that fails is tried again on the next band drawing', async ($, on) => {
  const state = world(on)

  state.registerFailures = 1
  await boot($)
  expect(state.opens).toEqual([])

  await boot($)
  expect(state.commands).toEqual(['pr-recap'])
  expect(state.opens).toEqual([{ id: 'pr-recap', columns: 40 }])
})

test('/pr-recap opens the pane at a fifth of the width it runs at', async ($, on) => {
  const state = world(on)

  await boot($)
  const ran = await $.command.run({
    command: 'pr-recap',
    args: '',
    presentation: { isFullscreen: true, columns: 160 },
  } as never)

  expect(ran).toMatchObject({ text: 'PR recap pane opened.' })
  expect(state.opens.map(open => open.columns)).toEqual([40, 32])
  expect(state.logRuns).toBe(2)
})

test('outside a git repository the pane says why', async ($, on) => {
  const state = world(on)

  state.log = null
  await boot($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(await texts(ui)).toEqual(['fatal: not a git repository'])
  expect(state.modelCalls).toEqual([])
  await ui.unmount()
})

test('switched off, the pane neither opens nor draws', { options: { prRecapEnabled: false } }, async ($, on) => {
  const state = world(on)

  await boot($)
  expect(state.opens).toEqual([])
  expect(state.logRuns).toBe(0)

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(await ui.find({ key: 'engine-empty' })).toBeDefined()
  await ui.unmount()
})
