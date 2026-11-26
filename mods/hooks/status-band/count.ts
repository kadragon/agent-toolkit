// Pure plugin and path reads: no engine types, so it runs and tests without `$`.

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

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

// `path` beneath `base`, in the separator `base` is written with: a Windows
// home or install path keeps its backslashes all the way down.
export const under = (base: string, path: string): string =>
  base.includes('\\') && !base.includes('/')
    ? `${base}\\${path.replace(/\//g, '\\')}`
    : `${base}/${path}`
