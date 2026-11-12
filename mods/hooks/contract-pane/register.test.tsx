import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

const CONTRACT = [
  '# mods: contract pane',
  '',
  '**Tag:** [FEAT]',
  '**Acceptance criteria:**',
  '- [ ] Parser reads the report → claude plugin test ./mods',
  '- [ ] Lint is clean → ruff check .',
  '- [ ] Seen by eye → observation in the pane',
  '**Out of scope:** nothing',
].join('\n')
const REPORT = {
  branch: 'feat/x',
  contract: CONTRACT,
  evidence: [
    { command: 'claude plugin test ./mods', exit_code: 0 },
    { command: 'ruff check .', exit_code: 1 },
    { command: 'bash scripts/other.sh', exit_code: 0 },
  ],
  notes: 'tried X\n',
  tree_matches_current: false,
}
const INSTALLED = '/home/me/.claude/plugins/installed_plugins.json'

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
    bodyColumns: 60,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

type World = {
  branch: string | null
  // Set to make inspect fail (exit 1) or come back cut.
  inspectFault?: 'exit' | 'truncated'
  report: Record<string, unknown>
  isDevOn: boolean
  inspects: number
  opens: string[]
  commands: string[]
}

const world = (on: On): World => {
  const state: World = { branch: 'feat/x', report: REPORT, isDevOn: true, inspects: 0, opens: [], commands: [] }
  const run = { isStdoutTruncated: false, isStderrTruncated: false, stderr: '' }

  on('clock.now', async () => ({ value: 1_000 }))
  on('clock.sleep', async () => ({ value: undefined }))
  on('session.cwd', async () => ({ value: '/work/repo' }))
  on('env.get', async ($, e) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('settings.read', async () => ({ value: state.isDevOn ? { enabledPlugins: { 'dev@kadragon': true } } : {} }))
  on('fs.read', async ($, e) => {
    if (e.path.endsWith('installed_plugins.json')) {
      return { value: JSON.stringify({ plugins: { 'dev@kadragon': [{ installPath: '/p/dev' }] } }) }
    }

    throw new Error(`no such file: ${e.path}`)
  })
  on('fs.exists', async ($, e) => ({ value: e.path === INSTALLED }))
  on('command.register', async ($, e) => {
    state.commands.push(e.name)

    return { value: { command: e.name } }
  })
  on('ui.open', async ($, e) => {
    state.opens.push(e.id)

    return { value: { isPlaced: true } }
  })
  on('ui.panes', async () => ({
    value: state.opens.map(id => ({ id, title: 'PR recap', isShown: true, isFocused: false, isPlaced: true })),
  }) as never)
  on('process.run', async ($, e) => {
    if (e.argv[0] === 'git' && e.argv.includes('--show-current')) {
      return state.branch === null
        ? { value: { ...run, exitCode: 128, stdout: '' } }
        : { value: { ...run, exitCode: 0, stdout: `${state.branch}\n` } }
    }

    if (e.argv.some(arg => arg.endsWith('/p/dev/skills/task-next/scripts/cycle_state.py')) && e.argv.includes('inspect')) {
      state.inspects += 1
      if (state.inspectFault === 'exit') return { value: { ...run, exitCode: 1, stdout: '' } }
      if (state.inspectFault === 'truncated') {
        return { value: { ...run, isStdoutTruncated: true, exitCode: 0, stdout: JSON.stringify(state.report).slice(0, 40) } }
      }

      return { value: { ...run, exitCode: 0, stdout: JSON.stringify(state.report) } }
    }

    return { value: { ...run, exitCode: 1, stdout: '' } }
  })
  on('tool.call', { tool: 'Bash' }, async () => ({ result: {} }))
  on('ui.render', async ($, e) => {
    const { Box } = $.ui.resolve(e)

    return <Box key="engine-empty" />
  })

  return state
}

// The status band reads the same contract with the same script: off here.
const ALONE = { options: { statusBandEnabled: false } }

const settle = () => new Promise<void>(resolve => setTimeout(resolve, 20))

// The first band drawing boots the PR recap pane, which reads the section first.
const boot = async ($: Engine) => {
  const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await settle()
  await band.unmount()
}

const reopen = async ($: Engine) => {
  await $.command.run({ command: 'pr-recap', args: '', presentation: { isFullscreen: true, columns: 160 } } as never)
  await settle()
}

const bash = async ($: Engine, command: string) => {
  await $.tool.call({ tool: 'Bash', command } as never)
  await settle()
}

const texts = async (ui: { findAll: (query: { type: 'Text' }) => Promise<{ text?: string }[]> }) =>
  (await ui.findAll({ type: 'Text' })).map(found => found.text)

const drawn = async ($: Engine) => {
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  const found = await texts(ui)

  await ui.unmount()

  return found
}

const RULE = '─'.repeat(60)

test('the PR recap pane opens with the contract on top, each criterion marked by the run its check names', ALONE, async ($, on) => {
  const state = world(on)

  await boot($)
  expect(state.opens).toEqual(['pr-recap'])
  expect(state.inspects).toBe(1)

  const found = await drawn($)

  expect(found.slice(0, 4)).toEqual([
    '[FEAT] mods: contract pane',
    '기준 3개 · 통과 1 · 실패 1 · 미확인 1',
    '검증 3건 · 트리가 바뀜, 다시 실행 필요',
    '⚑ 막힌 기록 있음 (cycle_state.py inspect)',
  ])
  expect(found).toContain('✓ Parser reads the report')
  expect(found).toContain('✗ Lint is clean')
  expect(found).toContain('· Seen by eye')
  expect(found).toContain('  → observation in the pane')
  expect(found).toContain('기준에 이어지지 않은 실행')
  expect(found).toContain('✓ bash scripts/other.sh')
  // The PR recap follows one rule below: here git has no log to give.
  expect(found.indexOf(RULE)).toBeGreaterThan(found.indexOf('✓ bash scripts/other.sh'))
  expect(found.slice(found.indexOf(RULE) + 1)).toEqual(['git exited 1'])
})

test('runs that match the tree read as current; none recorded says so', ALONE, async ($, on) => {
  const state = world(on)

  state.report = { ...REPORT, tree_matches_current: true, notes: null }
  await boot($)
  expect(await drawn($)).toContain('검증 3건 · 현재 트리와 일치')

  state.report = { ...REPORT, evidence: null, notes: null }
  await reopen($)

  const found = await drawn($)

  expect(found).toContain('기록된 검증 실행 없음')
  expect(found).toContain('기준 3개 · 통과 0 · 실패 0 · 미확인 3')
  expect(found).not.toContain('⚑ 막힌 기록 있음 (cycle_state.py inspect)')
})

test('with no contract the section folds to one line above the PR recap', ALONE, async ($, on) => {
  const state = world(on)
  const cases: [Partial<World>, string][] = [
    [{ report: { branch: 'feat/x', contract: null } }, 'Sprint Contract · 저장된 계약 없음'],
    [{ branch: 'main' }, 'Sprint Contract · 없음 (main)'],
    [{ branch: '' }, 'Sprint Contract · detached HEAD'],
    [{ branch: null }, 'Sprint Contract · git 저장소 아님'],
    [{ isDevOn: false }, 'Sprint Contract · dev 플러그인 꺼짐'],
  ]

  await boot($)
  for (const [change, line] of cases) {
    Object.assign(state, { branch: 'feat/x', report: REPORT, isDevOn: true }, change)
    await reopen($)
    expect((await drawn($)).slice(0, 3)).toEqual([line, RULE, 'git exited 1'])
  }
})

test('a command of the cycle rereads the section; another does not, nor one before the pane boots', ALONE, async ($, on) => {
  const state = world(on)

  await bash($, 'python3 "$STATE" evidence --command x --exit 0')
  expect(state.inspects).toBe(0)

  await boot($)
  expect(state.inspects).toBe(1)

  await bash($, 'ls -la')
  expect(state.inspects).toBe(1)

  // Staging moves the index the evidence is matched against.
  await bash($, 'git add -A')
  expect(state.inspects).toBe(2)

  state.report = { ...REPORT, tree_matches_current: true }
  await bash($, 'python3 "$STATE" evidence --command x --exit 0')
  expect(state.inspects).toBe(3)
  expect(await drawn($)).toContain('검증 3건 · 현재 트리와 일치')
})

test('a reread that fails or comes back cut keeps the contract shown, with the error', ALONE, async ($, on) => {
  const state = world(on)

  await boot($)
  state.inspectFault = 'truncated'
  await bash($, 'git add -A')

  let found = await drawn($)

  expect(found).toContain('[FEAT] mods: contract pane')
  expect(found).toContain('다시 읽기 실패: cycle_state.py inspect 출력이 잘림')

  state.inspectFault = undefined
  await bash($, 'git add -A')
  found = await drawn($)
  expect(found.some(text => text?.startsWith('다시 읽기 실패') === true)).toBe(false)
})

test('a first read that fails folds to one line saying why', ALONE, async ($, on) => {
  const state = world(on)

  state.inspectFault = 'exit'
  await boot($)
  expect((await drawn($)).slice(0, 1)).toEqual(['Sprint Contract · cycle_state.py inspect 실패'])
})

test('r rereads the section by hand', ALONE, async ($, on) => {
  const state = world(on)

  await boot($)
  state.report = { ...REPORT, tree_matches_current: true }

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect((await ui.find({ key: 'reload' }))?.props).toMatchObject({ hotkey: 'r' })
  await $.ui.press({ plugin: 'mods', key: 'reload' })
  await settle()
  expect(state.inspects).toBe(2)
  await ui.unmount()
  expect(await drawn($)).toContain('검증 3건 · 현재 트리와 일치')
})

test('switched off, the section is gone and nothing is read', { options: { statusBandEnabled: false, contractPaneEnabled: false } }, async ($, on) => {
  const state = world(on)

  await boot($)
  await bash($, 'git add -A')
  expect(state.inspects).toBe(0)
  expect(await drawn($)).toEqual(['git exited 1'])
})

test('with the PR recap pane off, no pane opens and nothing is read', { options: { statusBandEnabled: false, prRecapEnabled: false } }, async ($, on) => {
  const state = world(on)

  await boot($)
  await bash($, 'git add -A')
  expect(state.opens).toEqual([])
  expect(state.inspects).toBe(0)
})
