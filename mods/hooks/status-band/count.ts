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

// Where the installed-plugins file says each plugin's directory is.
export const installPaths = (text: string): Record<string, string> => {
  const file: unknown = JSON.parse(text)
  const plugins = isRecord(file) && isRecord(file.plugins) ? file.plugins : {}

  return Object.fromEntries(
    Object.entries(plugins).flatMap(([id, installs]) => {
      const first: unknown = Array.isArray(installs) ? installs[0] : undefined

      return isRecord(first) && typeof first.installPath === 'string'
        ? [[id, first.installPath]]
        : []
    }),
  )
}

const relative = (path: string): string => path.replace(/^\.\//, '')

// What a plugin's manifest adds to its default hooks file: the files it names,
// and the hooks it carries inline.
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
