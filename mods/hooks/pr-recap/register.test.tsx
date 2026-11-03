import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

const NOW = 1793589760 * 1000 + 30 * 60_000
const RS = '\x1e'
const US = '\x1f'
const GS = '\x1d'
const record = (sha: string, subject: string, body: string, numstat: string[]) =>
  `${RS}${sha}${US}${subject}${US}kangdonguk${US}1793589760${US}${body}${GS}\n\n${numstat.join('\n')}\n`
const LOG = [
  record('c31d51bc34550d835dfce3c958b2e422864aa3c7', '[HARNESS] commit-guard reads a switch (#381)', 'Why one.\n\nHow two.\n', [
    '12\t3\tdev/hooks/commit-guard/guard.py',
    '40\t0\tdev/hooks/commit-guard/test_guard.py',
    '2\t1\tCHANGELOG.md',
  ]),
  record('4a0c69c0000000000000000000000000000000000', '[HARNESS] Revert the side pane (#380)', '', ['0\t9\tdev/x.sh']),
  record('3d01722000000000000000000000000000000000', 'direct commit', '', ['1\t1\ta.md']),
  record('3d01722100000000000000000000000000000000', '[FEAT] task-review side pane (#378)', '', ['9\t0\tdev/x.sh']),
  record('77426d3000000000000000000000000000000000', '[FIX] backlog (#377)', '', ['1\t0\tb.py']),
].join('')

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
  gitRuns: (readonly string[])[]
  opens: { id: string; columns?: number }[]
  commands: string[]
}

const world = (on: On): World => {
  const state: World = { log: LOG, gitRuns: [], opens: [], commands: [] }

  on('clock.now', async () => ({ value: NOW }))
  on('clock.sleep', async () => ({ value: undefined }))
  on('command.register', async ($, e) => {
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
    state.gitRuns.push(e.argv)

    const run = { isStdoutTruncated: false, isStderrTruncated: false }

    if (state.log === null) return { value: { ...run, exitCode: 128, stdout: '', stderr: 'fatal: not a git repository\n' } }

    return { value: { ...run, exitCode: 0, stdout: state.log, stderr: '' } }
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

test('the first band drawing opens the pane at a fifth of the terminal, with the last three PRs', async ($, on) => {
  const state = world(on)

  await boot($)

  expect(state.opens).toEqual([{ id: 'pr-recap', columns: 40 }])
  expect(state.commands).toEqual(['pr-recap'])
  expect(state.gitRuns).toHaveLength(1)
  expect(state.gitRuns[0]).toContain('--first-parent')

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    const buttons = (await ui.findAll({ type: 'Button' })).map(found => found.key)

    expect(buttons.slice(0, 3)).toEqual(['pr:381', 'pr:380', 'pr:378'])
    expect(await ui.find({ type: 'Text', text: /\[HARNESS\] commit-guard reads a switch/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /kangdonguk · 30m ago · c31d51b/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /\+54 -4 · 3 files · code 1 · test 1 · docs 1/ })).toBeDefined()
    expect(await ui.find({ key: 'dir:381:dev/hooks/commit-guard' })).toBeDefined()
    await ui.unmount()
  }
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

test('pressing a tab, a group, the summary and refresh', async ($, on) => {
  const state = world(on)

  await boot($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(await ui.find({ type: 'Text', text: /guard\.py/ })).toBeUndefined()
  await ui.press({ key: 'dir:381:dev/hooks/commit-guard' })
  expect(await ui.find({ type: 'Text', text: /guard\.py \+12 -3/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /test_guard\.py \+40 -0/ })).toBeDefined()
  await ui.press({ key: 'dir:381:dev/hooks/commit-guard' })
  expect(await ui.find({ type: 'Text', text: /guard\.py/ })).toBeUndefined()

  expect(await texts(ui)).toContain('Why one.')
  expect(await texts(ui)).not.toContain('How two.')
  await ui.press({ key: 'summary' })
  expect(await texts(ui)).toContain('How two.')

  await ui.press({ key: 'pr:378' })
  expect(await ui.find({ type: 'Text', text: /\[FEAT\] task-review side pane/ })).toBeDefined()
  expect(await ui.find({ key: 'summary' })).toBeUndefined()

  await ui.press({ key: 'refresh' })
  expect(state.gitRuns).toHaveLength(2)
  await ui.unmount()
})

test('a Bash command that moves the history reads the PRs again; another does not', async ($, on) => {
  const state = world(on)

  await boot($)
  await $.tool.call({ tool: 'Bash', command: 'ls -la' })
  await settle()
  expect(state.gitRuns).toHaveLength(1)

  await $.tool.call({ tool: 'Bash', command: 'git pull --ff-only' })
  await settle()
  expect(state.gitRuns).toHaveLength(2)

  await $.tool.call({ tool: 'Bash', command: 'gh pr merge 12 --squash' })
  await settle()
  expect(state.gitRuns).toHaveLength(3)
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
  expect(state.gitRuns).toHaveLength(2)
})

test('outside a git repository the pane says why and offers refresh', async ($, on) => {
  const state = world(on)

  state.log = null
  await boot($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(await texts(ui)).toContain('fatal: not a git repository')
  expect(await ui.find({ key: 'refresh' })).toBeDefined()
  await ui.unmount()
})

test('prRecapCount shows fewer tabs', { options: { prRecapCount: 1 } }, async ($, on) => {
  world(on)

  await boot($)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect((await ui.findAll({ type: 'Button' })).filter(found => found.key?.startsWith('pr:'))).toHaveLength(1)
  await ui.unmount()
})

test('switched off, the pane neither opens nor draws', { options: { prRecapEnabled: false } }, async ($, on) => {
  const state = world(on)

  await boot($)
  expect(state.opens).toEqual([])
  expect(state.gitRuns).toEqual([])

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  expect(await ui.find({ key: 'engine-empty' })).toBeDefined()
  await ui.unmount()
})
