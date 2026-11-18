// Pure status text: no engine types, so it runs and tests without `$`.

import type { ContextPart, StatusBand } from '../../types'

const BAR_CELLS = 30
// A longer branch name is cut, so it does not push the figures after it off the row.
const BRANCH_CELLS = 24
const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

// What the rows draw beyond plain letters. Some terminals (Wave on Windows)
// advance a box-drawing, block or geometric glyph by a cell other than the one
// the engine counts, and a redraw then leaves cells behind: `ASCII` draws none.
export type Glyphs = {
  separator: string
  effort: Record<string, string>
  filled: string
  empty: string
  // The window left, and the compaction reserve, where the bar is split by category.
  free: string
  buffer: string
  ellipsis: string
}

export const UNICODE: Glyphs = {
  separator: ' │ ',
  effort: { low: '○', medium: '◔', high: '◑', xhigh: '◕', max: '●' },
  filled: '█',
  empty: '░',
  free: '─',
  buffer: '░',
  ellipsis: '…',
}

export const ASCII: Glyphs = {
  separator: ' | ',
  effort: {},
  filled: '#',
  empty: '-',
  free: '-',
  buffer: '.',
  ellipsis: '~',
}
// The windows the band names, in the order it draws them.
const WINDOWS: readonly (readonly [kind: string, label: string])[] = [
  ['five_hour', '5h'],
  ['seven_day', '7d'],
]

export type Level = 'success' | 'warning' | 'error'

// One run of a row drawn in its own color; `color` is a theme key.
export type Segment = { text: string; color?: string; isBold?: boolean; isDim?: boolean }

// `claude-opus-5-5` reads as `Opus 5.5`; a name of any other shape is kept.
export const modelLabel = (model: string): string => {
  const match = /^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(\[[^\]]+\])?$/.exec(model.trim())

  if (match === null) return model.trim()

  const [, family = '', major = '', minor, suffix] = match
  const version = minor === undefined ? major : `${major}.${minor}`

  return `${family.charAt(0).toUpperCase()}${family.slice(1)} ${version}${suffix ?? ''}`
}

export const clampPercent = (percent: number | undefined): number =>
  percent === undefined || Number.isNaN(percent) ? 0 : Math.min(100, Math.max(0, percent))

export const bar = (percent: number | undefined, glyphs: Glyphs = UNICODE): string => {
  const filled = Math.round((clampPercent(percent) / 100) * BAR_CELLS)

  return glyphs.filled.repeat(filled) + glyphs.empty.repeat(BAR_CELLS - filled)
}

export const levelOf = (percent: number | undefined): Level => {
  const used = clampPercent(percent)

  if (used >= 90) return 'error'

  return used >= 70 ? 'warning' : 'success'
}

