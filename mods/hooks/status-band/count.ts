// Pure hook counting: no engine types, so it runs and tests without `$`.

const DEFAULT_HOOKS_FILE = 'hooks/hooks.json'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// The commands under a settings.json `hooks` value: one per handler, so a
// matcher that runs two commands counts as two.
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

const covers = (projectPath: unknown, cwd: string): boolean =>
  typeof projectPath === 'string' &&
  (cwd === projectPath || cwd.startsWith(`${projectPath.replace(/[\\/]+$/, '')}/`))

// Where the installed-plugins file says each plugin's directory is. A plugin
// installed more than once is read from the install made for this project,
// else the user's own, else the first listed.
export const installPaths = (text: string, cwd: string): Record<string, string> => {
  const file: unknown = JSON.parse(text)
  const plugins = isRecord(file) && isRecord(file.plugins) ? file.plugins : {}

  return Object.fromEntries(
    Object.entries(plugins).flatMap(([id, listed]) => {
      const installs = (Array.isArray(listed) ? listed : []).filter(
        (install): install is Record<string, unknown> & { installPath: string } =>
          isRecord(install) && typeof install.installPath === 'string',
      )
      const install =
        installs.find(candidate => covers(candidate.projectPath, cwd)) ??
        installs.find(candidate => candidate.projectPath === undefined) ??
        installs[0]

      return install === undefined ? [] : [[id, install.installPath]]
    }),
  )
}

const relative = (path: string): string => path.replace(/^\.\//, '')

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
