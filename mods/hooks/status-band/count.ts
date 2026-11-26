const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// The plugins the settings switch on, by their `<name>@<marketplace>` id.
export const enabledPlugins = (settings: Record<string, unknown>): string[] =>
  isRecord(settings.enabledPlugins)
    ? Object.entries(settings.enabledPlugins).flatMap(([id, isOn]) => (isOn === true ? [id] : []))
    : []

const slashed = (path: string): string => path.replace(/\\/g, '/')

const isWindowsPath = (path: string): boolean => /^(?:[a-z]:\/|\/\/[^/]+\/[^/]+)/i.test(path)

type Coverage = { length: number; caseVariant?: string }

const covered = (projectPath: string, cwd: string): Coverage | undefined => {
  const path = slashed(projectPath)
  const root = path.replace(/\/+$/, '')
  const here = slashed(cwd)
  const length = root.length + 1

  if (here === root || here.startsWith(`${root}/`)) return { length }
  if (!isWindowsPath(path) || !isWindowsPath(here)) return undefined

  const ancestor = here.split('/').slice(0, root.split('/').length).join('/')

  if (ancestor.toLowerCase() !== root.toLowerCase()) return undefined

  const end = /^[a-z]:$/i.test(ancestor) ? ancestor.length + 1 : ancestor.length

  return { length, caseVariant: cwd.slice(0, end) }
}

// Pick the nearest project install, then the user's, then the first eligible install.
export const installPath = async (
  text: string,
  cwd: string,
  id: string,
  sameDirectory: (projectPath: string, ancestor: string) => Promise<boolean>,
): Promise<string | undefined> => {
  const file: unknown = JSON.parse(text)
  const plugins = isRecord(file) && isRecord(file.plugins) ? file.plugins : {}
  const installs = plugins[id]

  if (!Array.isArray(installs)) return undefined

  let first: string | undefined
  let user: string | undefined
  let nearest: { path: string; length: number } | undefined

  for (const install of installs) {
    if (!isRecord(install) || typeof install.installPath !== 'string') continue

    const projectPath = install.projectPath

    if (typeof projectPath === 'string') {
      const match = covered(projectPath, cwd)

      if (match !== undefined) {
        if (match.caseVariant !== undefined && !(await sameDirectory(projectPath, match.caseVariant))) {
          continue
        }

        if (match.length > (nearest?.length ?? 0)) {
          nearest = { path: install.installPath, length: match.length }
        }
      }
    } else if (projectPath === undefined) {
      user ??= install.installPath
    }

    first ??= install.installPath
  }

  return nearest?.path ?? user ?? first
}

// `path` beneath `base`, in the separator `base` is written with: a Windows
// home or install path keeps its backslashes all the way down.
export const under = (base: string, path: string): string =>
  base.includes('\\') && !base.includes('/')
    ? `${base}\\${path.replace(/\//g, '\\')}`
    : `${base}/${path}`
