import type { ExplainNode, NodeChange, Pr, PrExplain } from '../../types'

export const EXPLAIN_MODEL = 'haiku'
export const EXPLAIN_MAX_TOKENS = 1200
export const EXPLAIN_TIMEOUT_MS = 60_000
// How much of the diff the model reads: enough to see what calls what.
export const DIFF_CAP = 16_000
const MAX_NODES = 5
// Korean characters draw two cells wide: these keep a box within a 40-column pane.
const NAME_CELLS = 10
const NOTE_CELLS = 14
const LINK_CELLS = 14
const SUMMARY_CHARS = 240
const CHANGES: readonly NodeChange[] = ['added', 'changed', 'removed', 'same']

// The diff the model reads, against the parent the PR landed on.
export const diffArgv = (sha: string): string[] => [
  'git',
  '-c',
  'core.quotePath=false',
  '--no-pager',
  'diff',
  '--no-color',
  '--unified=1',
  `${sha}^1`,
  sha,
]

export const capDiff = (diff: string): string =>
  diff.length <= DIFF_CAP ? diff : `${diff.slice(0, DIFF_CAP)}\n… (diff cut at ${DIFF_CAP} characters)`

export const EXPLAIN_SYSTEM = `You explain one merged pull request to its own author, who wants to grasp what changed without reading code.
Answer with one JSON object and nothing else:
{"summary": string, "nodes": [{"name": string, "note": string, "change": "added"|"changed"|"removed"|"same", "link": string}]}
- summary: 2-3 short, plain Korean sentences: what the PR does and why. No file paths, no code identifiers unless unavoidable.
- nodes: 2-${MAX_NODES} parts of the system this PR touches or relies on, in the order work or data flows through them, top to bottom.
  name: Korean, at most ${NAME_CELLS} characters, a role ("상태 표시줄", "git 이력"), not a file name.
  note: Korean, at most ${NOTE_CELLS} characters, what this PR did to it or what it does here.
  change: added (new in this PR), changed (modified), removed (deleted), same (untouched context).
  link: Korean, at most ${LINK_CELLS} characters, how this node hands over to the next ("화면 폭 전달"); "" on the last node.`

export const explainPrompt = (pr: Pr, diff: string): string =>
  [
    `Title: ${pr.tag === undefined ? '' : `[${pr.tag}] `}${pr.title}`,
    `Commit message body:\n${pr.summary.join('\n\n') || '(none)'}`,
    `Files (+added -deleted):\n${pr.files.map(file => `${file.path} +${file.added} -${file.deleted}`).join('\n')}`,
    `Diff:\n${capDiff(diff)}`,
  ].join('\n\n')

const clip = (value: unknown, cells: number): string => {
  const text = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : ''

  return text.length <= cells ? text : `${text.slice(0, cells - 1)}…`
}

// The model's reply as an explanation, or undefined when it holds none: the
// first JSON object in the text, fields clipped to what the pane can draw.
export const parseExplain = (text: string): PrExplain | undefined => {
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')

  if (start < 0 || end <= start) return undefined

  let raw: unknown

  try {
    raw = JSON.parse(text.slice(start, end + 1))
  } catch {
    return undefined
  }

  if (typeof raw !== 'object' || raw === null) return undefined

  const { summary, nodes } = raw as { summary?: unknown; nodes?: unknown }
  const parsed: ExplainNode[] = (Array.isArray(nodes) ? nodes : [])
    .filter((node): node is Record<string, unknown> => typeof node === 'object' && node !== null)
    .map(node => ({
      name: clip(node.name, NAME_CELLS),
      note: clip(node.note, NOTE_CELLS),
      change: CHANGES.includes(node.change as NodeChange) ? (node.change as NodeChange) : 'same',
      link: clip(node.link, LINK_CELLS),
    }))
    .filter(node => node.name !== '')
    .slice(0, MAX_NODES)
  const summaryText = clip(summary, SUMMARY_CHARS)

  if (summaryText === '' && parsed.length === 0) return undefined

  // The last node hands over to nothing.
  const last = parsed[parsed.length - 1]

  if (last !== undefined) last.link = ''

  return { summary: summaryText, nodes: parsed }
}

export const MARKS: Record<NodeChange, string> = { added: '★', changed: '✎', removed: '✕', same: '' }

// Lines added in thousands read as `1.1k`.
export const count = (lines: number): string =>
  lines < 1000 ? String(lines) : `${(lines / 1000).toFixed(lines < 10_000 ? 1 : 0).replace(/\.0$/, '')}k`
