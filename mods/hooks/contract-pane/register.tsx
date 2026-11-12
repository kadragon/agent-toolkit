import { atom, read, update } from 'claude-code'
import type { Elements, EngineInterface, Register, RenderElement } from 'claude-code'

import type { ContractPane } from '../../types'
import { under } from '../status-band/count'
import { isFeatureBranch } from '../status-band/cycle'
import { readDevRoot } from '../status-band/register'
import { isContractCommand, markOf, parseContract } from './contract'
import type { Mark } from './contract'

// The branch's Sprint Contract, drawn on top of the PR recap pane: each
// acceptance criterion with the recorded validation run its check names, read
// off the dev plugin's own state helper. Read when the pane boots and again
// after a command of the cycle's own; with no contract it folds to one line.
const LABEL = 'Sprint Contract'
const CYCLE_SCRIPT = 'skills/task-next/scripts/cycle_state.py'
const GIT_TIMEOUT_MS = 2000
const READ_TIMEOUT_MS = 20_000
const MARKS: Record<Mark, { glyph: string; color?: 'success' | 'error' }> = {
  pass: { glyph: '✓', color: 'success' },
  fail: { glyph: '✗', color: 'error' },
  none: { glyph: '·' },
}

const paneAtom = atom({ plugin: 'mods', key: 'contractPane' } as const, null, { shape: 'contract-pane-1' })

// What the module keeps between hooks; a reload starts it over. `isActive`
// turns on with the first read, which the pane's boot asks for: until then a
// cycle command has no section to refresh.
const live = { isEnabled: false, isActive: false }

async function readOnce($: EngineInterface): Promise<ContractPane> {
  const readAt = await $.clock.now()
  const branch = await $.process
    .run(['git', 'branch', '--show-current'], { timeoutMs: GIT_TIMEOUT_MS })
    .then(run => (run.exitCode === 0 ? run.stdout.trim() : undefined))
    .catch(() => undefined)

  if (branch === undefined) return { contract: null, readAt, reason: 'git 저장소 아님' }
  if (branch === '') return { contract: null, readAt, reason: 'detached HEAD' }
  if (!isFeatureBranch(branch)) return { contract: null, readAt, reason: `없음 (${branch})` }

  const root = await readDevRoot($).catch(() => undefined)

  if (root === undefined) return { contract: null, readAt, reason: 'dev 플러그인 꺼짐' }

  const inspect = await $.process
    .run(['python3', under(root, CYCLE_SCRIPT), 'inspect'], { timeoutMs: READ_TIMEOUT_MS })
    .catch(() => $.process.run(['python', under(root, CYCLE_SCRIPT), 'inspect'], { timeoutMs: READ_TIMEOUT_MS }))

  // A failed or cut read is an error, not a reading: the contract before it stays.
  if (inspect.exitCode !== 0) throw new Error('cycle_state.py inspect 실패')
  if (inspect.isStdoutTruncated) throw new Error('cycle_state.py inspect 출력이 잘림')

  return { contract: parseContract(inspect.stdout), readAt }
}

let loading: Promise<void> | undefined
// A read asked for while one runs: that one may have started before the
// contract moved, so one more follows it.
let isStale = false

// Reads the section again; the PR recap pane's boot calls it first. A function
// declaration: the pane's file calls it with `$` past an import.
export function loadContract($: EngineInterface): Promise<void> {
  if (!live.isEnabled) return Promise.resolve()

  live.isActive = true
  if (loading !== undefined) {
    isStale = true

    return loading
  }

  loading = (async () => {
    do {
      isStale = false

      const next = await readOnce($).catch((error: unknown) => (error instanceof Error ? error.message : String(error)))

      // A reread that failed keeps the contract shown, with the error beside it.
      await update($, paneAtom, current =>
        typeof next !== 'string'
          ? next
          : current?.contract
            ? { ...current, error: next }
            : { contract: null, readAt: current?.readAt ?? 0, reason: next },
      )
    } while (isStale)
  })().finally(() => {
    loading = undefined
  })

  return loading
}

// The section the PR recap pane draws on top, or null when switched off.
export async function contractSection(
  $: EngineInterface,
  elements: Pick<Elements['terminal'], 'Box' | 'Button' | 'Text'>,
): Promise<RenderElement | null> {
  if (!live.isEnabled) return null

  const { Box, Button, Text } = elements
  const pane = await read($, paneAtom)

  if (pane === null) return <Text dimColor>{LABEL} · 읽는 중…</Text>

  const contract = pane.contract

  if (contract === null) {
    return (
      <Text dimColor wrap="truncate-end">
        {LABEL} · {pane.reason ?? '저장된 계약 없음'}
      </Text>
    )
  }

  const marks = contract.criteria.map(criterion => markOf(contract, criterion))
  const tally = (mark: Mark) => String(marks.filter(each => each === mark).length)
  const records = contract.evidence.length

  return (
    <Box flexDirection="column">
      <Text bold wrap="wrap">
        {contract.tag === undefined ? '' : `${contract.tag} `}
        {contract.title ?? contract.branch}
      </Text>
      <Text dimColor wrap="truncate-end">
        기준 {String(contract.criteria.length)}개 · 통과 {tally('pass')} · 실패 {tally('fail')} · 미확인 {tally('none')}
      </Text>
      {records === 0 ? (
        <Text dimColor>기록된 검증 실행 없음</Text>
      ) : contract.isEvidenceCurrent ? (
        <Text color="success">검증 {String(records)}건 · 현재 트리와 일치</Text>
      ) : (
        <Text color="warning">검증 {String(records)}건 · 트리가 바뀜, 다시 실행 필요</Text>
      )}
      {contract.hasNotes && <Text color="warning">⚑ 막힌 기록 있음 (cycle_state.py inspect)</Text>}
      {pane.error !== undefined && <Text color="error">다시 읽기 실패: {pane.error}</Text>}
      <Box flexDirection="column" marginTop={1}>
        {contract.criteria.map((criterion, index) => {
          const mark = MARKS[marks[index] ?? 'none']

          return (
            <Box key={`criterion-${index}`} flexDirection="column">
              <Text wrap="wrap">
                {mark.color === undefined ? <Text dimColor>{mark.glyph}</Text> : <Text color={mark.color}>{mark.glyph}</Text>}{' '}
                {criterion.text}
              </Text>
              {criterion.check !== '' && (
                <Text dimColor wrap="truncate-end">
                  {'  → '}
                  {criterion.check}
                </Text>
              )}
            </Box>
          )
        })}
      </Box>
      {contract.unnamed.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text dimColor>기준에 이어지지 않은 실행</Text>
          {contract.unnamed.map(index => {
            const record = contract.evidence[index]

            if (record === undefined) return null

            return (
              <Text key={`record-${index}`} wrap="truncate-end">
                {record.exitCode === 0 ? <Text color="success">✓</Text> : <Text color="error">✗</Text>} {record.command}
              </Text>
            )
          })}
        </Box>
      )}
      <Box>
        <Button key="reload" hotkey="r" plain onPress={() => void loadContract($).catch(() => undefined)}>
          계약 다시 읽기
        </Button>
      </Box>
    </Box>
  )
}

export const register: Register = (on, options) => {
  // The section rides on the PR recap pane: no pane, nothing to draw.
  live.isEnabled = options.contractPaneEnabled !== false && options.prRecapEnabled !== false
  if (!live.isEnabled) return

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)

    if (live.isActive && isContractCommand(e.command)) void loadContract($).catch(() => undefined)

    return ran
  })
}
