import { describe, expect, test } from 'claude-code/testing'

import type { StatusBand } from '../../types'
import {
  bar,
  cacheText,
  contextText,
  duration,
  headline,
  headlineSegments,
  levelOf,
  limitsSegments,
  limitsText,
  modelLabel,
  tokens,
} from './format'

const NOW = Date.parse('2026-10-11T12:00:00Z')
const MINUTE = 60_000
const HOUR = 60 * MINUTE
const at = (ms: number): string => new Date(NOW + ms).toISOString()

const STATUS: StatusBand = {
  model: 'claude-opus-5-5',
  effort: 'medium',
  cwd: '/work/agent-toolkit',
  branch: 'main',
  startedAt: NOW - 30_000,
  now: NOW,
  contextPercent: 0,
  rateLimits: [
    { kind: 'seven_day', percentUsed: 9, resetsAt: at(6 * 24 * HOUR + 7 * HOUR) },
    { kind: 'five_hour', percentUsed: 88, resetsAt: at(2 * HOUR + 4 * MINUTE) },
  ],
}

describe('headline', () => {
  test('reads model, effort, directory, branch and elapsed time', () => {
    expect(headline(STATUS)).toBe('[Opus 5.5 ◔ medium] │ agent-toolkit git:(main) │ ⏱️  <1m')
  })

  test('leaves the effort out until a turn reported one', () => {
    expect(headline({ ...STATUS, effort: undefined })).toBe(
      '[Opus 5.5] │ agent-toolkit git:(main) │ ⏱️  <1m',
    )
  })

  test('leaves the git segment out with no branch', () => {
    expect(headline({ ...STATUS, branch: undefined })).toBe(
      '[Opus 5.5 ◔ medium] │ agent-toolkit │ ⏱️  <1m',
    )
  })

  test('draws the branch alone when the directory has no name', () => {
    expect(headline({ ...STATUS, cwd: '/' })).toBe('[Opus 5.5 ◔ medium] │ git:(main) │ ⏱️  <1m')
    expect(headline({ ...STATUS, cwd: '', branch: undefined })).toBe('[Opus 5.5 ◔ medium] │ ⏱️  <1m')
  })

  test('leaves the model out when the engine named none', () => {
    expect(headline({ ...STATUS, model: '' })).toBe('agent-toolkit git:(main) │ ⏱️  <1m')
  })

  test('leaves the elapsed time out when the session start is unknown', () => {
    expect(headline({ ...STATUS, startedAt: undefined })).toBe(
      '[Opus 5.5 ◔ medium] │ agent-toolkit git:(main)',
    )
  })

  test('shows an effort it has no glyph for as given', () => {
    expect(headline({ ...STATUS, effort: 4096 })).toContain('[Opus 5.5 4096]')
  })
})

describe('modelLabel', () => {
  test('turns a model id into its display name', () => {
    expect(modelLabel('claude-opus-5-5')).toBe('Opus 5.5')
    expect(modelLabel('claude-sonnet-5-5-20260101')).toBe('Sonnet 5.5')
    expect(modelLabel('claude-fable-5-1[1m]')).toBe('Fable 5.1[1m]')
    expect(modelLabel('claude-haiku-5')).toBe('Haiku 5')
  })

  test('keeps a name of any other shape', () => {
    expect(modelLabel('Opus 5.5')).toBe('Opus 5.5')
    expect(modelLabel('opus')).toBe('opus')
    expect(modelLabel('claude-3-5-sonnet-20241022')).toBe('claude-3-5-sonnet-20241022')
  })
})

describe('context', () => {
  test('draws a ten-cell bar and a whole percentage', () => {
    expect(contextText(STATUS)).toBe('Context ░░░░░░░░░░ 0%')
    expect(contextText({ ...STATUS, contextPercent: 42 })).toBe('Context ████░░░░░░ 42%')
    expect(contextText({ ...STATUS, contextPercent: 100 })).toBe('Context ██████████ 100%')
  })

  test('is left out with no reading', () => {
    expect(contextText({ ...STATUS, contextPercent: undefined })).toBe('')
  })

  test('keeps the bar inside its ten cells', () => {
    expect(bar(250)).toBe('██████████')
    expect(bar(-5)).toBe('░░░░░░░░░░')
  })

  test('colors by how full the window is', () => {
    expect(levelOf(69)).toBe('success')
    expect(levelOf(70)).toBe('warning')
    expect(levelOf(90)).toBe('error')
  })
})

