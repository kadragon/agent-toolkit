import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { NodeChange, Pr, PrExplain, PrRecap } from '../../types'
import {
  count,
  diffArgv,
  EXPLAIN_MAX_TOKENS,
  EXPLAIN_MODEL,
  EXPLAIN_SYSTEM,
  EXPLAIN_TIMEOUT_MS,
  explainPrompt,
  MARKS,
  parseExplain,
} from './explain'
import { ago, logArgv, parseLog, totalsOf } from './recap'

// The latest merged PR, read without a key: its numbers, a plain summary and a
// top-to-bottom diagram of the parts it touches, both made once per commit by a
// small model; the PR before it as one line.
export const PANE = 'pr-recap'
const TITLE = 'PR recap'
const COMMAND = 'pr-recap'
// The latest PR and the one before it.
const PR_COUNT = 2
// First-parent commits read to find them among direct commits.
const LOG_WINDOW = 60
const GIT_TIMEOUT_MS = 5000
// The share of the terminal the docked pane asks, and the dock's own floor.
const SHARE = 0.2
const MIN_COLUMNS = 24
const MAX_BOX_COLUMNS = 34
const STORE_PREFIX = 'pr-recap:explain:'
// A Bash command that may move HEAD's history: git or gh directly, or the dev
// plugin's merge helper, which runs them inside its own script.
const MOVES_HISTORY =
  /\bgit\b[^\n|;&]*\b(merge|pull|checkout|switch|rebase|reset|fetch)\b|\bgh\s+pr\s+merge\b|merge-and-cleanup\.sh\b/
const BORDERS: Record<NodeChange, 'success' | 'warning' | 'error' | undefined> = {
  added: 'success',
  changed: 'warning',
  removed: 'error',
  same: undefined,
}

const recapAtom = atom({ plugin: 'mods', key: 'prRecap' } as const, null, { shape: 'pr-recap-1' })
const explainAtom = atom({ plugin: 'mods', key: 'prRecapExplain' } as const, null, {
  shape: 'pr-recap-explain-1',
})

// What the module keeps between hooks; a reload starts it over and boots again.
// `terminalColumns` is the width the band last drew at, handed over by band.tsx:
// the only drawing that spans the whole terminal. `asked` holds the commits an
// explanation was started for, so a failure is not asked again in a loop.
const live = {
  terminalColumns: 0,
  askedColumns: 0,
  isBooted: false,
  isEnabled: false,
  asked: new Set<string>(),
}

export const columnsFor = (terminalColumns: number): number =>
  Math.max(MIN_COLUMNS, Math.round(terminalColumns * SHARE))

function openPane($: EngineInterface) {
  const columns = live.terminalColumns > 0 ? columnsFor(live.terminalColumns) : undefined

  if (columns !== undefined) live.askedColumns = columns

  return $.ui.open({ id: PANE, title: TITLE, ...(columns === undefined ? {} : { columns }) })
}

// The latest PR explained: from the store when an earlier session made it, else
// by the model over the commit, its files and its capped diff.
async function explain($: EngineInterface, pr: Pr): Promise<void> {
  if (live.asked.has(pr.sha)) return
  live.asked.add(pr.sha)

  const key = `${STORE_PREFIX}${pr.sha}`
  const stored = await $.store.get(key).catch(() => undefined)
  // A stored value passes the same checks a reply does.
  const kept = stored === undefined || stored === null ? undefined : parseExplain(JSON.stringify(stored))

  if (kept !== undefined) {
    await update($, explainAtom, () => ({ sha: pr.sha, status: 'ready' as const, explain: kept }))

    return
  }

  await update($, explainAtom, () => ({ sha: pr.sha, status: 'pending' as const }))

  let made: PrExplain | undefined

  try {
    const diff = await $.process
      .run(diffArgv(pr.sha), { timeoutMs: GIT_TIMEOUT_MS })
      .then(run => (run.exitCode === 0 ? run.stdout : ''))
      .catch(() => '')
    const reply = await $.model.complete({
      model: EXPLAIN_MODEL,
      system: EXPLAIN_SYSTEM,
      prompt: explainPrompt(pr, diff),
      maxTokens: EXPLAIN_MAX_TOKENS,
      timeoutMs: EXPLAIN_TIMEOUT_MS,
    })

    made = reply.isAnswered ? parseExplain(reply.text) : undefined
  } catch {
    made = undefined
  }

  if (made === undefined) {
    await update($, explainAtom, () => ({ sha: pr.sha, status: 'failed' as const }))

    return
  }

  await $.store.set(key, made).catch(() => undefined)
  await update($, explainAtom, () => ({ sha: pr.sha, status: 'ready' as const, explain: made }))
}

