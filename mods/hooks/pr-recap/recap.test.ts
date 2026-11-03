import { describe, expect, test } from 'claude-code/testing'

import { ago, landedPath, logArgv, parseLog, summaryOf, totalsOf } from './recap'

const RS = '\x1e'
const US = '\x1f'
const GS = '\x1d'
const record = (sha: string, subject: string, time: number, body: string, numstat: string[]) =>
  `${RS}${sha}${US}${subject}${US}kangdonguk${US}${time}${US}${body}${GS}\n\n${numstat.join('\n')}\n`

const LOG = [
  record(
    'c31d51bc34550d835dfce3c958b2e422864aa3c7',
    '[HARNESS] commit-guard reads an in-chain switch (#381)',
    1793589760,
    '* [HARNESS] commit-guard reads an in-chain switch\n\nThe hook only read the live branch.\nNow it predicts it.\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n\n---------\n',
    ['12\t3\tdev/hooks/commit-guard/guard.py', '40\t0\tdev/hooks/commit-guard/test_guard.py', '2\t1\tCHANGELOG.md'],
  ),
  record('aaaa', 'chore: local tweak', 1793580000, '', ['1\t1\tREADME.md']),
  record('bbbb', 'Merge pull request #379 from kadragon/feat/x', 1793570000, '[FEAT] Add x\n\nWhy x.\n', [
    '-\t-\tassets/icon.png',
    '5\t0\tsrc/{old => new}/x.ts',
  ]),
  record('cccc', '[FIX] one more (#377)', 1793560000, '', ['1\t0\ta.ts']),
].join('')

describe('parseLog', () => {
  test('reads squash and merge PRs, newest first, skipping direct commits', () => {
    const prs = parseLog(LOG, 3)

    expect(prs.map(pr => pr.number)).toEqual([381, 379, 377])
    expect(prs[0]).toMatchObject({
      sha: 'c31d51bc34550d835dfce3c958b2e422864aa3c7',
      tag: 'HARNESS',
      title: 'commit-guard reads an in-chain switch',
      author: 'kangdonguk',
      mergedAt: 1793589760 * 1000,
      summary: ['The hook only read the live branch.\nNow it predicts it.'],
    })
    expect(prs[0]?.files.map(file => [file.path, file.added, file.deleted])).toEqual([
      ['dev/hooks/commit-guard/guard.py', 12, 3],
      ['dev/hooks/commit-guard/test_guard.py', 40, 0],
      ['CHANGELOG.md', 2, 1],
    ])
    expect(prs[1]).toMatchObject({ tag: 'FEAT', title: 'Add x', summary: ['Why x.'] })
    expect(prs[1]?.files).toEqual([
      { path: 'assets/icon.png', added: 0, deleted: 0, isBinary: true },
      { path: 'src/new/x.ts', added: 5, deleted: 0, isBinary: false },
    ])
  })

  test('stops at the count and reads CRLF output', () => {
    const prs = parseLog(LOG.replace(/\n/g, '\r\n'), 1)

    expect(prs.map(pr => pr.number)).toEqual([381])
    expect(prs[0]?.files).toHaveLength(3)
    expect(prs[0]?.summary).toEqual(['The hook only read the live branch.\nNow it predicts it.'])
  })

  test('a merge commit with no body takes its subject as the title', () => {
    const prs = parseLog(record('dddd', 'Merge pull request #12 from x/y', 1, '', ['1\t0\ta.ts']), 3)

    expect(prs[0]).toMatchObject({ number: 12, title: 'Merge pull request #12 from x/y', summary: [] })
  })

  test('cut-short output drops its partial last record', () => {
    const cut = LOG.slice(0, LOG.lastIndexOf('1\t0\ta.ts'))

    expect(parseLog(cut, 3, true).map(pr => pr.number)).toEqual([381, 379])
    expect(parseLog(LOG, 3, false).map(pr => pr.number)).toEqual([381, 379, 377])
  })

  test('the log asks git for paths unquoted', () => {
    expect(logArgv(60).slice(0, 3)).toEqual(['git', '-c', 'core.quotePath=false'])
    expect(parseLog(record('eeee', '[DOCS] 한글 (#9)', 1, '', ['3\t0\tdocs/한글.md']), 1)[0]?.files[0]).toMatchObject({
      path: 'docs/한글.md',
    })
  })

  test('an empty log has no PRs', () => {
    expect(parseLog('', 3)).toEqual([])
  })
})

test('a rename lands on its new path', () => {
  expect(landedPath('src/{old => new}/x.ts')).toBe('src/new/x.ts')
  expect(landedPath('src/{ => sub}/x.ts')).toBe('src/sub/x.ts')
  expect(landedPath('a.ts => b.ts')).toBe('b.ts')
})

test('a summary drops trailers, rules and the title bullet', () => {
  expect(summaryOf('* [FIX] title\n\nbody one\n\nSigned-off-by: me\n', 'title')).toEqual(['body one'])
  expect(summaryOf('', 'title')).toEqual([])
})

test('totals add up every file', () => {
  expect(totalsOf(parseLog(LOG, 1)[0]?.files ?? [])).toEqual({ added: 54, deleted: 4 })
})

test('ago reads in minutes, hours and days', () => {
  expect(ago(0, 5 * 60_000)).toBe('5분 전')
  expect(ago(0, 3 * 3_600_000)).toBe('3시간 전')
  expect(ago(0, 72 * 3_600_000)).toBe('3일 전')
})
