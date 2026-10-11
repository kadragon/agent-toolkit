import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

const ANSWER = 'I changed the parser and left the tests alone. '.repeat(4)
const USAGE = {
  input_tokens: 1,
  output_tokens: 1,
  cache_read_input_tokens: 0,
  cache_creation_input_tokens: 0,
}
const BAND = {
  plugin: 'mods',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 20,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 19 },
    view: {},
  },
} as const

type Reply = { text: string } | { reason: 'empty-reply' } | { deny: string }
type World = { modelCalls: string[]; fills: string[]; submits: string[] }

// The engine beneath the plugin: what the model, the turn, the box and the
// band answer when no plugin does.
const world = (on: On, answer: Reply | (() => Reply)): World => {
  const seen: World = { modelCalls: [], fills: [], submits: [] }

  on('model.complete', async ($, e) => {
    seen.modelCalls.push(e.model)
    const reply = typeof answer === 'function' ? answer() : answer

    if ('deny' in reply) return { deny: reply.deny }
    if ('reason' in reply) {
      return { value: { isAnswered: false, reason: reply.reason, usage: USAGE } }
    }

    return { value: { isAnswered: true, text: reply.text, usage: USAGE } }
  })
  on('turn.complete', async ($, e) => ({ text: e.answer }))
  on('prompt.fill', async ($, e) => {
    seen.fills.push(e.text)

    return { isFilled: true }
  })
  on('prompt.submit', async ($, e) => {
    seen.submits.push(e.text)

    return { text: e.text }
  })
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => {
    const { Box } = $.ui.resolve(e)

    return <Box key="engine-empty" />
  })

  return seen
}

const endTurn = ($: Engine, fields: Record<string, unknown> = {}) =>
  $.turn.complete({
    answer: ANSWER,
    durationMs: 10,
    isAborted: false,
    turnId: 't1',
    reason: 'answer',
    ...fields,
  } as Parameters<Engine['turn']['complete']>[0])

const buttons = async ($: Engine) => {
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  const found = []

  for (const key of ['next-step-1', 'next-step-2', 'next-step-3', 'next-step-4']) {
    const button = await ui.find({ key })

    if (button !== undefined) found.push(button.props.label)
  }

  return { ui, labels: found }
}

test('an eligible turn asks the model once and shows at most three', async ($, on) => {
  const seen = world(on, { text: 'Run the tests\nReview the diff\nCommit it\nA fourth' })

  const result = await endTurn($)
  const { ui, labels } = await buttons($)

  expect(result.text).toBe(ANSWER)
  expect(seen.modelCalls).toEqual(['haiku'])
  expect(labels).toEqual(['Run the tests', 'Review the diff', 'Commit it'])
  await ui.unmount()
})

test('the band draws on the desktop surface too', async ($, on) => {
  world(on, { text: 'Run the tests' })

  await endTurn($)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })

  expect((await ui.find({ key: 'next-step-1' }))?.props.label).toBe('Run the tests')
  await ui.unmount()
})

test('a turn that is not a full main-loop answer makes no model call', async ($, on) => {
  const seen = world(on, { text: 'Run the tests' })

  await endTurn($, { answer: 'Done.' })
  await endTurn($, { reason: 'aborted', isAborted: true })
  await endTurn($, { reason: 'error' })
  await endTurn($, {
    reason: 'refusal',
    refusal: { category: null, explanation: null },
  })
  await endTurn($, { agentId: 'agent-1' })
  const { ui, labels } = await buttons($)

  expect(seen.modelCalls).toEqual([])
  expect(labels).toEqual([])
  await ui.unmount()
})

test('pressing a suggestion fills the draft and submits nothing', async ($, on) => {
  const seen = world(on, { text: 'Run the tests\nReview the diff' })

  await endTurn($)
  const { ui } = await buttons($)
  await ui.press({ key: 'next-step-2' })

  expect(seen.fills).toEqual(['Review the diff'])
  expect(seen.submits).toEqual([])
  expect(await ui.find({ key: 'next-step-1' })).toBeUndefined()
  await ui.unmount()
})

test('0 dismisses the band without touching the draft', async ($, on) => {
  const seen = world(on, { text: 'Run the tests' })

  await endTurn($)
  const { ui } = await buttons($)

  expect((await ui.find({ key: 'next-step-dismiss' }))?.props.hotkey).toBe('0')
  await ui.press({ key: 'next-step-dismiss' })

  expect(await ui.find({ key: 'next-step-1' })).toBeUndefined()
  expect(seen.fills).toEqual([])
  await ui.unmount()
})

test('a new prompt clears the last suggestions', async ($, on) => {
  world(on, { text: 'Run the tests' })

  await endTurn($)
  await $.prompt.submit({ text: 'something else', wait: false, origin: { kind: 'composer' } })
  const { ui, labels } = await buttons($)

  expect(labels).toEqual([])
  await ui.unmount()
})

test('switched off, it makes no model call and draws nothing', { options: { nextStepsEnabled: false } }, async ($, on) => {
  const seen = world(on, { text: 'Run the tests' })

  await endTurn($)
  const { ui, labels } = await buttons($)

  expect(seen.modelCalls).toEqual([])
  expect(labels).toEqual([])
  await ui.unmount()
})

test('the model option picks who writes the suggestions', { options: { nextStepsModel: 'sonnet' } }, async ($, on) => {
  const seen = world(on, { text: 'Run the tests' })

  await endTurn($)

  expect(seen.modelCalls).toEqual(['sonnet'])
})

test('a failed model call leaves the turn as it was and drops the stale band', async ($, on) => {
  let reply: Reply = { text: 'Run the tests' }
  world(on, () => reply)

  await endTurn($)
  reply = { deny: 'provider down' }
  const result = await endTurn($, { turnId: 't2' })
  const { ui, labels } = await buttons($)

  expect(result.text).toBe(ANSWER)
  expect(labels).toEqual([])
  await ui.unmount()
})

test('a reply with nothing to suggest leaves the band empty', async ($, on) => {
  world(on, { text: 'NONE' })

  await endTurn($)
  const { ui, labels } = await buttons($)

  expect(labels).toEqual([])
  await ui.unmount()
})

test('a reply the model left without text leaves the band empty', async ($, on) => {
  world(on, { reason: 'empty-reply' })

  const result = await endTurn($)
  const { ui, labels } = await buttons($)

  expect(result.text).toBe(ANSWER)
  expect(labels).toEqual([])
  await ui.unmount()
})
