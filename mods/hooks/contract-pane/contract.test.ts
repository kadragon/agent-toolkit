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
      ],
      notes: 'tried X\n',
      tree_matches_current: true,
    }),
  )

  if (contract === null) throw new Error('no contract')

  expect(contract.criteria.map(criterion => markOf(contract, criterion))).toEqual(['fail', 'pass', 'pass', 'none'])
  expect(contract.unnamed).toEqual([2])
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

test('the state helper, its delimiters and a branch change reread the contract', () => {
  for (const command of [
    'python3 "$STATE" evidence --command x --exit 0',
    'python3 /a/cycle_state.py inspect',
    "python3 \"$STATE\" save <<'SPRINT_CONTRACT'",
    'git switch main',
    'git worktree add .worktrees/x feat/x',
  ]) {
    expect(isContractCommand(command)).toBe(true)
  }

  expect(isContractCommand('ls -la')).toBe(false)
  expect(isContractCommand('git status')).toBe(false)
})
