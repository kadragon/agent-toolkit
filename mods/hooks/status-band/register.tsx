import { atom, update } from 'claude-code'
import type { Elements, EngineInterface, Register, RenderElement } from 'claude-code'

import type { StatusBand } from '../../types'
import {
  connectedServers,
  enabledPlugins,
  hookCommands,
  hooksFileCommands,
  installPaths,
  manifestHooks,
  under,
} from './count'
import {
  contextText,
  curateText,
  headlineSegments,
  levelOf,
  limitsSegments,
  mergedSegments,
  setupSegments,
  UNICODE,
} from './format'
import type { Glyphs, Segment } from './format'

// Layout after the claude-hud status line (github.com/jarrodwatts/claude-hud).
// The elapsed time and the reset countdowns read in minutes.
const TICK_MS = 60_000
const GIT_TIMEOUT_MS = 2000
const MINUTE_MS = 60_000
const DEFAULT_CACHE_TTL_MINUTES = 60
// The dev plugin's session-start hook nudges about a due harness-curate run
// once a day; the band keeps it in sight, asking the same script.
const CURATE_PLUGIN = 'dev@kadragon'
const CURATE_SCRIPT = 'skills/harness-curate/scripts/record_run.py'
const CURATE_DUE_PREFIX = 'HARNESS-CURATE DUE'
const CURATE_EVERY_MS = 10 * MINUTE_MS
const CURATE_TIMEOUT_MS = 10_000
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
  // Null once the session ended or the model changed: nothing is cached.
  cacheExpiresAt?: number | null
  cacheModel?: string
  // The counts of what the session is set up with, as last read.
  setup: Setup
  // False until this load read or reset them: a reload keeps what is drawn.
  hasSetup: boolean
  // Raised by a reset, so a read that started before it is dropped.
  setupEpoch: number
  setupRead?: Promise<void>
  // When the curate check last ran; unset, the next read runs it.
  curateCheckedAt?: number
  curateRead?: Promise<void>
}

type Setup = Pick<StatusBand, 'hooks' | 'skills' | 'mcp' | 'curateDue'>

// The handlers a plugin's default hooks file, its manifest and the files the
// manifest names add; a file that is not there adds none.
const pluginHooks = async ($: EngineInterface, root: string): Promise<number> => {
  const { files, inline } = await $.fs
    .read(under(root, '.claude-plugin/plugin.json'))
    .then(manifestHooks)
    .catch(() => manifestHooks('{}'))
  const counts = await Promise.all(
    files.map(file =>
      $.fs
        .read(under(root, file))
        .then(hooksFileCommands)
        .catch(() => 0),
    ),
  )

  return counts.reduce((total, count) => total + count, inline)
}

// Where the installed-plugins file says each plugin's directory is.
const readInstallPaths = async ($: EngineInterface): Promise<Record<string, string>> => {
  const configDir = await $.env.get('CLAUDE_CONFIG_DIR')
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE'))

  const claudeDir = configDir ?? (home === undefined ? undefined : under(home, '.claude'))

  if (claudeDir === undefined) throw new Error('no home directory')

  return installPaths(
    await $.fs.read(under(claudeDir, 'plugins/installed_plugins.json')),
    await $.session.cwd(),
  )
}

// Whether a harness-curate run is due here, judged as the session-start hook
// judges it: only in a harness repo, by the installed dev plugin's own script.
const readCurateDue = async ($: EngineInterface): Promise<boolean> => {
  if (!enabledPlugins(await $.settings.read()).includes(CURATE_PLUGIN)) return false

  const cwd = await $.session.cwd()

  if (!(await $.fs.exists(under(cwd, 'AGENTS.md')))) return false

  const root = (await readInstallPaths($))[CURATE_PLUGIN]

  if (root === undefined) return false

  const args = [under(root, CURATE_SCRIPT), '--check-due', '--project', cwd]
  const init = { timeoutMs: CURATE_TIMEOUT_MS }
  // As the hook does: `python3`, else `python` where only that is installed.
  const { exitCode, stdout } = await $.process
    .run(['python3', ...args], init)
    .catch(() => $.process.run(['python', ...args], init))

  return exitCode === 0 && stdout.startsWith(CURATE_DUE_PREFIX)
}

// The hook handlers in force: the settings' own and every enabled plugin's.
// The engine lists none, so they are counted off the files that declare them.
const countHooks = async ($: EngineInterface): Promise<number> => {
  const settings = await $.settings.read()

  if (settings.disableAllHooks === true) return 0

  if (settings.allowManagedHooksOnly === true) {
    return hookCommands((await $.settings.read({ source: 'policy' })).hooks)
  }

  const own = hookCommands(settings.hooks)
  const enabled = enabledPlugins(settings)

  if (enabled.length === 0) return own

  const paths = await readInstallPaths($)
  const counts = await Promise.all(
    enabled.map(id => (paths[id] === undefined ? 0 : pluginHooks($, paths[id]))),
  )

  return counts.reduce((total, count) => total + count, own)
}

