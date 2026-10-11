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
type World = {
  modelCalls: string[]
  prompts: string[]
  fills: { text: string; mode: string }[]
  submits: string[]
  toasts: string[]
}
type Setup = {
  reply: Reply | (() => Reply)
  surfaces?: readonly ('terminal' | 'desktop' | 'vscode' | 'mobile')[]
  isFilled?: boolean
}

// The engine beneath the plugin: what the model, the turn, the box, the band
// and the session answer when no plugin does.
const world = (on: On, setup: Setup): World => {
  const seen: World = { modelCalls: [], prompts: [], fills: [], submits: [], toasts: [] }

  on('model.complete', async ($, e) => {
    seen.modelCalls.push(e.model)
    seen.prompts.push(e.prompt)
    const reply = typeof setup.reply === 'function' ? setup.reply() : setup.reply

    if ('deny' in reply) return { deny: reply.deny }
    if ('reason' in reply) {
      return { value: { isAnswered: false, reason: reply.reason, usage: USAGE } }
    }

    return { value: { isAnswered: true, text: reply.text, usage: USAGE } }
  })
  on('session.surfaces', async () => ({ value: setup.surfaces ?? ['terminal'] }))
  on('ui.toast', async ($, e) => {
    seen.toasts.push(e.text)

    return { value: undefined }
  })
  on('turn.start', async ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', async ($, e) => ({ text: e.answer }))
  on('prompt.fill', async ($, e) => {
    seen.fills.push({ text: e.text, mode: e.mode })

    return setup.isFilled === false ? { isFilled: false, refusal: 'dialog' } : { isFilled: true }
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
  const seen = world(on, { reply: { text: 'Run the tests\nReview the diff\nCommit it\nA fourth' } })

  const result = await endTurn($)
  const { ui, labels } = await buttons($)

  expect(result.text).toBe(ANSWER)
  expect(seen.modelCalls).toEqual(['haiku'])
  expect(labels).toEqual(['Run the tests', 'Review the diff', 'Commit it'])
  await ui.unmount()
})

test('the band draws on the desktop surface too', async ($, on) => {
  world(on, { reply: { text: 'Run the tests' } })

  await endTurn($)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })

  expect((await ui.find({ key: 'next-step-1' }))?.props.label).toBe('Run the tests')
  await ui.unmount()
})

test('a turn that is not a full main-loop answer makes no model call', async ($, on) => {
  const seen = world(on, { reply: { text: 'Run the tests' } })

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
  const seen = world(on, { reply: { text: 'Run the tests\nReview the diff' } })

  await endTurn($)
  const { ui } = await buttons($)
  await ui.press({ key: 'next-step-2' })

  expect(seen.fills).toEqual([{ text: 'Review the diff', mode: 'insert' }])
  expect(seen.submits).toEqual([])
  expect(await ui.find({ key: 'next-step-1' })).toBeUndefined()
  await ui.unmount()
})

test('0 dismisses the band without touching the draft', async ($, on) => {
  const seen = world(on, { reply: { text: 'Run the tests' } })

  await endTurn($)
  const { ui } = await buttons($)

  expect((await ui.find({ key: 'next-step-dismiss' }))?.props.hotkey).toBe('0')
  await ui.press({ key: 'next-step-dismiss' })

  expect(await ui.find({ key: 'next-step-1' })).toBeUndefined()
  expect(seen.fills).toEqual([])
  await ui.unmount()
})

test('a new turn clears the last suggestions', async ($, on) => {
  world(on, { reply: { text: 'Run the tests' } })

  await endTurn($)
  await $.turn.start({ text: 'something else', turnId: 't2' })
  const { ui, labels } = await buttons($)

  expect(labels).toEqual([])
  await ui.unmount()
})

