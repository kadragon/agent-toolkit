// Pure status text: no engine types, so it runs and tests without `$`.

import type { StatusBand } from '../../types'

const BAR_CELLS = 10
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

export const headline = (status: StatusBand): string => {
  const dir = basename(status.cwd)
  const place = status.branch === undefined ? dir : `${dir} git:(${status.branch})`
  const elapsed = `⏱️  ${duration(status.now - status.startedAt)}`

  return [status.model === '' ? '' : modelSegment(status), place, elapsed]
    .filter(segment => segment !== '')
    .join(SEPARATOR)
}

export const contextText = (status: StatusBand): string =>
  `Context ${bar(status.contextPercent)} ${Math.round(clampPercent(status.contextPercent))}%`

// A window the engine has no reading for is left out, never drawn as 0%.
export const limitsText = (status: StatusBand): string =>
  WINDOWS.flatMap(([kind, label]) => {
    const limit = status.rateLimits.find(candidate => candidate.kind === kind)

    if (limit === undefined) return []

    const resetsAt = limit.resetsAt === undefined ? Number.NaN : Date.parse(limit.resetsAt)
    const left = resetsAt - status.now
    const reset = Number.isNaN(left) || left <= 0 ? '' : ` (${duration(left)})`

    return [`${label}: ${Math.round(limit.percentUsed)}%${reset}`]
  }).join(' | ')
