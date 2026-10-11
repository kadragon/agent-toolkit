import { atom, update } from 'claude-code'
import type { Elements, EngineInterface, Register, RenderElement } from 'claude-code'

import type { StatusBand } from '../../types'
import { enabledPlugins, hookCommands, hooksFileCommands, installPaths, manifestHooks } from './count'
import { contextText, headlineSegments, levelOf, limitsSegments } from './format'
import type { Segment } from './format'

// Layout after the claude-hud status line (github.com/jarrodwatts/claude-hud).
// The elapsed time and the reset countdowns read in minutes.
const TICK_MS = 60_000
const GIT_TIMEOUT_MS = 2000
const MINUTE_MS = 60_000
const DEFAULT_CACHE_TTL_MINUTES = 60
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
  // Null once a `/clear` emptied the window: nothing of it is cached.
  cacheExpiresAt?: number | null
  // The counts of what the session is set up with; they hold for the session.
  setup: Setup
}

type Setup = Pick<StatusBand, 'hooks' | 'skills'>

// The handlers a plugin's default hooks file, its manifest and the files the
// manifest names add; a file that is not there adds none.
const pluginHooks = async ($: EngineInterface, root: string): Promise<number> => {
  const { files, inline } = await $.fs
    .read(`${root}/.claude-plugin/plugin.json`)
    .then(manifestHooks)
    .catch(() => manifestHooks('{}'))
  const counts = await Promise.all(
    files.map(file =>
      $.fs
        .read(`${root}/${file}`)
        .then(hooksFileCommands)
        .catch(() => 0),
    ),
  )

  return counts.reduce((total, count) => total + count, inline)
}

// The command hooks in force: the settings' own and every enabled plugin's.
// The engine lists none, so they are counted off the files that declare them.
const countHooks = async ($: EngineInterface): Promise<number> => {
  const settings = await $.settings.read()
  const own = hookCommands(settings.hooks)
  const enabled = enabledPlugins(settings)

  if (enabled.length === 0) return own

  const configDir = await $.env.get('CLAUDE_CONFIG_DIR')
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE'))

  if (configDir === undefined && home === undefined) throw new Error('no home directory')

  const paths = installPaths(
    await $.fs.read(`${configDir ?? `${home}/.claude`}/plugins/installed_plugins.json`),
  )
  const counts = await Promise.all(
    enabled.map(id => (paths[id] === undefined ? 0 : pluginHooks($, paths[id]))),
  )

  return counts.reduce((total, count) => total + count, own)
}

// The skill listing as /context counts it, estimated locally: no request is sent.
const readSkills = async ($: EngineInterface): Promise<StatusBand['skills']> => {
  const { context } = await $.session.usage({ breakdown: 'summary' })

  if (context.breakdown === undefined) return undefined

  const skills = context.breakdown.skills

  return { count: skills?.totalSkills ?? 0, tokens: skills?.tokens ?? 0 }
}

// Reads a count once and keeps it; one the engine could not give is asked again.
const readSetup = async ($: EngineInterface, live: Live): Promise<Setup> => {
  const [hooks, skills] = await Promise.all([
    live.setup.hooks ?? countHooks($).catch(() => undefined),
    live.setup.skills ?? readSkills($).catch(() => undefined),
  ])

  live.setup = { hooks, skills }

  return live.setup
}

// The band is a convenience: a figure the engine cannot give is left out or
// kept as last read, and nothing here may fail a hook.
const refresh = async ($: EngineInterface, live: Live): Promise<void> => {
  live.asked += 1
  const order = live.asked

  try {
    const [model, cwd, usage, turns, now, git, setup] = await Promise.all([
      $.session.model().catch(() => ''),
      $.session.cwd().catch(() => ''),
      $.session.usage().catch(() => null),
      $.session.turns().catch(() => null),
      $.clock.now(),
      $.process
        .run(['git', 'branch', '--show-current'], { timeoutMs: GIT_TIMEOUT_MS })
        .catch(() => null),
      readSetup($, live),
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
        cacheExpiresAt:
          live.cacheExpiresAt === null
            ? undefined
            : (live.cacheExpiresAt ?? current?.cacheExpiresAt),
        hooks: setup.hooks ?? current?.hooks,
        skills: setup.skills ?? current?.skills,
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

  const ttl = options.statusBandCacheTtlMinutes
  const cacheTtlMs =
    (typeof ttl === 'number' && ttl > 0 ? ttl : DEFAULT_CACHE_TTL_MINUTES) * MINUTE_MS
  const live: Live = { effort: undefined, isEffortFresh: false, asked: 0, drawn: 0, setup: {} }

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

    if (e.reason === 'clear') {
      live.cacheExpiresAt = null
      void watch($, live)
    }

    return result
  })

  // The request is passed on untouched: only its effort is read, and a
  // response of the main loop renews the prompt cache from that moment.
  on('turn.step', async function* ($, e, next) {
    if (e.agentId === undefined) live.isEffortFresh = true

    if (e.agentId === undefined && e.effort !== live.effort) {
      const effort = e.effort

      live.effort = effort
      await update($, statusBand, current =>
        current === null ? null : { ...current, effort },
      ).catch(() => undefined)
    }

    const result = yield* next(e)

    if (e.agentId === undefined && result.usage !== null) {
      try {
        const cacheExpiresAt = (await $.clock.now()) + cacheTtlMs

        live.cacheExpiresAt = cacheExpiresAt
        await update($, statusBand, current =>
          current === null ? null : { ...current, cacheExpiresAt },
        )
      } catch {
        // Keeps the last countdown.
      }
    }

    return result
  })
}

type BandElements = Pick<Elements['terminal'], 'Box' | 'Text'>

const runs = ({ Text }: BandElements, segments: Segment[]): RenderElement[] =>
  segments.map((segment, index) => (
    <Text
      key={`run-${index}`}
      color={segment.color}
      bold={segment.isBold}
      dimColor={segment.isDim}
    >
      {segment.text}
    </Text>
  ))

// This mod's rows of the band above the prompt. `hooks/band.tsx` draws them:
// the engine takes one band hook per plugin, and `$` stays in that hook's file.
export const statusRows = (elements: BandElements, status: StatusBand): RenderElement => {
  const { Box, Text } = elements
  const context = contextText(status)
  const limits = limitsSegments(status)

  return (
    <Box flexDirection="column">
      <Text wrap="truncate-end">{runs(elements, headlineSegments(status))}</Text>
      {context === '' && limits.length === 0 ? null : (
        <Box>
          {context === '' ? null : <Text color={levelOf(status.contextPercent)}>{context}</Text>}
          {limits.length === 0 ? null : (
            <Text wrap="truncate-end">
              {context === '' ? null : <Text dimColor> │ </Text>}
              {runs(elements, limits)}
            </Text>
          )}
        </Box>
      )}
    </Box>
  )
}
