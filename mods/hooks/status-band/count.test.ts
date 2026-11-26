import { describe, expect, test } from 'claude-code/testing'

import { enabledPlugins, installPaths, under } from './count'

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

describe('installPaths across separators', () => {
  test('matches a project path and a directory written with different separators', () => {
    const text = JSON.stringify({
      plugins: {
        'a@m': [
          { scope: 'user', installPath: '/p/user' },
          { scope: 'project', projectPath: 'C:\\work\\repo', installPath: '/p/repo' },
        ],
      },
    })

    expect(installPaths(text, 'C:/work/repo/src')).toEqual({ 'a@m': '/p/repo' })
    expect(installPaths(text, 'C:/work/repository')).toEqual({ 'a@m': '/p/user' })
    expect(
      installPaths(
        JSON.stringify({
          plugins: { 'a@m': [{ projectPath: 'C:/work/repo', installPath: '/p/repo' }, { installPath: '/p/user' }] },
        }),
        'C:\\work\\repo\\src',
      ),
    ).toEqual({ 'a@m': '/p/repo' })
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