describe('limitsText', () => {
  test('names the five-hour window first, each with its reset', () => {
    expect(limitsText(STATUS)).toBe('5h: 88% (2h 4m) | 7d: 9% (6d 7h)')
  })

  test('is empty off a subscription', () => {
    expect(limitsText({ ...STATUS, rateLimits: [] })).toBe('')
  })

  test('skips a window it does not name and one with no reading', () => {
    expect(
      limitsText({
        ...STATUS,
        rateLimits: [{ kind: 'spend_limit', percentUsed: 50 }, STATUS.rateLimits[1]!],
      }),
    ).toBe('5h: 88% (2h 4m)')
  })

  test('drops a reset that is missing, unreadable or already past', () => {
    const limit = (resetsAt?: string) => ({ kind: 'five_hour', percentUsed: 12.4, resetsAt })

    expect(limitsText({ ...STATUS, rateLimits: [limit()] })).toBe('5h: 12%')
    expect(limitsText({ ...STATUS, rateLimits: [limit('soon')] })).toBe('5h: 12%')
    expect(limitsText({ ...STATUS, rateLimits: [limit(at(-MINUTE))] })).toBe('5h: 12%')
  })
})

describe('duration', () => {
  test('shows the two largest units', () => {
    expect(duration(0)).toBe('<1m')
    expect(duration(59_999)).toBe('<1m')
    expect(duration(5 * MINUTE)).toBe('5m')
    expect(duration(HOUR)).toBe('1h 0m')
    expect(duration(2 * HOUR + 4 * MINUTE)).toBe('2h 4m')
    expect(duration(6 * 24 * HOUR + 7 * HOUR + 30 * MINUTE)).toBe('6d 7h')
  })
})

describe('cache', () => {
  test('reads the time left, and expired once it is past', () => {
    expect(cacheText({ ...STATUS, cacheExpiresAt: NOW + 58 * MINUTE })).toBe('cache 58m')
    expect(cacheText({ ...STATUS, cacheExpiresAt: NOW + 30_000 })).toBe('cache <1m')
    expect(cacheText({ ...STATUS, cacheExpiresAt: NOW })).toBe('cache expired')
  })

  test('is left out before the first response', () => {
    expect(cacheText(STATUS)).toBe('')
  })
})

describe('counts', () => {
  test('follow the timers: the cache, the hooks, then the skills and their size', () => {
    expect(
      headline({
        ...STATUS,
        cacheExpiresAt: NOW + 58 * MINUTE,
        hooks: 21,
        skills: { count: 49, tokens: 4234 },
      }),
    ).toBe(
      '[Opus 5.5 ◔ medium] │ agent-toolkit git:(main) │ ⏱️  <1m │ cache 58m │ 21 hooks │ 49 skills (4.2k)',
    )
  })

  test('name one of a thing in the singular', () => {
    expect(headline({ ...STATUS, hooks: 1, skills: { count: 1, tokens: 80 } })).toContain(
      '1 hook │ 1 skill (80)',
    )
  })

  test('write a thousand tokens and over in thousands', () => {
    expect(tokens(999)).toBe('999')
    expect(tokens(1000)).toBe('1.0k')
    expect(tokens(12_345)).toBe('12.3k')
  })
})

describe('segments', () => {
  test('dim the separators and leave the figures at full strength', () => {
    const segments = headlineSegments(STATUS)

    expect(segments.filter(segment => segment.isDim).map(segment => segment.text)).toEqual([
      ' │ ',
      ' │ ',
    ])
    expect(segments[0]).toEqual({ text: '[Opus 5.5 ◔ medium]', color: 'claude', isBold: true })
  })

  test('color each window by its own fill', () => {
    const colors = limitsSegments(STATUS).flatMap(({ color }) => (color === undefined ? [] : [color]))

    expect(colors).toEqual(['warning', 'success'])
  })
})
