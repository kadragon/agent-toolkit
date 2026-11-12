import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { ContractPane } from '../../types'
import { under } from '../status-band/count'
import { isFeatureBranch } from '../status-band/cycle'
import { python, readDevRoot } from '../status-band/register'
import { isContractCommand, markOf, parseContract } from './contract'
import type { Mark } from './contract'

// The branch's Sprint Contract: each acceptance criterion with the recorded
// validation run its check names, read off the dev plugin's own state helper.
// Opened by /contract; read again after a command of the cycle's own.
export const PANE = 'contract'
const TITLE = 'Sprint Contract'
const COMMAND = 'contract'
const CYCLE_SCRIPT = 'skills/task-next/scripts/cycle_state.py'
const GIT_TIMEOUT_MS = 2000
const READ_TIMEOUT_MS = 20_000
const MARKS: Record<Mark, { glyph: string; color?: 'success' | 'error' }> = {
  pass: { glyph: '✓', color: 'success' },
  fail: { glyph: '✗', color: 'error' },
  none: { glyph: '·' },
}

const paneAtom = atom({ plugin: 'mods', key: 'contractPane' } as const, null, { shape: 'contract-pane-1' })

// What the module keeps between hooks; a reload starts it over.
const live = { isEnabled: false, isRegistered: false }

async function readOnce($: EngineInterface): Promise<ContractPane> {
  const readAt = await $.clock.now()
  const branch = await $.process
    .run(['git', 'branch', '--show-current'], { timeoutMs: GIT_TIMEOUT_MS })
    .then(run => (run.exitCode === 0 ? run.stdout.trim() : undefined))
    .catch(() => undefined)

  if (branch === undefined) return { contract: null, readAt, reason: 'git 저장소가 아닙니다.' }
  if (!isFeatureBranch(branch)) {
    return { contract: null, readAt, reason: `기본 브랜치${branch === '' ? '' : ` (${branch})`}에는 계약이 없습니다.` }
  }

  const root = await readDevRoot($).catch(() => undefined)

  if (root === undefined) return { contract: null, readAt, reason: 'dev 플러그인이 켜져 있지 않습니다.' }

  const inspect = await python($, [under(root, CYCLE_SCRIPT), 'inspect'], { timeoutMs: READ_TIMEOUT_MS })

  if (inspect.exitCode !== 0) return { contract: null, readAt, reason: 'cycle_state.py inspect가 실패했습니다.' }

  return { contract: parseContract(inspect.stdout), readAt }
}

let loading: Promise<void> | undefined
// A read asked for while one runs: that one may have started before the
// contract moved, so one more follows it.
let isStale = false

function load($: EngineInterface): Promise<void> {
  if (loading !== undefined) {
    isStale = true

    return loading
  }

  loading = (async () => {
    do {
      isStale = false

      const next = await readOnce($).catch(async error => ({
        contract: null,
        readAt: await $.clock.now(),
        reason: String(error),
      }))

      await update($, paneAtom, () => next)
    } while (isStale)
  })().finally(() => {
    loading = undefined
  })

  return loading
}

// The first band drawing registers /contract: the plugin's one session.start
// hook belongs to the status band. It runs after the drawing, since a render
// may not register; a registration that failed is tried on the next drawing.
export function noteContractBand($: EngineInterface): void {
  if (!live.isEnabled || live.isRegistered) return

  live.isRegistered = true
  void $.clock
    .sleep(0)
    .then(() => $.command.register({ name: COMMAND, description: "Show this branch's Sprint Contract in a side pane" }))
    .catch(() => {
      live.isRegistered = false
    })
}

export const register: Register = (on, options) => {
  live.isEnabled = options.contractPaneEnabled !== false
  if (!live.isEnabled) return

  on('command.run', { command: COMMAND }, async $ => {
    await load($)
    await $.ui.open({ id: PANE, title: TITLE })

    return { text: 'Sprint Contract pane opened.' }
  })

  // Only an open pane is read again: a closed one reads when /contract opens it.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)

    if (isContractCommand(e.command)) {
      void $.ui
        .panes()
        .then(panes => (panes.some(pane => pane.id === PANE) ? load($) : undefined))
        .catch(() => undefined)
    }

    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const pane = await read($, paneAtom)

    if (pane === null) return <Text dimColor>계약을 읽는 중…</Text>

    const contract = pane.contract

    if (contract === null) {
      return (
        <Text dimColor wrap="wrap">
          {pane.reason ?? '이 브랜치에 저장된 Sprint Contract가 없습니다.'}
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
        <Box marginTop={1}>
          <Button key="reload" hotkey="r" plain onPress={() => load($)}>
            다시 읽기
          </Button>
          {!e.props.isFocused && <Text dimColor> (포커스 후 r)</Text>}
        </Box>
      </Box>
    )
  })
}
