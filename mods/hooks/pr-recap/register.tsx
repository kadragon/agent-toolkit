import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Pr, PrRecap, PrRecapView } from '../../types'
import { ago, fit, groupsOf, kindsOf, logArgv, parseLog, statBar, totalsOf } from './recap'

// After diffnav's file tree and CodeRabbit's walkthrough table: the last merged
// PRs as tabs, each one's files grouped by directory with a diffstat bar, the
// commit body as its summary, and a group opened to its files on a press.
export const PANE = 'pr-recap'
const TITLE = 'PR recap'
const COMMAND = 'pr-recap'
const DEFAULT_COUNT = 3
// First-parent commits read to find that many PRs among direct commits.
const LOG_WINDOW = 60
const GIT_TIMEOUT_MS = 5000
// The share of the terminal the docked pane asks, and the dock's own floor.
const SHARE = 0.2
const MIN_COLUMNS = 24
const BAR_CELLS = 8
// A Bash command that may move HEAD's history: git or gh directly, or the dev
// plugin's merge helper, which runs them inside its own script.
const MOVES_HISTORY =
  /\bgit\b[^\n|;&]*\b(merge|pull|checkout|switch|rebase|reset|fetch)\b|\bgh\s+pr\s+merge\b|merge-and-cleanup\.sh\b/

const recapAtom = atom({ plugin: 'mods', key: 'prRecap' } as const, null, { shape: 'pr-recap-1' })
const viewAtom = atom(
  { plugin: 'mods', key: 'prRecapView' } as const,
  { open: [], isSummaryOpen: false },
  { shape: 'pr-recap-view-1' },
)

// What the module keeps between hooks; a reload starts it over and boots again.
// `terminalColumns` is the width the band last drew at, handed over by band.tsx:
// the only drawing that spans the whole terminal.
const live = { terminalColumns: 0, askedColumns: 0, count: DEFAULT_COUNT, isBooted: false, isEnabled: false }

export const columnsFor = (terminalColumns: number): number =>
  Math.max(MIN_COLUMNS, Math.round(terminalColumns * SHARE))

function openPane($: EngineInterface) {
  const columns = live.terminalColumns > 0 ? columnsFor(live.terminalColumns) : undefined

  if (columns !== undefined) live.askedColumns = columns

  return $.ui.open({ id: PANE, title: TITLE, ...(columns === undefined ? {} : { columns }) })
}

async function readOnce($: EngineInterface): Promise<void> {
  let next: PrRecap

  try {
    const { exitCode, stdout, stderr, isStdoutTruncated } = await $.process.run(logArgv(LOG_WINDOW), {
      timeoutMs: GIT_TIMEOUT_MS,
    })

    next =
      exitCode === 0
        ? { prs: parseLog(stdout, live.count, isStdoutTruncated), readAt: await $.clock.now() }
        : { prs: [], readAt: await $.clock.now(), error: stderr.trim().split('\n')[0] || `git exited ${exitCode}` }
  } catch (error) {
    next = { prs: [], readAt: await $.clock.now(), error: String(error) }
  }

  await update($, recapAtom, () => next)
}

let loading: Promise<void> | undefined
// A read asked for while one runs: that one may have started before HEAD moved,
// so one more follows it.
let isStale = false

function load($: EngineInterface): Promise<void> {
  if (loading !== undefined) {
    isStale = true

    return loading
  }

  loading = (async () => {
    do {
      isStale = false
      await readOnce($)
    } while (isStale)
  })().finally(() => {
    loading = undefined
  })

  return loading
}

// The first band drawing boots the pane: the session is interactive and the
// terminal's width is known, so the dock opens at its share at once. The plugin
// takes one session.start hook, and the status band holds it. A width change
// later re-asks the open pane's share. Both run after the drawing: a render
// may not open a pane or write state.
async function boot($: EngineInterface) {
  await $.command.register({ name: COMMAND, description: 'Show the last merged PRs in a side pane' })
  await load($)
  await openPane($)
}

async function resize($: EngineInterface) {
  const panes = await $.ui.panes()

  if (panes.some(pane => pane.id === PANE)) await openPane($)
}

export function noteTerminalColumns($: EngineInterface, columns: number | undefined): void {
  if (!live.isEnabled || columns === undefined || columns <= 0 || columns === live.terminalColumns) return

  live.terminalColumns = columns

  const isBoot = !live.isBooted

  live.isBooted = true
  if (!isBoot && columnsFor(columns) === live.askedColumns) return

  void $.clock
    .sleep(0)
    .then(() => (isBoot ? boot($) : resize($)))
    .catch(() => {
      // A boot that failed is tried again on the next band drawing.
      if (isBoot) {
        live.isBooted = false
        live.terminalColumns = 0
      }
    })
}

const selectedOf = (prs: readonly Pr[], view: PrRecapView): Pr | undefined =>
  prs.find(pr => pr.number === view.selected) ?? prs[0]

const toggle = (list: readonly string[], key: string): string[] =>
  list.includes(key) ? list.filter(one => one !== key) : [...list, key]

