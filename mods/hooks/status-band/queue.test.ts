import { describe, expect, test } from 'claude-code/testing'

import { isQueueCommand, parseCount, queueOf } from './queue'

describe('queue', () => {
  test('counts the candidate arrays, an empty print as none', () => {
    expect(parseCount('[{"title": "a"}, {"title": "b"}]')).toBe(2)
    expect(parseCount('')).toBe(0)
    expect(queueOf('[{}]', '[{}, {}, {}]')).toEqual({ groups: 1, parked: 3 })
  })
})

describe('isQueueCommand', () => {
  test("matches the queue's scripts, the backlog and the git moves that may change it", () => {
    expect(isQueueCommand('git checkout -b feat/x')).toBe(true)
    expect(isQueueCommand('git commit -m "[FIX] x"')).toBe(true)
    expect(isQueueCommand('git pull --ff-only')).toBe(true)
    expect(isQueueCommand('python3 task_nodes.py prune-backlog')).toBe(true)
    expect(isQueueCommand('BRANCH=$(printf x | python3 "$NODES" branch --title "t")')).toBe(true)
    expect(isQueueCommand('python3 "${CANDIDATES}" --backlog backlog.md')).toBe(true)
    expect(isQueueCommand('bash /p/scripts/merge-and-cleanup.sh 367')).toBe(true)
  })

  test('leaves an ordinary command alone', () => {
    expect(isQueueCommand('git status --porcelain')).toBe(false)
    expect(isQueueCommand('python3 -m pytest')).toBe(false)
    expect(isQueueCommand('ls mods')).toBe(false)
  })
})
