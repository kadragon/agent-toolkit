import type { FileChange, FileKind, Pr, PrGroup } from '../../types'

// Field and record marks for the git log the recap reads: a record opens with
// RS, its fields part on US, and GS ends the message so the numstat after it
// is told from a body line.
const RS = '\x1e'
const US = '\x1f'
const GS = '\x1d'

export const LOG_FORMAT = `${RS}%H${US}%s${US}%an${US}%ct${US}%b${GS}`
// Squash merges carry `(#N)` at the end of the subject; merge commits name it.
const SQUASH = /\s*\(#(\d+)\)\s*$/
const MERGE = /^Merge pull request #(\d+)\b/
const TAG = /^\[([A-Z]+)\]\s*/
const TRAILER = /^(Co-Authored-By|Signed-off-by|Reviewed-by|Change-Id):/i
const RULE = /^-{3,}$/
const MAX_PARAGRAPHS = 6

// The git log that reads the PRs: HEAD's first-parent history, merges diffed
// against the branch they landed on, a window wide enough to skip direct commits.
export const logArgv = (window: number): string[] => [
  'git',
  // Paths as written, not C-quoted with octal escapes for non-ASCII bytes.
  '-c',
  'core.quotePath=false',
  '--no-pager',
  'log',
  '--first-parent',
  '--diff-merges=first-parent',
  `-n${window}`,
  `--format=${LOG_FORMAT}`,
  '--numstat',
  '--no-color',
  '--no-renames',
  'HEAD',
]

// `a/{b => c}/d` and `a => b` name the path a rename lands on.
export const landedPath = (path: string): string =>
  path.replace(/\{[^{}]*? => ([^{}]*)\}/g, '$1').replace(/^.* => /, '').replace(/\/{2,}/g, '/')

export const kindOf = (path: string): FileKind => {
  const name = path.split('/').pop() ?? path

  if (/(^|\/)(tests?|__tests__)\//.test(path) || /^test_|[._-](test|spec)\.[^.]+$/.test(name)) return 'test'
  if (/\.(md|mdx|txt|rst)$/i.test(name)) return 'docs'
  if (/\.(json|ya?ml|toml|ini|cfg|lock)$/i.test(name) || name.startsWith('.')) return 'config'

  return 'code'
}

const numstat = (line: string): FileChange | undefined => {
  const match = /^(\d+|-)\t(\d+|-)\t(.+)$/.exec(line)

  if (match === null) return undefined

  const path = landedPath(match[3] ?? '')
  const isBinary = match[1] === '-'

  return {
    path,
    added: isBinary ? 0 : Number(match[1]),
    deleted: isBinary ? 0 : Number(match[2]),
    isBinary,
    kind: kindOf(path),
  }
}

// The body's paragraphs worth reading: trailers, rules and a bullet that only
// repeats the title go.
export const summaryOf = (body: string, title: string): string[] => {
  const paragraphs: string[] = []
  let lines: string[] = []
  const flush = () => {
    const text = lines.join('\n').trim()

    lines = []
    if (text !== '' && text.replace(/^\*\s*/, '').replace(TAG, '') !== title) paragraphs.push(text)
  }

  for (const raw of body.replace(/\r/g, '').split('\n')) {
    const line = raw.trimEnd()

    if (TRAILER.test(line.trim()) || RULE.test(line.trim())) continue
    if (line.trim() === '') flush()
    else lines.push(line)
  }
  flush()

  return paragraphs.slice(0, MAX_PARAGRAPHS)
}

// The PRs in a git log, newest first, at most `count`; commits that name no PR
// are passed over. Output cut short leaves its last record partial: it is dropped.
export const parseLog = (stdout: string, count: number, isTruncated = false): Pr[] => {
  const prs: Pr[] = []
  const records = stdout.split(RS).slice(1)

  for (const record of isTruncated ? records.slice(0, -1) : records) {
    const end = record.indexOf(GS)

    if (end < 0) continue

    const [sha, subject = '', author = '', time = '0', ...rest] = record.slice(0, end).split(US)
    const number = SQUASH.exec(subject)?.[1] ?? MERGE.exec(subject)?.[1]

    if (number === undefined) continue

    const body = rest.join(US)
    // A merge commit's subject names the branch; its body's first line is the PR title.
    const isMerge = MERGE.test(subject)
    const heading = isMerge ? (body.trim().split('\n')[0] || subject) : subject.replace(SQUASH, '')
    const tag = TAG.exec(heading)?.[1]
    const title = heading.replace(TAG, '').trim()
    const files = record
      .slice(end + 1)
      .split('\n')
      .map(line => numstat(line.replace(/\r$/, '')))
      .filter((file): file is FileChange => file !== undefined)

    prs.push({
      number: Number(number),
      sha: (sha ?? '').trim(),
      ...(tag === undefined ? {} : { tag }),
      title,
      author,
      mergedAt: Number(time) * 1000,
      summary: summaryOf(isMerge ? body.trim().split('\n').slice(1).join('\n') : body, title),
      files,
    })
    if (prs.length >= count) break
  }

  return prs
}

const dirOf = (path: string): string => {
  const cut = path.lastIndexOf('/')

  return cut < 0 ? '.' : path.slice(0, cut)
}

// Files by the directory they sit in, the most changed first; within one, by path.
export const groupsOf = (files: readonly FileChange[]): PrGroup[] => {
  const groups = new Map<string, FileChange[]>()

  for (const file of files) {
    const dir = dirOf(file.path)

    groups.set(dir, [...(groups.get(dir) ?? []), file])
  }

  return [...groups.entries()]
    .map(([dir, list]) => ({
      dir,
      files: [...list].sort((a, b) => a.path.localeCompare(b.path)),
      added: list.reduce((sum, file) => sum + file.added, 0),
      deleted: list.reduce((sum, file) => sum + file.deleted, 0),
    }))
    .sort((a, b) => b.added + b.deleted - (a.added + a.deleted) || a.dir.localeCompare(b.dir))
}

export const totalsOf = (files: readonly FileChange[]) => ({
  added: files.reduce((sum, file) => sum + file.added, 0),
  deleted: files.reduce((sum, file) => sum + file.deleted, 0),
})

const KINDS: readonly FileKind[] = ['code', 'test', 'docs', 'config']

// How many files of each kind, the kinds with none left out.
export const kindsOf = (files: readonly FileChange[]): { kind: FileKind; files: number }[] =>
  KINDS.map(kind => ({ kind, files: files.filter(file => file.kind === kind).length })).filter(
    entry => entry.files > 0,
  )

// A diffstat bar `width` cells wide at most, scaled to `scale` lines: the share
// added in `+`, deleted in `-`, as `git diff --stat` draws it.
export const statBar = (
  added: number,
  deleted: number,
  scale: number,
  width: number,
): { plus: string; minus: string } => {
  const total = added + deleted

  if (total === 0 || width <= 0) return { plus: '', minus: '' }

  const cells = Math.max(1, Math.round((Math.min(total, scale) / Math.max(scale, 1)) * width))
  // Each side that changed keeps a cell, so a bar of one draws both.
  const plus =
    added === 0
      ? 0
      : deleted === 0
        ? cells
        : Math.min(Math.max(1, cells - 1), Math.max(1, Math.round((added / total) * cells)))
  const minus = deleted === 0 ? 0 : Math.max(1, cells - plus)

  return { plus: '+'.repeat(plus), minus: '-'.repeat(minus) }
}

// A path cut from the left to `width` cells, its tail kept: the name matters most.
export const fit = (text: string, width: number): string =>
  text.length <= width ? text : width <= 1 ? text.slice(-width) : `…${text.slice(text.length - width + 1)}`

export const ago = (then: number, now: number): string => {
  const minutes = Math.max(0, Math.floor((now - then) / 60_000))

  if (minutes < 60) return `${minutes}m ago`
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)}h ago`

  return `${Math.floor(minutes / (24 * 60))}d ago`
}