test("the model is shown the prompt of the turn it follows, not a queued one's", async ($, on) => {
  const seen = world(on, { reply: { text: 'Run the tests' } })

  await $.turn.start({ text: 'fix the parser', turnId: 't1' })
  await $.prompt.submit({ text: 'queued for later', wait: false, origin: { kind: 'composer' } })
  await endTurn($)

  expect(seen.prompts[0]).toContain('fix the parser')
  expect(seen.prompts[0]).not.toContain('queued for later')
})

test('a later turn too short to suggest for drops the earlier band', async ($, on) => {
  world(on, { reply: { text: 'Run the tests' } })

  await endTurn($)
  await endTurn($, { turnId: 't2', answer: 'Done.' })
  const { ui, labels } = await buttons($)

  expect(labels).toEqual([])
  await ui.unmount()
})

test("a subagent's turn leaves the main loop's band alone", async ($, on) => {
  world(on, { reply: { text: 'Run the tests' } })

  await endTurn($)
  await endTurn($, { turnId: 'sub', agentId: 'agent-1', answer: 'Done.' })
  const { ui, labels } = await buttons($)

  expect(labels).toEqual(['Run the tests'])
  await ui.unmount()
})

test('a draft the box did not take keeps the suggestions up', async ($, on) => {
  const seen = world(on, { reply: { text: 'Run the tests' }, isFilled: false })

  await endTurn($)
  const { ui } = await buttons($)
  await ui.press({ key: 'next-step-1' })

  expect(seen.fills.length).toBe(1)
  expect((await ui.find({ key: 'next-step-1' }))?.props.label).toBe('Run the tests')
  await ui.unmount()
})

test('where no surface draws the band, no model call is made', async ($, on) => {
  const headless = world(on, { reply: { text: 'Run the tests' }, surfaces: [] })

  await endTurn($)

  expect(headless.modelCalls).toEqual([])
})

test('a surface that never draws the band alone makes no model call', async ($, on) => {
  const seen = world(on, { reply: { text: 'Run the tests' }, surfaces: ['vscode', 'mobile'] })

  await endTurn($)

  expect(seen.modelCalls).toEqual([])
})

test('a refused request says so once and stops asking', async ($, on) => {
  const seen = world(on, { reply: { deny: 'model not allowed' } })

  await endTurn($)
  await endTurn($, { turnId: 't2' })

  expect(seen.modelCalls.length).toBe(1)
  expect(seen.toasts.length).toBe(1)
  expect(seen.toasts[0]).toContain('Next steps model')
})

test('switched off, it makes no model call and draws nothing', { options: { nextStepsEnabled: false } }, async ($, on) => {
  const seen = world(on, { reply: { text: 'Run the tests' } })

  await endTurn($)
  const { ui, labels } = await buttons($)

  expect(seen.modelCalls).toEqual([])
  expect(labels).toEqual([])
  await ui.unmount()
})

test('the model option picks who writes the suggestions', { options: { nextStepsModel: 'sonnet' } }, async ($, on) => {
  const seen = world(on, { reply: { text: 'Run the tests' } })

  await endTurn($)

  expect(seen.modelCalls).toEqual(['sonnet'])
})

test('a failed model call leaves the turn as it was and drops the stale band', async ($, on) => {
  let reply: Reply = { text: 'Run the tests' }
  world(on, { reply: () => reply })

  await endTurn($)
  reply = { reason: 'empty-reply' }
  const result = await endTurn($, { turnId: 't2' })
  const { ui, labels } = await buttons($)

  expect(result.text).toBe(ANSWER)
  expect(labels).toEqual([])
  await ui.unmount()
})

test('a reply with nothing to suggest leaves the band empty', async ($, on) => {
  world(on, { reply: { text: 'NONE' } })

  await endTurn($)
  const { ui, labels } = await buttons($)

  expect(labels).toEqual([])
  await ui.unmount()
})

test('a reply the model left without text leaves the band empty', async ($, on) => {
  world(on, { reply: { reason: 'empty-reply' } })

  const result = await endTurn($)
  const { ui, labels } = await buttons($)

  expect(result.text).toBe(ANSWER)
  expect(labels).toEqual([])
  await ui.unmount()
})
