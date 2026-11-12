// Pure contract reading: what `cycle_state.py inspect` prints, parsed without `$`.

import type { Contract, ContractCriterion, ContractEvidence } from '../../types'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// The criteria section, as `cycle_state.py` bounds it: from the heading up to
// the next `**Field:**` line or heading, or the next criteria heading, so two
// sections never count one item twice; a wrapped item continues indented.
const CRITERIA_START = /^(?:\*\*Acceptance criteria(?::\*\*|\*\*:?)|#{1,6}\s+Acceptance criteria:?\s*$)/i
const FIELD = /^\*\*[^*]+:\*\*/
const CHECKBOX = /^\s*[-*+] \[([ xX])\]\s*(.*)$/
// The check follows the last arrow, whitespace before it: `→`, else the ASCII
// `->` cycle_state.py also takes, so an arrow inside a check stays verbatim
// where the contract uses `→` to start it.
const ARROWS = [/\s→\s*/g, /\s->\s*/g]

type Item = { text: string; isChecked: boolean }

const itemsOf = (contract: string): Item[] => {
  // As cycle_state.py's splitlines(): a CRLF contract reads the same.
  const lines = contract.split(/\r?\n/)
  const items: Item[] = []

  lines.forEach((line, index) => {
    if (!CRITERIA_START.test(line.trim())) return

    const section: Item[] = []

    for (const item of lines.slice(index + 1)) {
      if (FIELD.test(item.trim()) || item.startsWith('#') || CRITERIA_START.test(item.trim())) break

      const match = CHECKBOX.exec(item)
      const last = section[section.length - 1]

      if (match !== null) section.push({ text: match[2] ?? '', isChecked: match[1] !== ' ' })
      else if (last !== undefined && /^\s/.test(item) && item.trim() !== '') last.text += ` ${item.trim()}`
    }

    items.push(...section)
  })

  return items
}

// A command a check names, and the form a record's command is compared in.
type Named = { command: string; form: (text: string) => string }

// A backticked span is the command verbatim: whitespace inside it, quoted or
// not, is part of what ran. An unquoted check is prose that may have wrapped,
// so there backticks and runs of whitespace do not change the command.
const verbatim = (text: string): string => text.trim()
const collapsed = (text: string): string => text.replace(/`/g, '').replace(/\s+/g, ' ').trim()

// The commands a check names: each backticked span, else the whole check.
const commandsOf = (check: string): Named[] => {
  const spans = Array.from(check.matchAll(/`([^`]+)`/g), match => match[1] ?? '')
  const form = spans.length > 0 ? verbatim : collapsed

  return (spans.length > 0 ? spans : [check])
    .map(text => ({ command: form(text), form }))
    .filter(named => named.command !== '')
}

// The record of one command: the one whose command is exactly it. A narrower
// or wider run is another check, never this one's proof. The last record
// wins, as a rerun replaces its own.
const recordOf = ({ command, form }: Named, evidence: readonly ContractEvidence[]): number | undefined => {
  for (let index = evidence.length - 1; index >= 0; index -= 1) {
    if (form(evidence[index]?.command ?? '') === command) return index
  }

  return undefined
}

// The criterion's text and its check, split at the last arrow.
const splitAtArrow = (text: string): [string, string] => {
  for (const arrow of ARROWS) {
    const last = Array.from(text.matchAll(arrow)).pop()

    if (last?.index !== undefined) return [text.slice(0, last.index), text.slice(last.index + last[0].length)]
  }

  return [text, '']
}

const criterionOf = (item: Item, evidence: readonly ContractEvidence[]): ContractCriterion => {
  const [text, rest] = splitAtArrow(item.text)
  const check = rest.trim()
  const found = commandsOf(check).map(named => recordOf(named, evidence))
  const records = found.filter((index): index is number => index !== undefined)

  return {
    text: text.trim(),
    check,
    isChecked: item.isChecked,
    evidence: records,
    missing: found.length - records.length,
  }
}

const evidenceOf = (value: unknown): ContractEvidence[] =>
  Array.isArray(value)
    ? value.filter(isRecord).map(record => ({
        command: typeof record.command === 'string' ? record.command : '',
        exitCode: typeof record.exit_code === 'number' ? record.exit_code : -1,
      }))
    : []

// What `cycle_state.py inspect` printed: null when the branch has no contract.
export const parseContract = (stdout: string): Contract | null => {
  const report: unknown = JSON.parse(stdout)

  if (!isRecord(report) || typeof report.contract !== 'string') return null

  const contract = report.contract
  const evidence = evidenceOf(report.evidence)
  const criteria = itemsOf(contract).map(item => criterionOf(item, evidence))
  const named = new Set(criteria.flatMap(criterion => criterion.evidence))

  return {
    branch: typeof report.branch === 'string' ? report.branch : '',
    title: /^#\s+(.+?)\s*$/m.exec(contract)?.[1],
    tag: /^\*\*Tag:\*\*\s*(\[[A-Z]+\])/m.exec(contract)?.[1],
    criteria,
    evidence,
    unnamed: evidence.flatMap((_, index) => (named.has(index) ? [] : [index])),
    isEvidenceCurrent: report.tree_matches_current === true,
    hasNotes: typeof report.notes === 'string' && report.notes.trim() !== '',
  }
}

export type Mark = 'pass' | 'fail' | 'none'

// A criterion's mark: failed when any command it names failed; passed only
// when every one it names has a passing record; else none.
export const markOf = (contract: Contract, criterion: ContractCriterion): Mark => {
  const results = criterion.evidence.map(index => contract.evidence[index]?.exitCode)

  if (results.some(code => code !== 0)) return 'fail'

  return results.length > 0 && criterion.missing === 0 ? 'pass' : 'none'
}

// A Bash command after which the contract, its evidence, the branch or the
// index the evidence is matched against may have moved: the state helper, its
// delimiters, a branch change, or a command that writes the index.
const CONTRACT_COMMAND =
  /cycle_state\.py|\$\{?STATE\b|SPRINT_CONTRACT|STUCK_NOTE|task_nodes\.py|commit-and-push\.sh|merge-and-cleanup\.sh|\bgit\b[^\n|;&]*\b(checkout|switch|merge|worktree|add|rm|mv|commit|stash|reset|restore|rebase|cherry-pick|pull)\b/

export const isContractCommand = (command: string): boolean => CONTRACT_COMMAND.test(command)
