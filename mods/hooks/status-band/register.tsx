import { atom, update } from 'claude-code'
import type { Elements, EngineInterface, Register, RenderElement } from 'claude-code'

import type { StatusBand } from '../../types'
import { contextText, headline, levelOf, limitsText } from './format'

// Layout after the claude-hud status line (github.com/jarrodwatts/claude-hud).
// The elapsed time and the reset countdowns read in minutes.
const TICK_MS = 60_000
const GIT_TIMEOUT_MS = 2000
// The surfaces the engine raises the band above the prompt on.
const BAND_SURFACES: readonly string[] = ['terminal', 'desktop']

const statusBand = atom({ plugin: 'mods', key: 'statusBand' } as const, null)

// What one load of the module keeps between hooks.
type Live = {
  effort: StatusBand['effort']
  // True from a main-loop step until the next read: that effort is the model's now.
  isEffortFresh: boolean
  tick?: { cancel: () => void }
  asked: number
  drawn: number
}

// The band is a convenience: a figure the engine cannot give is left out or
// kept as last read, and nothing here may fail a hook.
const refresh = async ($: EngineInterface, live: Live): Promise<void> => {
  live.asked += 1
  const order = live.asked

  try {
    const [model, cwd, usage, turns, now, git] = await Promise.all([
      $.session.model().catch(() => ''),
      $.session.cwd().catch(() => ''),
      $.session.usage().catch(() => null),
      $.session.turns().catch(() => null),
      $.clock.now(),
      $.process
        .run(['git', 'branch', '--show-current'], { timeoutMs: GIT_TIMEOUT_MS })
        .catch(() => null),
    ])
    // Git answering with no name (no repository, a detached HEAD) is a reading.
    const branch = git === null ? null : git.exitCode === 0 ? git.stdout.trim() : ''

    await update($, statusBand, current => {
      // A read that started earlier and ended later must not undo a newer one.
      if (order < live.drawn) return current

      live.drawn = order
      const name = model === '' ? (current?.model ?? '') : model

      if (live.isEffortFresh) {
        live.isEffortFresh = false
      } else if (current !== null && current.model !== name) {
        // The effort was the last model's; the next step reports this one's.
        live.effort = undefined
      } else if (live.effort === undefined) {
        // A reload starts the module over; the session's value is still good.
        live.effort = current?.effort
      }

      return {
        model: name,
        effort: live.effort,
        cwd: cwd === '' ? (current?.cwd ?? '') : cwd,
        branch: branch === null ? current?.branch : branch === '' ? undefined : branch,
        startedAt: usage?.startedAt ?? current?.startedAt,
        now,
        // Before the first prompt nothing is in the window: that 0 is a reading.
        contextPercent:
          usage === null
            ? current?.contextPercent
            : (usage.context.percent ?? (turns === 0 ? 0 : undefined)),
        rateLimits: usage?.rateLimits ?? current?.rateLimits ?? [],
      }
    })
  } catch {
    // Keeps what was last drawn.
  }
}

// Reads the figures and keeps the minute tick, where a surface draws the band.
const watch = async ($: EngineInterface, live: Live): Promise<void> => {
  try {
    const surfaces = await $.session.surfaces()

    if (!surfaces.some(surface => BAND_SURFACES.includes(surface))) {
      live.tick?.cancel()
      live.tick = undefined

      return
    }

    live.tick ??= $.clock.every(TICK_MS, () => void refresh($, live))
    await refresh($, live)
  } catch {
    // Nothing to draw on.
  }
}

export const register: Register = (on, options) => {
  if (options.statusBandEnabled === false) return

  const live: Live = { effort: undefined, isEffortFresh: false, asked: 0, drawn: 0 }

  // Neither hook waits for the read: a slow git must not hold the session.
  on('session.start', async ($, e, next) => {
    const result = await next(e)

    void watch($, live)

    return result
  })

  // Raised after each main-thread turn too, which may have switched the branch;
  // a surface that attached after the start gets its tick here.
  on('session.measure', ($, e, next) => {
    void watch($, live)

    return next(e)
  })

  // The band follows the surfaces: one that attaches gets it at once, and the
  // tick stops when the last one that draws it leaves.
  on('session.attach', async ($, e, next) => {
    const result = await next(e)

    void watch($, live)

    return result
  })

  on('session.detach', async ($, e, next) => {
    const result = await next(e)

    void watch($, live)

    return result
  })

  // A `/clear` empties the window and starts the timer over; no measure follows it.
  on('session.end', async ($, e, next) => {
    const result = await next(e)

    if (e.reason === 'clear') void watch($, live)

    return result
  })

  // The request is passed on untouched: only its effort is read.
  on('turn.step', async function* ($, e, next) {
    if (e.agentId === undefined) live.isEffortFresh = true

    if (e.agentId === undefined && e.effort !== live.effort) {
      const effort = e.effort

      live.effort = effort
      await update($, statusBand, current =>
        current === null ? null : { ...current, effort },
      ).catch(() => undefined)
    }

    return yield* next(e)
  })
}

type BandElements = Pick<Elements['terminal'], 'Box' | 'Text'>

// This mod's rows of the band above the prompt. `hooks/band.tsx` draws them:
// the engine takes one band hook per plugin, and `$` stays in that hook's file.
export const statusRows = ({ Box, Text }: BandElements, status: StatusBand): RenderElement => {
  const context = contextText(status)
  const limits = limitsText(status)

  return (
    <Box flexDirection="column">
      <Text wrap="truncate-end">{headline(status)}</Text>
      {context === '' && limits === '' ? null : (
        <Box>
          {context === '' ? null : <Text color={levelOf(status.contextPercent)}>{context}</Text>}
          {limits === '' ? null : (
            <Text dimColor wrap="truncate-end">
              {context === '' ? limits : ` │ ${limits}`}
            </Text>
          )}
        </Box>
      )}
    </Box>
  )
}