// The two largest units, so a week reads `6d 7h` and an hour `2h 4m`.
export const duration = (ms: number): string => {
  if (ms < MINUTE_MS) return '<1m'

  const days = Math.floor(ms / DAY_MS)
  const hours = Math.floor((ms % DAY_MS) / HOUR_MS)
  const minutes = Math.floor((ms % HOUR_MS) / MINUTE_MS)

  if (days > 0) return `${days}d ${hours}h`

  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`
}

const modelSegment = (status: StatusBand, glyphs: Glyphs): string => {
  const name = modelLabel(status.model)

  if (status.effort === undefined) return `[${name}]`

  const glyph = glyphs.effort[String(status.effort)]

  return glyph === undefined ? `[${name} ${status.effort}]` : `[${name} ${glyph} ${status.effort}]`
}

const basename = (path: string): string => path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? ''

const plural = (count: number, noun: string): string => `${count} ${noun}${count === 1 ? '' : 's'}`

// `4200` reads as `4.2k`; under a thousand the count is kept.
export const tokens = (count: number): string =>
  count < 1000 ? String(Math.round(count)) : `${(count / 1000).toFixed(1)}k`

// What is left of the prompt cache, counted from the last response.
export const cacheText = (status: StatusBand): string => {
  if (status.cacheExpiresAt === undefined) return ''

  const left = status.cacheExpiresAt - status.now

  if (left <= 0) return 'cache expired'

  // Whole minutes alone, so a full hour reads `60m`, not `1h 0m`.
  return left < MINUTE_MS ? 'cache <1m' : `cache ${Math.floor(left / MINUTE_MS)}m`
}

const joined = (groups: Segment[][], separator: string): Segment[] =>
  groups
    .filter(group => group.length > 0)
    .flatMap((group, index) =>
      index === 0 ? group : [{ text: separator, isDim: true }, ...group],
    )

// A figure the engine has no reading for is left out, with its separator.
export const headlineSegments = (status: StatusBand, glyphs: Glyphs = UNICODE): Segment[] => {
  const dir = basename(status.cwd)
  const place: Segment[] = dir === '' ? [] : [{ text: dir, color: 'suggestion', isBold: true }]

  if (status.branch !== undefined) {
    const branch =
      status.branch.length > BRANCH_CELLS
        ? `${status.branch.slice(0, BRANCH_CELLS - 1)}${glyphs.ellipsis}`
        : status.branch

    place.push({ text: `${dir === '' ? '' : ' '}git:(${branch})`, color: 'autoAccept' })
  }

  return joined(
    [
      status.model === '' ? [] : [{ text: modelSegment(status, glyphs), color: 'claude', isBold: true }],
      place,
      status.startedAt === undefined
        ? []
        : [{ text: `up ${duration(status.now - status.startedAt)}` }],
    ],
    glyphs.separator,
  )
}

// The queue's depth; a queue read and found empty is a figure.
export const queueSegments = (status: StatusBand): Segment[] => {
  const queue = status.queue

  if (queue === undefined || queue === null) return []

  const groups: Segment = {
    text: `queue ${queue.groups}`,
    color: queue.groups === 0 ? undefined : 'suggestion',
    isDim: queue.groups === 0,
  }

  return queue.parked === 0
    ? [groups]
    : [groups, { text: ` (${queue.parked} parked)`, color: 'warning' }]
}

// The cache countdown, what the session is set up with and the queue, on a row of their own.
export const setupSegments = (status: StatusBand, glyphs: Glyphs = UNICODE): Segment[] => {
  const cache = cacheText(status)

  return joined(
    [
      cache === ''
        ? []
        : [{ text: cache, color: cache === 'cache expired' ? 'warning' : 'planMode' }],
      status.hooks === undefined
        ? []
        : [{ text: plural(status.hooks, 'hook'), color: 'permission' }],
      status.skills === undefined
        ? []
        : [
            { text: plural(status.skills.count, 'skill'), color: 'remember' },
            { text: ` (${tokens(status.skills.tokens)})`, isDim: true },
          ],
      // No server is no figure: the row keeps its room.
      status.mcp === undefined || status.mcp === 0
        ? []
        : [{ text: `${status.mcp} mcp`, color: 'ide' }],
      queueSegments(status),
    ],
    glyphs.separator,
  )
}

// Where the band has no row to spare, the setup rides on the headline.
export const mergedSegments = (status: StatusBand, glyphs: Glyphs = UNICODE): Segment[] =>
  joined([headlineSegments(status, glyphs), setupSegments(status, glyphs)], glyphs.separator)

const textOf = (segments: Segment[]): string => segments.map(segment => segment.text).join('')

export const headline = (status: StatusBand): string => textOf(headlineSegments(status))

export const setupText = (status: StatusBand): string => textOf(setupSegments(status))

// Splits `cells` by weight, the largest remainders taking the cells rounding left.
const apportion = (weights: number[], cells: number): number[] => {
  const total = weights.reduce((sum, weight) => sum + weight, 0)

  if (total <= 0 || cells <= 0) return weights.map(() => 0)

  const shares = weights.map(weight => (weight / total) * cells)
  const counts = shares.map(Math.floor)
  let left = cells - counts.reduce((sum, count) => sum + count, 0)

  for (const index of shares
    .map((share, at) => at)
    .sort((a, b) => shares[b]! - counts[b]! - (shares[a]! - counts[a]!))) {
    if (left === 0) break
    counts[index]! += 1
    left -= 1
  }

  return counts
}

// The used cells, split among the rows that fill them; a row with any tokens
// keeps a cell of its own while there are cells enough to go round.
const usedCells = (used: ContextPart[], cells: number): number[] => {
  const holding = used.filter(part => part.tokens > 0).length

  if (holding === 0 || cells < holding) return apportion(used.map(part => part.tokens), cells)

  const rest = apportion(used.map(part => part.tokens), cells - holding)

  return rest.map((count, index) => count + (used[index]!.tokens > 0 ? 1 : 0))
}

// The bar, after /context and the context-bar mod of
// github.com/hamzafer/claude-code-mods: each row that fills the window in its own color,
// then the window left and the compaction reserve. The filled length follows
// the percentage, so bar and figure agree; without a breakdown, one fill.
export const contextBarSegments = (status: StatusBand, glyphs: Glyphs = UNICODE): Segment[] => {
  const parts = status.contextParts ?? []
  const used = parts.filter(part => part.kind === 'used')
  const filled = Math.round((clampPercent(status.contextPercent) / 100) * BAR_CELLS)

  if (used.every(part => part.tokens <= 0)) return [{ text: bar(status.contextPercent, glyphs) }]

  const window = parts.reduce((sum, part) => sum + Math.max(0, part.tokens), 0)
  const reserve = parts
    .filter(part => part.kind === 'buffer')
    .reduce((sum, part) => sum + Math.max(0, part.tokens), 0)
  const buffer = Math.min(BAR_CELLS - filled, Math.round((reserve / window) * BAR_CELLS))
  const free = BAR_CELLS - filled - buffer
  const counts = usedCells(used, filled)
  const runs: Segment[] = used.map((part, index) => ({
    text: glyphs.filled.repeat(counts[index]!),
    color: part.color,
  }))

  return [
    ...runs,
    { text: glyphs.free.repeat(free), isDim: true },
    { text: glyphs.buffer.repeat(buffer), isDim: true },
  ].filter(segment => segment.text !== '')
}

// A fill the engine has no reading for is left out, never drawn as 0%.
export const contextSegments = (status: StatusBand, glyphs: Glyphs = UNICODE): Segment[] =>
  status.contextPercent === undefined
    ? []
    : [
        { text: 'Context ' },
        ...contextBarSegments(status, glyphs),
        { text: ` ${Math.round(clampPercent(status.contextPercent))}%` },
      ]

export const contextText = (status: StatusBand, glyphs: Glyphs = UNICODE): string =>
  textOf(contextSegments(status, glyphs))

// A window the engine has no reading for is left out, never drawn as 0%.
export const limitsSegments = (status: StatusBand, glyphs: Glyphs = UNICODE): Segment[] =>
  joined(
    WINDOWS.map(([kind, label]): Segment[] => {
      const limit = status.rateLimits.find(candidate => candidate.kind === kind)

      if (limit === undefined) return []

      const resetsAt = limit.resetsAt === undefined ? Number.NaN : Date.parse(limit.resetsAt)
      const left = resetsAt - status.now
      const used: Segment[] = [
        { text: `${label}: `, isDim: true },
        { text: `${Math.round(limit.percentUsed)}%`, color: levelOf(limit.percentUsed) },
      ]

      return Number.isNaN(left) || left <= 0
        ? used
        : [...used, { text: ` (${duration(left)})`, isDim: true }]
    }),
    glyphs.separator,
  )

// A harness-curate run the dev plugin judges due; nothing otherwise.
export const curateText = (status: StatusBand): string =>
  status.curateDue === true ? 'harness-curate due' : ''

export const limitsText = (status: StatusBand): string => textOf(limitsSegments(status))
