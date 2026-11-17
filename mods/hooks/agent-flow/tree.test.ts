import { expect, test } from 'claude-code/testing'
import type { AgentInfo } from 'claude-code'

import type { FlowAgent } from '../../types'
import {
  ASCII_FLOW,
  elapsedOf,
  elapsedText,
  fitRows,
  flowRows,
  mergeAgents,
  summaryText,
  tokensText,
  toFlowAgent,
  UNICODE_FLOW,
} from './tree'

const agent = (id: string, startTime: number, extra: Partial<FlowAgent> = {}): FlowAgent => ({
  id,
  type: 'Explore',
  description: `task ${id}`,
  status: 'running',
  startTime,
  tokens: 0,
  ...extra,
})

const info = (id: string, extra: Partial<AgentInfo> = {}): AgentInfo => ({
  id,
  description: `task ${id}`,
  type: 'general-purpose',
  status: 'running',
  kind: 'local_agent',
  taskStatus: 'running',
  label: `task ${id}`,
  startTime: 1000,
  cwd: '/work',
  tokenCount: 1200,
  tokenSamples: [],
  hasRow: true,
  ...extra,
})

test('children nest under their parent in start order; an unlisted parent leaves a root', () => {
  const rows = flowRows([
    agent('b', 20),
    agent('a', 10),
    agent('a2', 40, { parentId: 'a' }),
    agent('a1', 30, { parentId: 'a' }),
    agent('orphan', 5, { parentId: 'gone' }),
  ])

  expect(rows.map(row => `${row.depth}:${row.agent.id}`)).toEqual(['0:orphan', '0:a', '1:a1', '1:a2', '0:b'])
})

test('a parent cycle in a bad reading does not loop', () => {
  const rows = flowRows([agent('x', 1, { parentId: 'y' }), agent('y', 2, { parentId: 'x' })])

  expect(rows).toEqual([])
})

test('an agent keeps the first progress line that differs from its description', () => {
  expect(toFlowAgent(info('a', { label: '\n  reading cycle.md \nmore' })).label).toBe('reading cycle.md')
  expect(toFlowAgent(info('a')).label).toBeUndefined()
  expect(toFlowAgent(info('a', { parentId: 'p' })).parentId).toBe('p')
  expect('parentId' in toFlowAgent(info('a'))).toBe(false)
})

test('an agent seen ending is stamped once; one already ended when first seen is not', () => {
  const first = mergeAgents([], [info('a', { status: 'completed' }), info('b')], 5000)

  expect(first.map(one => one.endTime)).toEqual([undefined, undefined])

  const second = mergeAgents(first, [info('a', { status: 'completed' }), info('b', { status: 'failed' })], 9000)

  expect(second.map(one => one.endTime)).toEqual([undefined, 9000])

  const third = mergeAgents(second, [info('b', { status: 'failed' })], 13_000)

  expect(third[0]?.endTime).toBe(9000)
  expect(third[0] === undefined ? undefined : elapsedOf(third[0], 20_000)).toBe(8000)
  expect(second[0] === undefined ? 0 : elapsedOf(second[0], 20_000)).toBeUndefined()
  expect(elapsedOf(agent('r', 1000), 20_000)).toBe(19_000)
})

test('a tree taller than the pane drops finished agents first, then its earliest rows', () => {
  const rows = flowRows([
    agent('a', 1, { label: 'reading' }),
    agent('a1', 2, { parentId: 'a', status: 'completed' }),
    agent('b', 3, { status: 'completed' }),
    agent('c', 4, { label: 'writing' }),
  ])
  const ids = (room: number) => fitRows(rows, room).map(row => row.agent.id)

  expect(ids(6)).toEqual(['a', 'a1', 'b', 'c'])
  expect(ids(5)).toEqual(['a', 'b', 'c'])
  expect(ids(4)).toEqual(['a', 'c'])
  expect(ids(3)).toEqual(['c'])
})

test('elapsed time and tokens read short', () => {
  expect(elapsedText(-5)).toBe('0s')
  expect(elapsedText(59_999)).toBe('59s')
  expect(elapsedText(65_000)).toBe('1m05s')
  expect(elapsedText(3_660_000)).toBe('1h01m')
  expect(tokensText(999)).toBe('999')
  expect(tokensText(1250)).toBe('1.3k')
  expect(tokensText(9_999)).toBe('10k')
  expect(tokensText(45_600)).toBe('46k')
  expect(tokensText(999_600)).toBe('1.0M')
  expect(tokensText(2_340_000)).toBe('2.3M')
})

test('the summary counts running, done and failed agents', () => {
  const agents = [
    agent('a', 1),
    agent('b', 2, { status: 'waiting' }),
    agent('c', 3, { status: 'completed' }),
    agent('d', 4, { status: 'killed' }),
  ]

  expect(summaryText(agents, UNICODE_FLOW)).toBe('2 running · 1 done · 1 failed')
  expect(summaryText([agent('a', 1, { status: 'idle' })], ASCII_FLOW)).toBe('0 running | 1 done')
})
