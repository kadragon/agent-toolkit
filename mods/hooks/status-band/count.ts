// Pure hook counting: no engine types, so it runs and tests without `$`.

const DEFAULT_HOOKS_FILE = 'hooks/hooks.json'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// The handlers under a settings.json `hooks` value, of whatever type: a
// matcher that runs two counts as two.
export const hookCommands = (hooks: unknown): number => {
  if (!isRecord(hooks)) return 0

  return Object.values(hooks).reduce<number>((total, groups) => {
    if (!Array.isArray(groups)) return total

    return groups.reduce<number>(
      (sum, group) => sum + (isRecord(group) && Array.isArray(group.hooks) ? group.hooks.length : 0),
      total,
    )
  }, 0)
}

// A hooks file wraps the same value in `hooks`; a function-hooks file has none.
export const hooksFileCommands = (text: string): number => {
  const file: unknown = JSON.parse(text)

  return isRecord(file) ? hookCommands(file.hooks) : 0
}

// The plugins the settings switch on, by their `<name>@<marketplace>` id.
export const enabledPlugins = (settings: Record<string, unknown>): string[] =>
  isRecord(settings.enabledPlugins)
    ? Object.entries(settings.enabledPlugins).flatMap(([id, isOn]) => (isOn === true ? [id] : []))
    : []

// How much of `cwd` a project path covers, in characters; 0 when it is not
// that directory or one beneath it. Either separator ends a segment.
const covered = (projectPath: unknown, cwd: string): number => {
  if (typeof projectPath !== 'string') return 0

  const root = projectPath.replace(/[\\/]+$/, '')
  const isWithin = cwd === root || (cwd.startsWith(root) && /[\\/]/.test(cwd.charAt(root.length)))

  return isWithin ? root.length + 1 : 0
}

// Where the installed-plugins file says each plugin's directory is. A plugin
// installed more than once is read from the install made for the nearest
// project around `cwd`, else the user's own, else the first listed.
export const installPaths = (text: string, cwd: string): Record<string, string> => {
  const file: unknown = JSON.parse(text)
  const plugins = isRecord(file) && isRecord(file.plugins) ? file.plugins : {}

  return Object.fromEntries(
    Object.entries(plugins).flatMap(([id, listed]) => {
      const installs = (Array.isArray(listed) ? listed : []).filter(
        (install): install is Record<string, unknown> & { installPath: string } =>
          isRecord(install) && typeof install.installPath === 'string',
      )
      const nearest = installs.reduce<(typeof installs)[number] | undefined>(
        (best, candidate) =>
          covered(candidate.projectPath, cwd) > covered(best?.projectPath, cwd) ? candidate : best,
        undefined,
      )
      const install =
        nearest ?? installs.find(candidate => candidate.projectPath === undefined) ?? installs[0]

      return install === undefined ? [] : [[id, install.installPath]]
    }),
  )
}

// The tools a server that needs a sign-in offers in place of its own.
const SIGN_IN_TOOLS = new Set(['authenticate', 'complete_authentication'])

// The MCP servers connected, by the tools the context carries: a server counts
// once, however many tools it has, and not at all while it offers only its sign-in.
export const connectedServers = (tools: readonly { name: string; serverName: string }[]): number =>
  new Set(
    tools
      .filter(tool => !SIGN_IN_TOOLS.has(tool.name.slice(`mcp__${tool.serverName}__`.length)))
      .map(tool => tool.serverName),
  ).size

const relative = (path: string): string => path.replace(/^\.\//, '')

// `path` beneath `base`, in the separator `base` is written with: a Windows
// home or install path keeps its backslashes all the way down.
export const under = (base: string, path: string): string =>
  base.includes('\\') && !base.includes('/')
    ? `${base}\\${path.replace(/\//g, '\\')}`
    : `${base}/${path}`

// What a plugin's manifest adds to its default hooks file: the files it names,
// and the hooks it carries inline. The engine loads both together.
export const manifestHooks = (text: string): { files: string[]; inline: number } => {
  const manifest: unknown = JSON.parse(text)
  const named = isRecord(manifest) ? manifest.hooks : undefined
  const files = new Set([DEFAULT_HOOKS_FILE])
  let inline = 0

  for (const entry of Array.isArray(named) ? named : [named]) {
    if (typeof entry === 'string') files.add(relative(entry))
    else if (isRecord(entry)) inline += hookCommands(isRecord(entry.hooks) ? entry.hooks : entry)
  }

  return { files: [...files], inline }
}
