import { atom, update } from 'claude-code'
import type { Elements, EngineInterface, Register, RenderElement } from 'claude-code'

import type { StatusBand } from '../../types'
import { contextText, headline, levelOf, limitsText } from './format'

// Layout after the claude-hud status line (github.com/jarrodwatts/claude-hud).
// The elapsed time and the reset countdowns read in minutes.
const TICK_MS = 60_000
const GIT_TIMEOUT_MS = 2000

const statusBand = atom({ plugin: 'mods', key: 'statusBand' } as const, null)

// The band is a convenience: a figure the engine cannot give is left out, and
// nothing here may fail a hook.
const refresh = async ($: EngineInterface, effort: StatusBand['effort']): Promise<void> => {
  try {
    const [model, cwd, usage, now, git] = await Promise.all([
      $.session.model().catch(() => ''),
      $.session.cwd().catch(() => ''),
      $.session.usage().catch(() => null),
      $.clock.now(),
      $.process
        .run(['git', 'branch', '--show-current'], { timeoutMs: GIT_TIMEOUT_MS })
        .catch(() => null),
    ])
    const branch = git?.exitCode === 0 ? git.stdout.trim() : ''

    await update($, statusBand, () => ({
      model,
      effort,
      cwd,
      branch: branch === '' ? undefined : branch,
      startedAt: usage?.startedAt ?? now,
      now,
      contextPercent: usage?.context.percent,
      rateLimits: usage?.rateLimits ?? [],
    }))
  } catch {
    // Keeps what was last drawn.
  }
}

export const register: Register = (on, options) => {
  if (options.statusBandEnabled === false) return

  let effort: StatusBand['effort']
  let tick: { cancel: () => void } | undefined

  on('session.start', async ($, e, next) => {
    const result = await next(e)

    if (e.isInteractive) {
      await refresh($, effort)
      tick?.cancel()
      tick = $.clock.every(TICK_MS, () => void refresh($, effort))
    }

    return result
  })

  on('session.end', ($, e, next) => {
    // A `/clear` ends the session without starting another, so the tick stays.
    if (e.reason !== 'clear') {
      tick?.cancel()
      tick = undefined
    }

    return next(e)
  })

  // The request is passed on untouched: only its effort is read.
  on('turn.step', async function* ($, e, next) {
    if (e.agentId === undefined && e.effort !== effort) {
      effort = e.effort
      await update($, statusBand, current =>
        current === null ? null : { ...current, effort },
      ).catch(() => undefined)
    }

    return yield* next(e)
  })

  // Raised after each main-thread turn too, which may have switched the branch.
  on('session.measure', async ($, e, next) => {
    await refresh($, effort)

    return next(e)
  })
}

type BandElements = Pick<Elements['terminal'], 'Box' | 'Text'>

// This mod's rows of the band above the prompt. `hooks/band.tsx` draws them:
// the engine takes one band hook per plugin, and `$` stays in that hook's file.
export const statusRows = ({ Box, Text }: BandElements, status: StatusBand): RenderElement => {
  const limits = limitsText(status)

  return (
    <Box flexDirection="column">
      <Text wrap="truncate-end">
        {headline(status)}
      </Text>
      <Box>
        <Text color={levelOf(status.contextPercent)}>
          {contextText(status)}
        </Text>
        {limits === '' ? null : (
          <Text dimColor wrap="truncate-end">
            {` │ ${limits}`}
          </Text>
        )}
      </Box>
    </Box>
  )
}
