import { expect, test } from 'claude-code/testing'

import { isContractCommand, markOf, parseContract } from './contract'

const CONTRACT = [
  '# mods: contract pane',
  '',
  '**Tag:** [FEAT]',
  '**Acceptance criteria:**',
  '- [ ] Parser reads the report → `claude plugin test ./mods`',
  '- [x] Lint is clean -> ruff check .',
  '- [ ] A wrapped criterion that runs',
  '  onto a second line → pytest -k wrapped',
  '- [ ] Seen by eye → observation in the pane',
  '**Out of scope:** nothing',
].join('\n')

const report = (extra: Record<string, unknown>) =>
  JSON.stringify({ branch: 'feat/x', contract: CONTRACT, evidence: null, notes: null, tree_matches_current: false, ...extra })

test('no archived contract reads as null', () => {
  expect(parseContract(JSON.stringify({ branch: 'feat/x', contract: null }))).toBeNull()
})

test('the title, tag and each criterion split at its arrow', () => {
  const contract = parseContract(report({}))

  expect(contract?.branch).toBe('feat/x')
  expect(contract?.title).toBe('mods: contract pane')
  expect(contract?.tag).toBe('[FEAT]')
  expect(contract?.criteria.map(criterion => [criterion.text, criterion.check, criterion.isChecked])).toEqual([
    ['Parser reads the report', '`claude plugin test ./mods`', false],
    ['Lint is clean', 'ruff check .', true],
    ['A wrapped criterion that runs onto a second line', 'pytest -k wrapped', false],
    ['Seen by eye', 'observation in the pane', false],
  ])
  expect(contract?.isEvidenceCurrent).toBe(false)
  expect(contract?.hasNotes).toBe(false)
})

test('a criterion takes the record its check names; the rest are listed apart', () => {
  const contract = parseContract(
    report({
      evidence: [
        { command: 'claude plugin test ./mods', exit_code: 1 },
        { command: 'ruff  check .', exit_code: 0 },
        { command: 'bash scripts/other.sh', exit_code: 0 },
        { command: 'pytest -k wrapped --maxfail=1', exit_code: 0 },
        { command: 'pytest', exit_code: 0 },
      ],
      notes: 'tried X\n',
      tree_matches_current: true,
    }),
  )

  if (contract === null) throw new Error('no contract')

  // A wider run (`--maxfail=1` added) or a narrower one (`pytest`) is not the check's own.
  expect(contract.criteria.map(criterion => markOf(contract, criterion))).toEqual(['fail', 'pass', 'none', 'none'])
  expect(contract.unnamed).toEqual([2, 3, 4])
  expect(contract.isEvidenceCurrent).toBe(true)
  expect(contract.hasNotes).toBe(true)
})

test('a rerun of the same command is the record that counts', () => {
  const contract = parseContract(
    report({
      evidence: [
        { command: 'claude plugin test ./mods', exit_code: 1 },
        { command: 'claude plugin test ./mods', exit_code: 0 },
      ],
    }),
  )

  if (contract === null) throw new Error('no contract')

  expect(markOf(contract, contract.criteria[0]!)).toBe('pass')
})

test('a check splits at the last arrow and keeps an arrow inside it verbatim', () => {
  const contract = parseContract(
    JSON.stringify({
      contract: [
        '**Acceptance criteria:**',
        "- [ ] Pipe a -> b works → python3 s.py --map 'a -> b'",
        '- [ ] Only ascii -> `make check`',
      ].join('\n'),
      evidence: [
        { command: "python3 s.py --map 'a -> b'", exit_code: 0 },
        { command: 'make check', exit_code: 1 },
      ],
    }),
  )

  if (contract === null) throw new Error('no contract')

  expect(contract.criteria.map(criterion => [criterion.text, criterion.check])).toEqual([
    ['Pipe a -> b works', "python3 s.py --map 'a -> b'"],
    ['Only ascii', '`make check`'],
  ])
  expect(contract.criteria.map(criterion => markOf(contract, criterion))).toEqual(['pass', 'fail'])
})

test('a contract saved with CRLF line endings reads the same', () => {
  const contract = parseContract(report({ contract: CONTRACT.replace(/\n/g, '\r\n') }))

  expect(contract?.criteria.map(criterion => criterion.check)).toEqual([
    '`claude plugin test ./mods`',
    'ruff check .',
    'pytest -k wrapped',
    'observation in the pane',
  ])
})

test('the state helper, its delimiters and a branch change reread the contract', () => {
  for (const command of [
    'python3 "$STATE" evidence --command x --exit 0',
    'python3 /a/cycle_state.py inspect',
    "python3 \"$STATE\" save <<'SPRINT_CONTRACT'",
    'git switch main',
    'git worktree add .worktrees/x feat/x',
    'git add -A',
    'git commit -m x',
    'git stash push -u -m tag',
    'bash scripts/commit-and-push.sh --pr',
  ]) {
    expect(isContractCommand(command)).toBe(true)
  }

  expect(isContractCommand('ls -la')).toBe(false)
  expect(isContractCommand('git status')).toBe(false)
})