// The skill listing and the MCP servers as /context counts them, estimated
// locally: no request is sent.
const readContext = async ($: EngineInterface): Promise<Pick<StatusBand, 'skills' | 'mcp'>> => {
  const { context } = await $.session.usage({ breakdown: 'summary' })
  const breakdown = context.breakdown

  if (breakdown === undefined) return {}

  const skills = breakdown.skills

  return {
    skills: skills === undefined ? undefined : { count: skills.totalSkills, tokens: skills.tokens },
    mcp: connectedServers(breakdown.mcpTools),
  }
}

// Reads the counts apart from the other figures, which must not wait for the
// files: one read at a time, and a count that cannot be read keeps the last
// one this session gave.
const loadSetup = ($: EngineInterface, live: Live): void => {
  if (live.setupRead !== undefined) return

  const epoch = live.setupEpoch

  live.setupRead = (async () => {
    const [hooks, context] = await Promise.all([
      countHooks($).catch(() => undefined),
      readContext($).catch(() => undefined),
    ])

    if (epoch !== live.setupEpoch) return

    const setup = {
      hooks: hooks ?? live.setup.hooks,
      skills: context?.skills ?? live.setup.skills,
      mcp: context?.mcp ?? live.setup.mcp,
    }

    live.setup = { ...live.setup, ...setup }
    live.hasSetup = true
    await update($, statusBand, current => (current === null ? null : { ...current, ...setup }))
  })()
    .catch(() => undefined)
    .finally(() => {
      live.setupRead = undefined
      // A reset came while this read ran: the counts are the new session's to read.
      if (epoch !== live.setupEpoch) loadSetup($, live)
    })
}

// The curate check spawns a scan, so it runs apart from the counts and at most
// once in a while; between runs, or when a run fails, the last answer stands.
const loadCurate = ($: EngineInterface, live: Live): void => {
  if (live.curateRead !== undefined) return

  const epoch = live.setupEpoch

  live.curateRead = (async () => {
    const now = await $.clock.now()

    if (epoch !== live.setupEpoch) return
    if (live.curateCheckedAt !== undefined && now - live.curateCheckedAt < CURATE_EVERY_MS) return

    live.curateCheckedAt = now
    const curateDue = await readCurateDue($).catch(() => undefined)

    if (epoch !== live.setupEpoch || curateDue === undefined) return

    live.setup = { ...live.setup, curateDue }
    live.hasSetup = true
    await update($, statusBand, current => (current === null ? null : { ...current, curateDue }))
  })()
    .catch(() => undefined)
    .finally(() => {
      live.curateRead = undefined
      // A reset came while this read ran: the new session asks again.
      if (epoch !== live.setupEpoch) loadCurate($, live)
    })
}

// The counts were another session's: they are left out until read again.
const resetSetup = (live: Live): void => {
  live.setup = {}
  live.hasSetup = true
  live.setupEpoch += 1
  // A run in the last session stamped its record: ask again.
  live.curateCheckedAt = undefined
}

