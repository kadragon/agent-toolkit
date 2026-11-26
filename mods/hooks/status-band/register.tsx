import { atom, update } from 'claude-code'
import type { Elements, EngineInterface, Register, RenderElement } from 'claude-code'

import type { StatusBand } from '../../types'
import { enabledPlugins, installPaths, under } from './count'
import {
  cellsByLength,
  contextSegments,
  curateText,
  headlineSegments,
  isSameModel,
  levelOf,
  timesSegments,
  UNICODE,
} from './format'
import type { Glyphs, Segment } from './format'

// ---- SECTION MAP ----
// Read this file in ranges, not whole: find a name with `grep -n '<name>'` and read only
// its range. Pure counting and text helpers live in count.ts and format.ts. The names
// below are checked against the real top-level functions by `scripts/check_mods.py`.
//   curate-due reads: readInstallPaths, readDevRoot, python, readCurateDue
//   curate check and verdict: checkCurateThrottled, dropCurateVerdict
//   live refresh (git, cache window, tick): isCached, refresh, watch
//   entry points (register holds every on(...) hook handler): startStatusBand, register
//   rendering the band rows: runs, statusRows

// Layout after the claude-hud status line (github.com/jarrodwatts/claude-hud).
const MINUTE_MS = 60_000
const TICK_MS = MINUTE_MS
const GIT_TIMEOUT_MS = 2000
const DEFAULT_CACHE_TTL_MINUTES = 60
// The dev plugin's session-start hook nudges about a due harness-curate run
// once a day; the band keeps it in sight, asking the same script.
const CURATE_PLUGIN = 'dev@kadragon'
const CURATE_SCRIPT = 'skills/harness-curate/scripts/record_run.py'
const CURATE_DUE_PREFIX = 'HARNESS-CURATE DUE'
const CURATE_EVERY_MS = 10 * MINUTE_MS
const CURATE_TIMEOUT_MS = 10_000
const DEV_PLUGIN = CURATE_PLUGIN
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
  setup: Setup
  hasSessionCurateVerdict: boolean
  // Raised by a reset, so a read that started before it is dropped.
  setupEpoch: number
  // When the curate check last ran; unset, the next read runs it.
  curateCheckedAt?: number
  curateRead?: Promise<void>
}

type Setup = Pick<StatusBand, 'curateDue'>

// Where the installed-plugins file says each plugin's directory is.
async function readInstallPaths($: EngineInterface): Promise<Record<string, string>> {
  const configDir = await $.env.get('CLAUDE_CONFIG_DIR')
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE'))

  const claudeDir = configDir ?? (home === undefined ? undefined : under(home, '.claude'))

  if (claudeDir === undefined) throw new Error('no home directory')

  return installPaths(
    await $.fs.read(under(claudeDir, 'plugins/installed_plugins.json')),
    await $.session.cwd(),
  )
}

// Where the dev plugin is installed, when the settings switch it on.
async function readDevRoot($: EngineInterface): Promise<string | undefined> {
  if (!enabledPlugins(await $.settings.read()).includes(DEV_PLUGIN)) return undefined

  return (await readInstallPaths($))[DEV_PLUGIN]
}

// As the hooks do: `python3`, else `python` where only that is installed.
function python(
  $: EngineInterface,
  args: string[],
  init: { timeoutMs: number; cwd?: string },
): Promise<{ exitCode: number; stdout: string }> {
  return $.process.run(['python3', ...args], init).catch(() => $.process.run(['python', ...args], init))
}

// Whether a harness-curate run is due here, judged as the session-start hook
// judges it: only in a harness repo, by the installed dev plugin's own script.
async function readCurateDue($: EngineInterface): Promise<boolean> {
  const cwd = await $.session.cwd()

  if (!(await $.fs.exists(under(cwd, 'AGENTS.md')))) return false

  const root = await readDevRoot($)

  if (root === undefined) return false

  const { exitCode, stdout } = await python(
    $,
    [under(root, CURATE_SCRIPT), '--check-due', '--project', cwd],
    { timeoutMs: CURATE_TIMEOUT_MS },
  )

  return exitCode === 0 && stdout.startsWith(CURATE_DUE_PREFIX)
}

function checkCurateThrottled($: EngineInterface, live: Live): void {
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
    live.hasSessionCurateVerdict = true
    await update($, statusBand, current => (current === null ? null : { ...current, curateDue }))
  })()
    .catch(() => undefined)
    .finally(() => {
      live.curateRead = undefined
      // A reset came while this read ran: the new session asks again.
      if (epoch !== live.setupEpoch) checkCurateThrottled($, live)
    })
}

const dropCurateVerdict = (live: Live): void => {
  live.setup = {}
  live.hasSessionCurateVerdict = true
  live.setupEpoch += 1
  // A run in the last session stamped its record: ask again.
  live.curateCheckedAt = undefined
}

