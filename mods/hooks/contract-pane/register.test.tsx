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
  requestId: 'contract',
  props: {
    title: 'Sprint Contract',
    isFocused: false,
    bodyColumns: 60,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

type World = {
  branch: string | null
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
    value: state.opens.map(id => ({ id, title: 'Sprint Contract', isShown: true, isFocused: false, isPlaced: true })),
  }) as never)
  on('process.run', async ($, e) => {
    if (e.argv[0] === 'git' && e.argv.includes('--show-current')) {
      return state.branch === null
        ? { value: { ...run, exitCode: 128, stdout: '' } }
        : { value: { ...run, exitCode: 0, stdout: `${state.branch}\n` } }
    }

    if (e.argv.some(arg => arg.endsWith('/p/dev/skills/task-next/scripts/cycle_state.py')) && e.argv.includes('inspect')) {
      state.inspects += 1

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

// The other mods read the same contract and register their own commands: off here.
const ALONE = { options: { statusBandEnabled: false, prRecapEnabled: false } }

const settle = () => new Promise<void>(resolve => setTimeout(resolve, 20))

// The first band drawing registers /contract, as a session's first frame does.
const boot = async ($: Engine) => {
  const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await settle()
  await band.unmount()
}

const open = ($: Engine) =>
  $.command.run({ command: 'contract', args: '', presentation: { isFullscreen: true, columns: 160 } } as never)

const texts = async (ui: { findAll: (query: { type: 'Text' }) => Promise<{ text?: string }[]> }) =>
  (await ui.findAll({ type: 'Text' })).map(found => found.text)

const drawn = async ($: Engine) => {
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  const found = await texts(ui)

  await ui.unmount()

  return found
}

test('/contract opens the pane with each criterion marked by the run its check names', ALONE, async ($, on) => {
  const state = world(on)

  await boot($)
  expect(state.commands).toEqual(['contract'])
  expect(state.inspects).toBe(0)

  expect(await open($)).toMatchObject({ text: 'Sprint Contract pane opened.' })
  expect(state.opens).toEqual(['contract'])

  const found = await drawn($)

  expect(found).toContain('[FEAT] mods: contract pane')
  expect(found).toContain('기준 3개 · 통과 1 · 실패 1 · 미확인 1')
  expect(found).toContain('검증 3건 · 트리가 바뀜, 다시 실행 필요')
  expect(found).toContain('⚑ 막힌 기록 있음 (cycle_state.py inspect)')
  expect(found).toContain('✓ Parser reads the report')
  expect(found).toContain('✗ Lint is clean')
  expect(found).toContain('· Seen by eye')
  expect(found).toContain('  → observation in the pane')
  expect(found).toContain('기준에 이어지지 않은 실행')
  expect(found).toContain('✓ bash scripts/other.sh')
})

test('runs that match the tree read as current; none recorded says so', ALONE, async ($, on) => {
  const state = world(on)

  state.report = { ...REPORT, tree_matches_current: true, notes: null }
  await boot($)
  await open($)
  expect(await drawn($)).toContain('검증 3건 · 현재 트리와 일치')

  state.report = { ...REPORT, evidence: null, notes: null }
  await open($)

  const found = await drawn($)

  expect(found).toContain('기록된 검증 실행 없음')
  expect(found).toContain('기준 3개 · 통과 0 · 실패 0 · 미확인 3')
  expect(found).not.toContain('⚑ 막힌 기록 있음 (cycle_state.py inspect)')
})

test('with no contract, on the base branch, on a detached HEAD, outside git or without the dev plugin the pane says why', ALONE, async ($, on) => {
  const state = world(on)

  await boot($)

  state.report = { branch: 'feat/x', contract: null }
  await open($)
  expect(await drawn($)).toEqual(['이 브랜치에 저장된 Sprint Contract가 없습니다.'])

  state.branch = 'main'
  await open($)
  expect(await drawn($)).toEqual(['기본 브랜치 (main)에는 계약이 없습니다.'])

  state.branch = ''
  await open($)
  expect(await drawn($)).toEqual(['HEAD가 브랜치에 있지 않습니다 (detached HEAD).'])

  state.branch = null
  await open($)
  expect(await drawn($)).toEqual(['git 저장소가 아닙니다.'])

  state.branch = 'feat/x'
  state.isDevOn = false
  await open($)
  expect(await drawn($)).toEqual(['dev 플러그인이 켜져 있지 않습니다.'])
})

test('while open, a command of the cycle rereads the contract; another does not', ALONE, async ($, on) => {
  const state = world(on)

  await boot($)

  // Closed, nothing is read.
  await $.tool.call({ tool: 'Bash', command: 'python3 "$STATE" evidence --command x --exit 0' } as never)
  await settle()
  expect(state.inspects).toBe(0)

  await open($)
  expect(state.inspects).toBe(1)

  await $.tool.call({ tool: 'Bash', command: 'ls -la' } as never)
  await settle()
  expect(state.inspects).toBe(1)

  // Staging moves the index the evidence is matched against.
  await $.tool.call({ tool: 'Bash', command: 'git add -A' } as never)
  await settle()
  expect(state.inspects).toBe(2)

  state.report = { ...REPORT, tree_matches_current: true }
  await $.tool.call({ tool: 'Bash', command: 'python3 "$STATE" evidence --command x --exit 0' } as never)
  await settle()
  expect(state.inspects).toBe(3)
  expect(await drawn($)).toContain('검증 3건 · 현재 트리와 일치')
})

test('switched off, /contract is not registered and the pane does not draw', { options: { contractPaneEnabled: false, prRecapEnabled: false } }, async ($, on) => {
  const state = world(on)

  await boot($)
  expect(state.commands).toEqual([])

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(await ui.find({ key: 'engine-empty' })).toBeDefined()
  await ui.unmount()
})
