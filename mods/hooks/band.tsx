import { atom, read, update } from 'claude-code'
import type { Register, RenderElement } from 'claude-code'

import { nextStepRows } from './next-steps/register'
import { statusRows } from './status-band/register'

// The same values the mods write: the loader reads an atom's key off the file
// that uses it, so each is spelled again here.
const nextSteps = atom({ plugin: 'mods', key: 'nextSteps' } as const, null)
const statusBand = atom({ plugin: 'mods', key: 'statusBand' } as const, null)

// The engine takes one hook per plugin on the band above the prompt, so the
// mods that draw there are stacked here, each handing over its rows.
// The status rows are two under a blank one; next-steps draws a heading, its
// buttons and Dismiss.
const STATUS_ROWS = 3
const NEXT_STEPS_CHROME_ROWS = 2
// The brackets, the hotkey and the spaces the terminal draws around a label.
const BUTTON_CHROME_CELLS = 7

export const register: Register = (on, options) => {
  // `$.state` outlives a reload, so a mod switched off mid-session still has its
  // last value there: the option decides, not the value.
  const hasStatus = options.statusBandEnabled !== false
  const hasNextSteps = options.nextStepsEnabled !== false

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)

    const steps = hasNextSteps && !e.props.isWorking ? await read($, nextSteps) : null
    const columns = Math.max(1, e.props.bodyColumns)
    // A long suggestion wraps: count the rows its `[ n: label ]` really takes.
    const stepRows =
      steps === null
        ? 0
        : steps.suggestions.reduce(
            (rows, text) => rows + Math.ceil((text.length + BUTTON_CHROME_CELLS) / columns),
            NEXT_STEPS_CHROME_ROWS,
          )
    // A digit reaches only a button inside the band's window, so the status
    // rows give way where both would not fit.
    const status =
      hasStatus && stepRows + STATUS_ROWS <= e.props.maxRows ? await read($, statusBand) : null

    if (status === null && steps === null) return next(e)

    const elements = $.ui.resolve(e)
    const rows: RenderElement[] = []

    if (status !== null) rows.push(statusRows(elements, status))
    if (steps !== null) {
      rows.push(
        nextStepRows(
          elements,
          steps.suggestions,
          async text => {
            // `insert` keeps a draft in progress; the band stays while no box took it.
            const filled = await $.prompt.fill({ text, mode: 'insert' })

            if (filled.isFilled) await update($, nextSteps, () => null)
          },
          async () => {
            await update($, nextSteps, () => null)
          },
        ),
      )
    }

    return <elements.Box flexDirection="column">{rows}</elements.Box>
  })
}
