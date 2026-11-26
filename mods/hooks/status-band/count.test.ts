import { describe, expect, test } from 'claude-code/testing'

import { enabledPlugins, installPath, under } from './count'

describe('enabledPlugins', () => {
  test('keeps the plugins switched on', () => {
    expect(enabledPlugins({ enabledPlugins: { 'a@m': true, 'b@m': false } })).toEqual(['a@m'])
    expect(enabledPlugins({})).toEqual([])
  })
})

const selectInstall = (
  text: string,
  cwd: string,
  sameDirectory = async (_project: string, _ancestor: string): Promise<boolean> => false,
) => installPath(text, cwd, 'a@m', sameDirectory)

describe('installPath', () => {
  test('takes the first install for the named plugin', async () => {
    const text = JSON.stringify({
      plugins: { 'a@m': [{ installPath: '/p/a' }, { installPath: '/p/old' }], 'b@m': [] },
    })

    expect(await selectInstall(text, '/work/repo')).toBe('/p/a')
    expect(await installPath(text, '/work/repo', 'b@m', async () => false)).toBeUndefined()
  })

  test("prefers this project's install, then the user's own", async () => {
    const text = JSON.stringify({
      plugins: {
        'a@m': [
          { scope: 'project', projectPath: '/work/other', installPath: '/p/other' },
          { scope: 'user', installPath: '/p/user' },
          { scope: 'project', projectPath: '/work/repo', installPath: '/p/repo' },
        ],
      },
    })

    expect(await selectInstall(text, '/work/repo/src')).toBe('/p/repo')
    expect(await selectInstall(text, '/work/repository')).toBe('/p/user')
  })

  test('takes the nearest project around the directory, whichever separator it uses', async () => {
    const text = JSON.stringify({
      plugins: {
        'a@m': [
          { projectPath: 'C:\\work', installPath: '/p/outer' },
          { projectPath: 'C:\\work\\repo', installPath: '/p/inner' },
        ],
      },
    })

    expect(await selectInstall(text, 'C:\\work\\repo\\src')).toBe('/p/inner')
  })
})

describe('installPath without a matching install', () => {
  test("does not borrow another project's install when this directory has none", async () => {
    const other = JSON.stringify({
      plugins: { 'a@m': [{ scope: 'project', projectPath: '/work/other', installPath: '/p/other' }] },
    })
    const withUser = JSON.stringify({
      plugins: {
        'a@m': [
          { scope: 'project', projectPath: '/work/other', installPath: '/p/other' },
          { scope: 'user', installPath: '/p/user' },
        ],
      },
    })

    expect(await selectInstall(other, '/work/repo')).toBeUndefined()
    expect(await selectInstall(withUser, '/work/repo')).toBe('/p/user')
  })
})

describe('installPath across separators', () => {
  test('matches a project path and a directory written with different separators', async () => {
    const text = JSON.stringify({
      plugins: {
        'a@m': [
          { scope: 'user', installPath: '/p/user' },
          { scope: 'project', projectPath: 'C:\\work\\repo', installPath: '/p/repo' },
        ],
      },
    })

    expect(await selectInstall(text, 'C:/work/repo/src')).toBe('/p/repo')
    expect(await selectInstall(text, 'c:/WORK/Repository', async () => true)).toBe('/p/user')
    expect(
      await selectInstall(
        JSON.stringify({
          plugins: { 'a@m': [{ projectPath: 'C:/work/repo', installPath: '/p/repo' }, { installPath: '/p/user' }] },
        }),
        'C:\\work\\repo\\src',
      ),
    ).toBe('/p/repo')
  })
})

describe('installPath path case', () => {
  test('matches a confirmed Windows ancestor across separators and case', async () => {
    const projectPath = 'C:\\work\\repo'
    const text = JSON.stringify({
      plugins: { 'a@m': [{ projectPath, installPath: '/p/repo' }, { installPath: '/p/user' }] },
    })
    const sameDirectory = async (project: string, ancestor: string) =>
      project === projectPath && ancestor === 'c:/WORK/Repo'

    expect(await selectInstall(text, 'c:/WORK/Repo/src', sameDirectory)).toBe('/p/repo')
  })

  test('skips a different Windows ancestor even when it is the only installed copy', async () => {
    const text = JSON.stringify({
      plugins: { 'a@m': [{ projectPath: 'C:\\work\\Repo', installPath: '/p/repo' }] },
    })

    expect(await selectInstall(text, 'C:\\work\\repo\\src')).toBeUndefined()
  })

  test('matches a confirmed UNC ancestor across separators and case', async () => {
    const projectPath = '\\\\Server\\Share\\Repo'
    const text = JSON.stringify({
      plugins: {
        'a@m': [
          { installPath: '/p/user' },
          { projectPath, installPath: '/p/repo' },
        ],
      },
    })

    const sameDirectory = async (project: string, ancestor: string) =>
      project === projectPath && ancestor === '//server/share/repo'

    expect(await selectInstall(text, '//server/share/repo/src', sameDirectory)).toBe('/p/repo')
  })

  test('keeps POSIX project paths case sensitive', async () => {
    const text = JSON.stringify({
      plugins: {
        'a@m': [
          { installPath: '/p/user' },
          { projectPath: '/work/Repo', installPath: '/p/repo' },
        ],
      },
    })

    expect(await selectInstall(text, '/work/repo/src', async () => true)).toBe('/p/user')
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