export const register: Register = (on, options) => {
  live.isEnabled = options.prRecapEnabled !== false
  if (!live.isEnabled) return

  const asked = Math.round(Number(options.prRecapCount ?? DEFAULT_COUNT))

  live.count = Number.isFinite(asked) ? Math.min(DEFAULT_COUNT, Math.max(1, asked)) : DEFAULT_COUNT

  on('command.run', { command: COMMAND }, async ($, e) => {
    if (e.presentation.columns > 0) live.terminalColumns = e.presentation.columns
    await load($)
    await openPane($)

    return { text: 'PR recap pane opened.' }
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)

    if (MOVES_HISTORY.test(e.command)) void load($)

    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const recap = await read($, recapAtom)
    const view = await read($, viewAtom)
    const now = await $.clock.now()
    const width = Math.max(MIN_COLUMNS - 2, e.props.bodyColumns)

    if (recap === null) return <Text dimColor>Reading git log…</Text>

    const refresh = (
      <Button key="refresh" hotkey="r" plain onPress={() => void load($)}>
        refresh <Text dimColor>· read {ago(recap.readAt, now)}</Text>
      </Button>
    )

    if (recap.error !== undefined || recap.prs.length === 0) {
      return (
        <Box flexDirection="column">
          <Text dimColor wrap="wrap">
            {recap.error ?? 'No merged PR in this branch history.'}
          </Text>
          {refresh}
        </Box>
      )
    }

    const pr = selectedOf(recap.prs, view) as Pr
    const totals = totalsOf(pr.files)
    const groups = groupsOf(pr.files)
    const scale = Math.max(1, ...groups.map(group => group.added + group.deleted))
    const kinds = kindsOf(pr.files)
      .map(entry => `${entry.kind} ${entry.files}`)
      .join(' · ')
    const select = (number: number) => () =>
      void update($, viewAtom, current => ({ ...current, selected: number }))

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" gap={1}>
          {recap.prs.map((one, index) => (
            <Button
              key={`pr:${one.number}`}
              hotkey={String(index + 1)}
              variant={one.number === pr.number ? 'primary' : 'secondary'}
              onPress={select(one.number)}
            >
              #{String(one.number)}
            </Button>
          ))}
        </Box>
        <Text bold wrap="wrap">
          {pr.tag === undefined ? '' : `[${pr.tag}] `}
          {pr.title}
        </Text>
        <Text dimColor wrap="truncate-end">
          {pr.author} · {ago(pr.mergedAt, now)} · {pr.sha.slice(0, 7)}
        </Text>
        <Text wrap="truncate-end">
          <Text color="success">+{String(totals.added)}</Text> <Text color="error">-{String(totals.deleted)}</Text>
          <Text dimColor>
            {' '}
            · {String(pr.files.length)} files{kinds === '' ? '' : ` · ${kinds}`}
          </Text>
        </Text>
        {pr.summary.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Button
              key="summary"
              hotkey="s"
              plain
              onPress={() => void update($, viewAtom, current => ({ ...current, isSummaryOpen: !current.isSummaryOpen }))}
            >
              {view.isSummaryOpen ? '▾' : '▸'} summary
            </Button>
            {view.isSummaryOpen ? (
              pr.summary.map(paragraph => (
                <Text wrap="wrap" dimColor>
                  {paragraph}
                </Text>
              ))
            ) : (
              <Text dimColor wrap="truncate-end">
                {(pr.summary[0] ?? '').split('\n')[0]}
              </Text>
            )}
          </Box>
        )}
        <Box flexDirection="column" marginTop={1}>
          {groups.map(group => {
            const key = `${pr.number}:${group.dir}`
            const isOpen = view.open.includes(key)
            const bar = statBar(group.added, group.deleted, scale, BAR_CELLS)
            const stat = `${group.files.length}f`
            const room = Math.max(4, width - 2 - stat.length - 1 - bar.plus.length - bar.minus.length - 1)

            return (
              <Box flexDirection="column">
                <Button
                  key={`dir:${key}`}
                  plain
                  onPress={() => void update($, viewAtom, current => ({ ...current, open: toggle(current.open, key) }))}
                >
                  {isOpen ? '▾' : '▸'} {fit(`${group.dir}/`, room)} <Text dimColor>{stat}</Text>{' '}
                  <Text color="success">{bar.plus}</Text>
                  <Text color="error">{bar.minus}</Text>
                </Button>
                {isOpen &&
                  group.files.map(file => {
                    const name = file.path.slice(group.dir === '.' ? 0 : group.dir.length + 1)
                    const delta = file.isBinary ? 'bin' : `+${file.added} -${file.deleted}`

                    return (
                      <Text wrap="truncate-end">
                        {'   '}
                        {fit(name, Math.max(4, width - 4 - delta.length))}{' '}
                        <Text dimColor>{delta}</Text>
                      </Text>
                    )
                  })}
              </Box>
            )
          })}
        </Box>
        <Box marginTop={1}>{refresh}</Box>
      </Box>
    )
  })
}
