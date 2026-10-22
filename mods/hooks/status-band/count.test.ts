import { describe, expect, test } from 'claude-code/testing'

import {
  enabledPlugins,
  hookCommands,
  hooksFileCommands,
  installPaths,
  connectedServers,
  manifestHooks,
  under,
} from './count'

const GROUP = { matcher: 'Bash', hooks: [{ type: 'command' }, { type: 'command' }] }

describe('hookCommands', () => {
  test('counts every handler of every event', () => {
    expect(hookCommands({ PreToolUse: [GROUP, GROUP], Stop: [{ hooks: [{ type: 'command' }] }] })).toBe(5)
  })

  test('counts nothing in a value of another shape', () => {
    expect(hookCommands(undefined)).toBe(0)
    expect(hookCommands({ PreToolUse: 'no', Stop: [null, { hooks: 3 }] })).toBe(0)
  })
})

describe('hooksFileCommands', () => {
  test('reads the hooks a file wraps, and none from a function-hooks file', () => {
    expect(hooksFileCommands(JSON.stringify({ hooks: { Stop: [GROUP] } }))).toBe(2)
    expect(hooksFileCommands(JSON.stringify({ modules: ['./register.ts'] }))).toBe(0)
  })
})

describe('enabledPlugins', () => {
  test('keeps the plugins switched on', () => {
    expect(enabledPlugins({ enabledPlugins: { 'a@m': true, 'b@m': false } })).toEqual(['a@m'])
    expect(enabledPlugins({})).toEqual([])
  })
})

describe('installPaths', () => {
  test('takes the first install of each plugin', () => {
    const text = JSON.stringify({
      plugins: { 'a@m': [{ installPath: '/p/a' }, { installPath: '/p/old' }], 'b@m': [] },
    })

    expect(installPaths(text, '/work/repo')).toEqual({ 'a@m': '/p/a' })
  })

  test("prefers this project's install, then the user's own", () => {
    const text = JSON.stringify({
      plugins: {
        'a@m': [
          { scope: 'project', projectPath: '/work/other', installPath: '/p/other' },
          { scope: 'user', installPath: '/p/user' },
          { scope: 'project', projectPath: '/work/repo', installPath: '/p/repo' },
        ],
      },
    })

    expect(installPaths(text, '/work/repo/src')).toEqual({ 'a@m': '/p/repo' })
    expect(installPaths(text, '/work/repository')).toEqual({ 'a@m': '/p/user' })
  })

  test('takes the nearest project around the directory, whichever separator it uses', () => {
    const text = JSON.stringify({
      plugins: {
        'a@m': [
          { projectPath: 'C:\\work', installPath: '/p/outer' },
          { projectPath: 'C:\\work\\repo', installPath: '/p/inner' },
        ],
      },
    })

    expect(installPaths(text, 'C:\\work\\repo\\src')).toEqual({ 'a@m': '/p/inner' })
  })
})

describe('manifestHooks', () => {
  test('always reads the default file', () => {
    expect(manifestHooks('{}')).toEqual({ files: ['hooks/hooks.json'], inline: 0 })
  })

  test('adds a file the manifest names, once', () => {
    expect(manifestHooks(JSON.stringify({ hooks: './hooks.json' })).files).toEqual([
      'hooks/hooks.json',
      'hooks.json',
    ])
    expect(manifestHooks(JSON.stringify({ hooks: './hooks/hooks.json' })).files).toEqual([
      'hooks/hooks.json',
    ])
  })

  test('counts hooks the manifest carries inline', () => {
    expect(manifestHooks(JSON.stringify({ hooks: { Stop: [GROUP] } })).inline).toBe(2)
    expect(manifestHooks(JSON.stringify({ hooks: [{ hooks: { Stop: [GROUP] } }, './a.json'] }))).toEqual({
      files: ['hooks/hooks.json', 'a.json'],
      inline: 2,
    })
  })
})

describe('under', () => {
  test('joins a POSIX base with a forward slash', () => {
    expect(under('/home/me', '.claude')).toBe('/home/me/.claude')
    expect(under('/p/plain', 'hooks/hooks.json')).toBe('/p/plain/hooks/hooks.json')
  })

  test('keeps a backslash base in backslashes all the way down', () => {
    expect(under('C:\\Users\\me', '.claude')).toBe('C:\\Users\\me\\.claude')
    expect(under('C:\\p\\plain', 'hooks/hooks.json')).toBe('C:\\p\\plain\\hooks\\hooks.json')
  })

  test('leaves a base that already mixes in forward slashes on them', () => {
    expect(under('C:/Users/me', '.claude')).toBe('C:/Users/me/.claude')
    expect(under('C:\\Users/me', '.claude')).toBe('C:\\Users/me/.claude')
  })
})

describe('connectedServers', () => {
  const tool = (serverName: string, name: string) => ({ name: `mcp__${serverName}__${name}`, serverName })

  test('counts each server once, however many tools it has', () => {
    expect(connectedServers([tool('qmd', 'get'), tool('qmd', 'query'), tool('claude.ai Gmail', 'send')])).toBe(2)
  })

  test('leaves out a server that offers only its sign-in', () => {
    expect(
      connectedServers([
        tool('claude.ai Asana', 'authenticate'),
        tool('claude.ai Asana', 'complete_authentication'),
        tool('qmd', 'get'),
      ]),
    ).toBe(1)
  })
})