// Only a response that read or wrote the prompt cache renews it.
const isCached = (usage: { cache_read_input_tokens: number; cache_creation_input_tokens: number } | null): boolean =>
  usage !== null && usage.cache_read_input_tokens + usage.cache_creation_input_tokens > 0

// The band is a convenience: a figure the engine cannot give is left out or
// kept as last read, and nothing here may fail a hook.
async function refresh($: EngineInterface, live: Live): Promise<void> {
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
      const isForfeit = cacheModel !== undefined && name !== '' && !isSameModel(cacheModel, name)
      const isCacheGone = isForfeit || live.cacheExpiresAt === null

      decided = { effort, isForfeit }

      return {
        model: name,
        effort,
        cwd: cwd === '' ? (current?.cwd ?? '') : cwd,
        branch: branch === null ? current?.branch : branch === '' ? undefined : branch,
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
        curateDue: live.hasSessionCurateVerdict ? live.setup.curateDue : current?.curateDue,
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
async function watch($: EngineInterface, live: Live): Promise<void> {
  try {
    const surfaces = await $.session.surfaces()

    if (!surfaces.some(surface => BAND_SURFACES.includes(surface))) {
      live.tick?.cancel()
      live.tick = undefined

      return
    }

    live.tick ??= $.clock.every(TICK_MS, () => void refresh($, live))
    checkCurateThrottled($, live)
    await refresh($, live)
  } catch {
    // Nothing to draw on.
  }
}

// The band's state for this load, set by register; unset while the band is off.
const loaded: { live?: Live } = {}

// The engine takes one session.start hook per plugin, and register.ts holds it.
// Nothing waits for the read: a slow git must not hold the session.
export function startStatusBand($: EngineInterface): void {
  const live = loaded.live

  if (live === undefined) return

  dropCurateVerdict(live)
  void watch($, live)
}

export const register: Register = (on, options) => {
  loaded.live = undefined
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
    hasSessionCurateVerdict: false,
    setupEpoch: 0,
  }

  loaded.live = live

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
  // and where the process goes on the band shows it at once.
  on('session.end', async ($, e, next) => {
    const result = await next(e)

    live.cacheExpiresAt = null
    live.cacheModel = undefined
    dropCurateVerdict(live)
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
    const epoch = live.setupEpoch
    const result = yield* next(e)

    // The step does not wait for the band: the countdown is written behind it.
    if (sentAt !== undefined && isCached(result.usage)) {
      void sentAt
        .then(async at => {
          if (at === undefined) return

          const cacheExpiresAt = at + cacheTtlMs
          const cacheModel = e.model || undefined
          const sessionModel = await $.session.model().catch(() => '')

          if (epoch !== live.setupEpoch) return

          if (
            cacheModel !== undefined &&
            sessionModel !== '' &&
            !isSameModel(cacheModel, sessionModel)
          ) {
            return
          }

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
// them off the line above where the band has a row to spare: the headline,
// then the context fill, the windows and the cache countdown. `glyphs` is the
// set the rows draw beyond plain letters; `columns` is the row's width, where
// a figure row wider than it drops the reset times so the cache is not cut.
// `hooks/band.tsx` draws them: the engine takes one band hook per plugin, and
// `$` stays in that hook's file.
export const statusRows = (
  elements: BandElements,
  status: StatusBand,
  {
    hasMargin,
    glyphs = UNICODE,
    columns,
  }: { hasMargin: boolean; glyphs?: Glyphs; columns?: number },
): RenderElement => {
  const { Box, Text } = elements
  const context = contextSegments(status)
  const curate = curateText(status)
  const separator = glyphs.separator.length
  const taken =
    (context.length === 0 ? 0 : cellsByLength(context) + separator) +
    (curate === '' ? 0 : curate.length + separator)
  const times = timesSegments(status, glyphs, columns === undefined ? undefined : columns - taken)

  return (
    <Box key="status-band" flexDirection="column" marginTop={hasMargin ? 1 : 0}>
      <Text wrap="truncate-end">{runs(elements, headlineSegments(status, glyphs))}</Text>
      {context.length === 0 && times.length === 0 && curate === '' ? null : (
        <Box>
          {context.length === 0 ? null : (
            <Text color={levelOf(status.contextPercent)} wrap="truncate-end">
              {runs(elements, context)}
            </Text>
          )}
          {times.length === 0 ? null : (
            <Text wrap="truncate-end">
              {context.length === 0 ? null : <Text dimColor>{glyphs.separator}</Text>}
              {runs(elements, times)}
            </Text>
          )}
          {curate === '' ? null : (
            <Box>
              {context.length === 0 && times.length === 0 ? null : (
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
