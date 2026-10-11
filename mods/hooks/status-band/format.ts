// Pure status text: no engine types, so it runs and tests without `$`.

import type { StatusBand } from '../../types'

const BAR_CELLS = 10
// A longer branch name is cut, so it does not push the figures after it off the row.
const BRANCH_CELLS = 24
const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS
const SEPARATOR = ' │ '
const EFFORT_GLYPHS: Record<string, string> = {
  low: '○',
  medium: '◔',
  high: '◑',
  xhigh: '◕',
  max: '●',
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

export const bar = (percent: number | undefined): string => {
  const filled = Math.round((clampPercent(percent) / 100) * BAR_CELLS)

  return '█'.repeat(filled) + '░'.repeat(BAR_CELLS - filled)
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

const modelSegment = (status: StatusBand): string => {
  const name = modelLabel(status.model)

  if (status.effort === undefined) return `[${name}]`

  const glyph = EFFORT_GLYPHS[String(status.effort)]

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

  return left <= 0 ? 'cache expired' : `cache ${duration(left)}`
}

const joined = (groups: Segment[][], separator: string): Segment[] =>
  groups
    .filter(group => group.length > 0)
    .flatMap((group, index) =>
      index === 0 ? group : [{ text: separator, isDim: true }, ...group],
    )

// A figure the engine has no reading for is left out, with its separator.
export const headlineSegments = (status: StatusBand): Segment[] => {
  const dir = basename(status.cwd)
  const cache = cacheText(status)
  const place: Segment[] = dir === '' ? [] : [{ text: dir, color: 'suggestion', isBold: true }]

  if (status.branch !== undefined) {
    const branch =
      status.branch.length > BRANCH_CELLS
        ? `${status.branch.slice(0, BRANCH_CELLS - 1)}…`
        : status.branch

    place.push({ text: `${dir === '' ? '' : ' '}git:(${branch})`, color: 'autoAccept' })
  }

  return joined(
    [
      status.model === '' ? [] : [{ text: modelSegment(status), color: 'claude', isBold: true }],
      place,
      status.startedAt === undefined
        ? []
        : [{ text: `⏱️  ${duration(status.now - status.startedAt)}` }],
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
    ],
    SEPARATOR,
  )
}

const textOf = (segments: Segment[]): string => segments.map(segment => segment.text).join('')

export const headline = (status: StatusBand): string => textOf(headlineSegments(status))

// A fill the engine has no reading for is left out, never drawn as 0%.
export const contextText = (status: StatusBand): string =>
  status.contextPercent === undefined
    ? ''
    : `Context ${bar(status.contextPercent)} ${Math.round(clampPercent(status.contextPercent))}%`

// A window the engine has no reading for is left out, never drawn as 0%.
export const limitsSegments = (status: StatusBand): Segment[] =>
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
    ' | ',
  )

export const limitsText = (status: StatusBand): string => textOf(limitsSegments(status))
