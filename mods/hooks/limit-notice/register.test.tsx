import { expect, test } from 'claude-code/testing'

import { isLimitWarning } from './register'

const WARNING =
  "You've used 75% of your weekly limit · resets Nov 18, 2pm (Asia/Seoul) · Run /usage-credits to turn on extra usage for your org"

const notice = (text: string, command: string | null = null) =>
  ({
    plugin: 'mods',
    surface: 'terminal',
    component: 'InfoNotice',
    props: { text, command },
  }) as const

test('the usage warning is drawn as nothing', async $ => {
  const ui = await $.ui.mount(notice(WARNING, '/usage-credits'))

  expect(await ui.keepsBeneath()).toBe(false)
  await ui.unmount()
})

test('any other notice is left to the engine', async $ => {
  const ui = await $.ui.mount(notice('Model set from ANTHROPIC_MODEL', '/model'))

  expect(await ui.keepsBeneath()).toBe(true)
  await ui.unmount()
})

test(
  'switched off, the warning is left to the engine',
  { options: { limitNoticeHidden: false } },
  async $ => {
    const ui = await $.ui.mount(notice(WARNING, '/usage-credits'))

    expect(await ui.keepsBeneath()).toBe(true)
    await ui.unmount()
  },
)

test('it reads each limit window and leaves other percentages alone', async () => {
  expect(isLimitWarning(WARNING)).toBe(true)
  expect(isLimitWarning("You've used 90% of your session limit · resets 4pm")).toBe(true)
  expect(isLimitWarning('Context 75% full')).toBe(false)
})