async function readOnce($: EngineInterface): Promise<void> {
  let next: PrRecap

  try {
    const { exitCode, stdout, stderr, isStdoutTruncated } = await $.process.run(logArgv(LOG_WINDOW), {
      timeoutMs: GIT_TIMEOUT_MS,
    })

    next =
      exitCode === 0
        ? { prs: parseLog(stdout, PR_COUNT, isStdoutTruncated), readAt: await $.clock.now() }
        : { prs: [], readAt: await $.clock.now(), error: stderr.trim().split('\n')[0] || `git exited ${exitCode}` }
  } catch (error) {
    next = { prs: [], readAt: await $.clock.now(), error: String(error) }
  }

  await update($, recapAtom, () => next)

  const latest = next.prs[0]

  if (latest !== undefined) void explain($, latest).catch(() => undefined)
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
  await $.command.register({ name: COMMAND, description: 'Show the latest merged PR in a side pane' })
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

export const register: Register = (on, options) => {
  live.isEnabled = options.prRecapEnabled !== false
  if (!live.isEnabled) return

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
    const { Box, Text } = $.ui.resolve(e)
    const recap = await read($, recapAtom)
    const state = await read($, explainAtom)
    const now = await $.clock.now()
    const boxColumns = Math.min(MAX_BOX_COLUMNS, Math.max(MIN_COLUMNS - 2, e.props.bodyColumns))

    if (recap === null) return <Text dimColor>git 이력을 읽는 중…</Text>

    const pr = recap.prs[0]

    if (recap.error !== undefined || pr === undefined) {
      return (
        <Text dimColor wrap="wrap">
          {recap.error ?? '이 브랜치 이력에 머지된 PR이 없습니다.'}
        </Text>
      )
    }

    const totals = totalsOf(pr.files)
    const previous = recap.prs[1]
    const made = state?.sha === pr.sha ? state : undefined
    const fallback = pr.summary[0] ?? ''

    return (
      <Box flexDirection="column">
        <Text bold wrap="wrap">
          #{String(pr.number)} {pr.tag === undefined ? '' : `[${pr.tag}] `}
          {pr.title}
        </Text>
        <Text wrap="truncate-end">
          <Text color="success">+{count(totals.added)}</Text> <Text color="error">-{count(totals.deleted)}</Text>
          <Text dimColor>
            {' '}
            · 파일 {String(pr.files.length)}개 · {ago(pr.mergedAt, now)}
          </Text>
        </Text>
        <Box flexDirection="column" marginTop={1}>
          {made?.status === 'ready' && made.explain !== undefined ? (
            <Box flexDirection="column">
              {made.explain.summary !== '' && <Text wrap="wrap">{made.explain.summary}</Text>}
              {made.explain.nodes.map((node, index) => (
                <Box flexDirection="column" marginTop={index === 0 ? 1 : 0}>
                  <Box
                    flexDirection="column"
                    borderStyle="round"
                    width={boxColumns}
                    paddingX={1}
                    {...(BORDERS[node.change] === undefined
                      ? { borderDimColor: true }
                      : { borderColor: BORDERS[node.change] })}
                  >
                    <Text bold wrap="truncate-end">
                      {node.name}
                      {MARKS[node.change] === '' ? '' : ` ${MARKS[node.change]}`}
                    </Text>
                    {node.note !== '' && (
                      <Text dimColor wrap="truncate-end">
                        {node.note}
                      </Text>
                    )}
                  </Box>
                  {index < (made.explain?.nodes.length ?? 0) - 1 && (
                    <Box flexDirection="column">
                      <Text dimColor wrap="truncate-end">
                        {'   │ '}
                        {node.link}
                      </Text>
                      <Text dimColor>{'   ▼'}</Text>
                    </Box>
                  )}
                </Box>
              ))}
              {made.explain.nodes.length > 0 && <Text dimColor>★ 새로 추가 ✎ 수정 ✕ 제거</Text>}
            </Box>
          ) : (
            <Box flexDirection="column">
              {fallback !== '' && (
                <Text wrap="wrap" dimColor>
                  {fallback}
                </Text>
              )}
              <Text dimColor wrap="wrap">
                {made?.status === 'failed' ? '(구조도를 만들지 못했습니다)' : '요약과 구조도를 만드는 중…'}
              </Text>
            </Box>
          )}
        </Box>
        {previous !== undefined && (
          <Box marginTop={1}>
            <Text dimColor wrap="truncate-end">
              이전: #{String(previous.number)} {previous.title} · {ago(previous.mergedAt, now)}
            </Text>
          </Box>
        )}
      </Box>
    )
  })
}
