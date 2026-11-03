import { expect, test } from 'claude-code/testing'

import type { Pr } from '../../types'
import { capDiff, count, DIFF_CAP, diffArgv, explainPrompt, parseExplain } from './explain'

const PR: Pr = {
  number: 382,
  sha: 'abc123',
  tag: 'FEAT',
  title: 'pr-recap side pane',
  author: 'kangdonguk',
  mergedAt: 0,
  summary: ['A pane shows the last PR.'],
  files: [{ path: 'mods/hooks/pr-recap/register.tsx', added: 300, deleted: 2, isBinary: false }],
}

test('the prompt carries the title, body, files and diff', () => {
  const prompt = explainPrompt(PR, 'diff --git a/x b/x')

  expect(prompt).toContain('Title: [FEAT] pr-recap side pane')
  expect(prompt).toContain('A pane shows the last PR.')
  expect(prompt).toContain('mods/hooks/pr-recap/register.tsx +300 -2')
  expect(prompt).toContain('diff --git a/x b/x')
})

test('a long diff is cut at the cap', () => {
  const cut = capDiff('x'.repeat(DIFF_CAP + 10))

  expect(cut.startsWith('x'.repeat(DIFF_CAP))).toBe(true)
  expect(cut).toContain(`diff cut at ${DIFF_CAP} characters`)
  expect(capDiff('short')).toBe('short')
})

test('the diff is read against the parent the PR landed on', () => {
  expect(diffArgv('abc123').slice(-2)).toEqual(['abc123^1', 'abc123'])
})

test('a reply parses into a summary and ordered boxes, the last linking nowhere', () => {
  const reply = `Here you go:
{"summary": "오른쪽 패널을 새로 만들었다.", "nodes": [
  {"name": "상태 표시줄", "note": "화면 폭 전달", "change": "changed", "link": "폭 전달"},
  {"name": "PR 요약 패널", "note": "새로 추가", "change": "added", "link": "읽기"},
  {"name": "git 이력", "note": "읽기만 함", "change": "bogus", "link": "남은 링크"}
]}`

  expect(parseExplain(reply)).toEqual({
    summary: '오른쪽 패널을 새로 만들었다.',
    nodes: [
      { name: '상태 표시줄', note: '화면 폭 전달', change: 'changed', link: '폭 전달' },
      { name: 'PR 요약 패널', note: '새로 추가', change: 'added', link: '읽기' },
      { name: 'git 이력', note: '읽기만 함', change: 'same', link: '' },
    ],
  })
})

test('fields are clipped and the boxes capped at five', () => {
  const nodes = Array.from({ length: 7 }, (_, index) => ({
    name: `아주 긴 이름을 가진 구성 요소 ${index}`,
    note: 'n',
    change: 'same',
    link: 'l',
  }))
  const parsed = parseExplain(JSON.stringify({ summary: 's', nodes }))

  expect(parsed?.nodes).toHaveLength(5)
  expect(parsed?.nodes[0]?.name.length).toBe(10)
  expect(parsed?.nodes[0]?.name.endsWith('…')).toBe(true)
})

test('a reply with no usable JSON is no explanation', () => {
  expect(parseExplain('sorry, I cannot')).toBeUndefined()
  expect(parseExplain('{not json}')).toBeUndefined()
  expect(parseExplain('{"summary": "", "nodes": []}')).toBeUndefined()
  expect(parseExplain('[1, 2]')).toBeUndefined()
})

test('line counts read in thousands past 999', () => {
  expect(count(999)).toBe('999')
  expect(count(1000)).toBe('1k')
  expect(count(1149)).toBe('1.1k')
  expect(count(12_400)).toBe('12k')
})
