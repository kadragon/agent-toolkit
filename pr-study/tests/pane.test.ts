import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

const NOTES = JSON.stringify({
  summary: '복습 스케줄러를 FSRS로 교체',
  points: [{ title: 'FSRS 스케줄링', file: 'quiz_state.py', why: '간격 계산이 바뀐다', level: 2 }],
  questions: ['SM-2 fallback은 언제 쓰이나?'],
  review: [],
})

function stubHost(on: On, diffOf: () => string, prompts: string[], reply = NOTES) {
  on('ui.open', () => ({ value: { isOpen: true } }) as never)
  on('command.register', () => ({ value: undefined }) as never)
  on('fs.read', () => ({ deny: 'no repo-quiz history' }))
  on('turn.complete', () => ({ text: '' }))
  on('process.run', (_$, e) => {
    const args = e.argv.slice(1).join(' ')
    const diff = diffOf()
    if (args.startsWith('merge-base')) return { value: { exitCode: 0, stdout: 'abc1234def\n', stderr: '' } } as never
    if (args.startsWith('diff --numstat')) return { value: { exitCode: 0, stdout: diff ? '7\t2\ta.py' : '', stderr: '' } } as never
    if (args.startsWith('rev-parse')) return { value: { exitCode: 0, stdout: 'feat/x\n', stderr: '' } } as never
    return { value: { exitCode: 0, stdout: diff, stderr: '' } } as never
  })
  on('model.complete', (_$, e) => {
    prompts.push(e.prompt)
    return { value: { isAnswered: true, text: reply, usage: { input_tokens: 1, output_tokens: 1 } } } as never
  })
}

const PROPS = { title: 'PR 공부', isFocused: false, bodyColumns: 60, placement: 'dock' }

// refresh() runs unawaited, so poll the drawn pane until it shows the expected text.
async function drawnWith($: Engine, surface: 'terminal' | 'desktop', needle: string) {
  let last = ''
  for (let i = 0; i < 50; i++) {
    const ui = await $.ui.mount({ plugin: 'pr-study', surface, component: 'Pane', requestId: 'pr-study', props: PROPS } as never)
    last = JSON.stringify(await ui.drawn())
    await ui.unmount()
    if (last.includes(needle)) return last
  }
  throw new Error(`pane never showed ${needle}: ${last.slice(0, 300)}`)
}

// Lets unawaited refresh work run so a "nothing happened" assertion is meaningful.
async function drain($: Engine, surface: 'terminal' | 'desktop') {
  for (let i = 0; i < 20; i++) await drawnWith($, surface, '')
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`${surface}: /pr-study turns the branch diff into notes drawn in the pane`, async ($, on) => {
    const prompts: string[] = []
    stubHost(on, () => 'diff --git a/a.py b/a.py\n-x\n+y', prompts)

    await $.command.run({ command: 'pr-study' } as never)
    await drawnWith($, surface, 'FSRS')

    expect(prompts[0]).toContain('+y')
  })

  test(`${surface}: no diff against main skips the model call`, async ($, on) => {
    const prompts: string[] = []
    stubHost(on, () => '', prompts)

    await $.command.run({ command: 'pr-study' } as never)
    await drawnWith($, surface, '변경점 없음')

    expect(prompts.length).toBe(0)
  })

  test(`${surface}: a main-loop turn re-generates only when the diff changed; subagent turns never do`, async ($, on) => {
    const prompts: string[] = []
    let diff = 'diff --git a/a.py b/a.py\n+one'
    stubHost(on, () => diff, prompts)
    const turn = (extra: object) =>
      $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer', ...extra } as never)

    await turn({})
    await drawnWith($, surface, 'FSRS')
    await turn({})
    await drain($, surface)
    expect(prompts.length).toBe(1)

    diff += '\n+two'
    await turn({ agentId: 'sub-1' })
    await drain($, surface)
    expect(prompts.length).toBe(1)

    await turn({})
    for (let i = 0; i < 50 && prompts.length < 2; i++) await drain($, surface)
    expect(prompts.length).toBe(2)
    expect(prompts[1]).toContain('+two')
  })

  test(`${surface}: the pane draws file bars and ticks a self-check question on press`, async ($, on) => {
    stubHost(on, () => 'diff --git a/a.py b/a.py\n+y', [])

    await $.command.run({ command: 'pr-study' } as never)
    const drawn = await drawnWith($, surface, 'FSRS')
    expect(drawn).toContain('"+","7"')
    expect(drawn).toContain('█')
    expect(drawn).toContain('feat/x')

    const ui = await $.ui.mount({ plugin: 'pr-study', surface, component: 'Pane', requestId: 'pr-study', props: PROPS } as never)
    await ui.press({ key: 'q0' })
    await ui.unmount()
    await drawnWith($, surface, '☑')
  })

  test(`${surface}: a non-JSON reply falls back to markdown`, async ($, on) => {
    stubHost(on, () => 'diff --git a/a.py b/a.py\n+y', [], '## 그냥 마크다운 노트')

    await $.command.run({ command: 'pr-study' } as never)
    await drawnWith($, surface, '그냥 마크다운 노트')
  })
}
