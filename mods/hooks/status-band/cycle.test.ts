import { describe, expect, test } from 'claude-code/testing'

import {
  ciSettled,
  isCycleCommand,
  isFeatureBranch,
  parseCiStatus,
  parseCount,
  parseInspect,
  parsePr,
  parseStrikes,
  queueOf,
} from './cycle'

const CONTRACT = `# Status band cycle rows
**Tag:** [FEAT]
**Scope:** mods/hooks/status-band
**Acceptance criteria:**
- [ ] the cycle row draws → claude plugin test ./mods
- [x] the queue row draws → claude plugin test ./mods
- [ ] a wrapped criterion
  continues here → tsc -p mods
**Out of scope:** panes
`

const inspect = (fields: Record<string, unknown>): string =>
  JSON.stringify({
    branch: 'feat/x',
    head: 'abc',
    changes: '',
    contract_path: '/g/.git/task-cycle/feat-x/contract.md',
    contract: CONTRACT,
    evidence_path: '/g/.git/task-cycle/feat-x/evidence.json',
    evidence: null,
    notes: null,
    tree_matches_current: false,
    ...fields,
  })

describe('parseInspect', () => {
  test('reads the tag, the heading, the criteria and no evidence', () => {
    expect(parseInspect(inspect({}))).toEqual({
      tag: '[FEAT]',
      title: 'Status band cycle rows',
      criteria: 3,
      evidence: 0,
      isEvidenceCurrent: false,
      hasNotes: false,
    })
  })

  test('counts the evidence records and whether their tree is current', () => {
    const report = inspect({
      evidence: [{ command: 'a', exit: 0 }, { command: 'b', exit: 1 }],
      tree_matches_current: true,
      notes: 'tried X\n',
    })

    expect(parseInspect(report)).toMatchObject({ evidence: 2, isEvidenceCurrent: true, hasNotes: true })
  })

  test('is null where no contract is archived', () => {
    expect(parseInspect(inspect({ contract: null }))).toBeNull()
  })

  test('leaves out a tag or heading the contract has none of', () => {
    const report = inspect({ contract: '**Acceptance criteria:**\n- [ ] one → t\n' })

    expect(parseInspect(report)).toMatchObject({ tag: undefined, title: undefined, criteria: 1 })
  })
})

describe('hub readings', () => {
  test('reads the PR number, or takes it off the URL', () => {
    expect(parsePr('{"pr_number": 367, "pr_url": "https://github.com/o/r/pull/367"}')).toBe(367)
    expect(parsePr('{"pr_number": null, "pr_url": "https://github.com/o/r/pull/368/"}')).toBe(368)
    expect(parsePr('{"pr_number": null, "pr_url": null}')).toBeUndefined()
  })

  test('reads a CI status and takes an unknown one as none', () => {
    expect(parseCiStatus('{"status": "pending", "checks": 3}')).toBe('pending')
    expect(parseCiStatus('{"status": "success", "checks": 3}')).toBe('success')
    expect(parseCiStatus('{"status": "failure", "checks": 3}')).toBe('failure')
    expect(parseCiStatus('{"status": "weird"}')).toBe('none')
  })

  test('reads the strike file as ci-wait does: missing or odd is none', () => {
    expect(parseStrikes('2\n')).toBe(2)
    expect(parseStrikes(undefined)).toBe(0)
    expect(parseStrikes('nope')).toBe(0)
  })

  test('a toast is due once a pending run settles, not on a repeat reading', () => {
    expect(ciSettled('pending', 'success')).toBe(true)
    expect(ciSettled('pending', 'failure')).toBe(true)
    expect(ciSettled('pending', 'pending')).toBe(false)
    expect(ciSettled('success', 'success')).toBe(false)
    expect(ciSettled(undefined, 'success')).toBe(false)
  })
})

describe('queue', () => {
  test('counts the candidate arrays, an empty print as none', () => {
    expect(parseCount('[{"title": "a"}, {"title": "b"}]')).toBe(2)
    expect(parseCount('')).toBe(0)
    expect(queueOf('[{}]', '[{}, {}, {}]')).toEqual({ groups: 1, parked: 3 })
  })
})

describe('isFeatureBranch', () => {
  test('holds off the base branches and a detached head', () => {
    expect(isFeatureBranch('feat/x')).toBe(true)
    expect(isFeatureBranch('main')).toBe(false)
    expect(isFeatureBranch('master')).toBe(false)
    expect(isFeatureBranch('')).toBe(false)
    expect(isFeatureBranch(undefined)).toBe(false)
  })
})

describe('isCycleCommand', () => {
  test("matches the cycle's scripts and the git moves between its steps", () => {
    expect(isCycleCommand('python3 "$STATE" save <<\'SPRINT_CONTRACT\'')).toBe(true)
    expect(isCycleCommand('bash /p/scripts/ci-wait.sh 367')).toBe(true)
    expect(isCycleCommand('git checkout -b feat/x')).toBe(true)
    expect(isCycleCommand('git commit -m "[FIX] x"')).toBe(true)
    expect(isCycleCommand('python3 task_nodes.py prune-backlog')).toBe(true)
    expect(isCycleCommand('BRANCH=$(printf x | python3 "$NODES" branch --title "t")')).toBe(true)
    expect(isCycleCommand('python3 "${CANDIDATES}" --backlog backlog.md')).toBe(true)
  })

  test('leaves an ordinary command alone', () => {
    expect(isCycleCommand('git status --porcelain')).toBe(false)
    expect(isCycleCommand('python3 -m pytest')).toBe(false)
    expect(isCycleCommand('ls mods')).toBe(false)
  })
})
