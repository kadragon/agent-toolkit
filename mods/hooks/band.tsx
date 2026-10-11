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
export const register: Register = on => {
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)

    const status = await read($, statusBand)
    const steps = e.props.isWorking ? null : await read($, nextSteps)

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