// Only a response that read or wrote the prompt cache renews it.
const isCached = (usage: { cache_read_input_tokens: number; cache_creation_input_tokens: number } | null): boolean =>
  usage !== null && usage.cache_read_input_tokens + usage.cache_creation_input_tokens > 0

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

    // What the write decided, kept for after it: the engine may run the
    // function again, so it reads `live` and leaves it as it is.
    const before = { effort: live.effort, isFresh: live.isEffortFresh, cache: live.cacheExpiresAt }
    let decided: { effort: StatusBand['effort']; isForfeit: boolean } | undefined

    await update($, statusBand, current => {
      decided = undefined

      // A read that started earlier and ended later must not undo a newer one.
      if (order < live.drawn) return current

      live.drawn = order
      const name = model === '' ? (current?.model ?? '') : model
      let effort = before.effort

      if (before.isFresh) {
        // The step that reported it ran under this model.
      } else if (current !== null && current.model !== name) {
        // The effort was the last model's; the next step reports this one's.
        effort = undefined
      } else if (effort === undefined) {
        // A reload starts the module over; the session's value is still good.
        effort = current?.effort
      }

      // The cache was the model's that made it: a switch forfeits it.
      const cacheModel = live.cacheModel ?? current?.cacheModel
      const isForfeit = cacheModel !== undefined && name !== '' && cacheModel !== name
      const isCacheGone = isForfeit || live.cacheExpiresAt === null

      decided = { effort, isForfeit }

      return {
        model: name,
        effort,
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
        cacheExpiresAt: isCacheGone
          ? undefined
          : (live.cacheExpiresAt ?? current?.cacheExpiresAt),
        cacheModel: isCacheGone ? undefined : cacheModel,
        hooks: live.hasSetup ? live.setup.hooks : current?.hooks,
        skills: live.hasSetup ? live.setup.skills : current?.skills,
        mcp: live.hasSetup ? live.setup.mcp : current?.mcp,
        curateDue: live.hasSetup ? live.setup.curateDue : current?.curateDue,
      }
    })

    if (decided !== undefined) {
      // A step that reported meanwhile is newer than what this read decided.
      if (live.effort === before.effort) live.effort = decided.effort
      if (before.isFresh) live.isEffortFresh = false

      if (decided.isForfeit && live.cacheExpiresAt === before.cache) {
        live.cacheExpiresAt = null
        live.cacheModel = undefined
      }
    }
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
    loadSetup($, live)
    loadCurate($, live)
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
  const live: Live = {
    effort: undefined,
    isEffortFresh: false,
    asked: 0,
    drawn: 0,
    setup: {},
    hasSetup: false,
    setupEpoch: 0,
  }

  // Neither hook waits for the read: a slow git must not hold the session.
  on('session.start', async ($, e, next) => {
    const result = await next(e)

    resetSetup(live)
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
  // Whatever ends the session, the conversation that follows has its own cache
  // and its own counts, and where the process goes on the band shows it at once.
  on('session.end', async ($, e, next) => {
    const result = await next(e)

    live.cacheExpiresAt = null
    live.cacheModel = undefined
    resetSetup(live)
    void watch($, live)

    return result
  })

  // The request is passed on untouched: only its effort is read, and a
  // response of the main loop renews the prompt cache from when it was sent.
  on('turn.step', async function* ($, e, next) {
    if (e.agentId === undefined) live.isEffortFresh = true

    if (e.agentId === undefined && e.effort !== live.effort) {
      const effort = e.effort

      live.effort = effort
      await update($, statusBand, current =>
        current === null ? null : { ...current, effort },
      ).catch(() => undefined)
    }

    const sentAt = e.agentId === undefined ? $.clock.now().catch(() => undefined) : undefined
    const result = yield* next(e)

    // The step does not wait for the band: the countdown is written behind it.
    if (sentAt !== undefined && isCached(result.usage)) {
      void sentAt
        .then(async at => {
          if (at === undefined) return

          const cacheExpiresAt = at + cacheTtlMs
          const model = await $.session.model().catch(() => '')
          const cacheModel = model === '' ? undefined : model

          live.cacheExpiresAt = cacheExpiresAt
          live.cacheModel = cacheModel
          await update($, statusBand, current =>
            current === null ? null : { ...current, cacheExpiresAt, cacheModel },
          )
        })
        .catch(() => undefined)
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

// This mod's rows of the band above the prompt, under a blank row that keeps
// them off the line above where the band has a row to spare. The setup gets a
// row of its own where `isSplit`, else it rides on the headline; `glyphs` is
// the set the rows draw beyond plain letters. `hooks/band.tsx`
// draws them: the engine takes one band hook per plugin, and `$` stays in that
// hook's file.
export const statusRows = (
  elements: BandElements,
  status: StatusBand,
  {
    hasMargin,
    isSplit,
    glyphs = UNICODE,
  }: { hasMargin: boolean; isSplit: boolean; glyphs?: Glyphs },
): RenderElement => {
  const { Box, Text } = elements
  const setup = isSplit ? setupSegments(status, glyphs) : []
  const context = contextText(status, glyphs)
  const limits = limitsSegments(status, glyphs)
  const curate = curateText(status)

  return (
    <Box key="status-band" flexDirection="column" marginTop={hasMargin ? 1 : 0}>
      <Text wrap="truncate-end">
        {runs(
          elements,
          isSplit ? headlineSegments(status, glyphs) : mergedSegments(status, glyphs),
        )}
      </Text>
      {setup.length === 0 ? null : <Text wrap="truncate-end">{runs(elements, setup)}</Text>}
      {context === '' && limits.length === 0 && curate === '' ? null : (
        <Box>
          {context === '' ? null : <Text color={levelOf(status.contextPercent)}>{context}</Text>}
          {limits.length === 0 ? null : (
            <Text wrap="truncate-end">
              {context === '' ? null : <Text dimColor>{glyphs.separator}</Text>}
              {runs(elements, limits)}
            </Text>
          )}
          {curate === '' ? null : (
            <Box>
              {context === '' && limits.length === 0 ? null : (
                <Text dimColor>{glyphs.separator}</Text>
              )}
              <Text color="warning" wrap="truncate-end">
                {curate}
              </Text>
            </Box>
          )}
        </Box>
      )}
    </Box>
  )
}
