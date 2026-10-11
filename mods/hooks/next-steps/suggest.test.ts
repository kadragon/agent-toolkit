import { describe, expect, test } from 'claude-code/testing'

import { buildPrompt, isEligible, MIN_ANSWER_CHARS, parseSuggestions } from './suggest'

const LONG = 'x'.repeat(MIN_ANSWER_CHARS)

describe('isEligible', () => {
  test('takes a main-loop answer of the minimum length', () => {
    expect(isEligible({ answer: LONG, reason: 'answer' })).toBe(true)
  })

  test('skips an answer one character short, padding not counted', () => {
    expect(isEligible({ answer: ` ${LONG.slice(1)} `, reason: 'answer' })).toBe(false)
  })

  test('skips a turn that did not end in an answer', () => {
    for (const reason of ['aborted', 'refusal', 'error'] as const) {
      expect(isEligible({ answer: LONG, reason })).toBe(false)
    }
  })

  test("skips a subagent's turn", () => {
    expect(isEligible({ answer: LONG, reason: 'answer', agentId: 'a1' })).toBe(false)
  })
})

describe('parseSuggestions', () => {
  test('strips list markers and quotes', () => {
    expect(parseSuggestions('1. Run the tests\n- "Review the diff"\n* Commit it')).toEqual([
      'Run the tests',
      'Review the diff',
      'Commit it',
    ])
  })

  test('keeps the first three, without blanks or repeats', () => {
    expect(parseSuggestions('a\n\na\nb\nc\nd')).toEqual(['a', 'b', 'c'])
  })

  test('reads NONE and an empty reply as nothing to suggest', () => {
    expect(parseSuggestions('NONE')).toEqual([])
    expect(parseSuggestions('')).toEqual([])
  })

  test('drops a line too long to be a prompt', () => {
    expect(parseSuggestions(`${'y'.repeat(121)}\nok`)).toEqual(['ok'])
  })
})

describe('buildPrompt', () => {
  test('carries both sides of the exchange', () => {
    const prompt = buildPrompt('fix the bug', 'I fixed it.')

    expect(prompt).toContain('fix the bug')
    expect(prompt).toContain('I fixed it.')
  })

  test('keeps the end of an answer longer than the context cap', () => {
    const prompt = buildPrompt('q', `HEAD${'z'.repeat(5000)}TAIL`)

    expect(prompt).toContain('TAIL')
    expect(prompt).not.toContain('HEAD')
  })
})
