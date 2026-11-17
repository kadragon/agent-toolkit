import type { Register } from 'claude-code'

// "You've used 75% of your weekly limit · resets … · Run /usage-credits …":
// the engine's usage warning, whatever window or wording of the tail. One or
// two digits: a limit reached (100%) still shows.
const LIMIT_WARNING = /(?<!\d)\d{1,2}% of your\b[^·]*\blimit\b/i

export const isLimitWarning = (text: string): boolean => LIMIT_WARNING.test(text)

// The engine raises its usage warning as a dim notice line; this draws an
// empty Box in its place and hands every other notice on untouched.
export const register: Register = (on, options) => {
  if (options.limitNoticeHidden === false) return

  on('ui.render', { component: 'InfoNotice' }, ($, e, next) => {
    if (!isLimitWarning(e.props.text)) return next(e)

    const { Box } = $.ui.resolve(e)

    return <Box />
  })
}
