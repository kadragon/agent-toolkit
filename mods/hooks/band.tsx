import { atom, read } from 'claude-code'
import type { Register } from 'claude-code'

import { ASCII, setupSegments, UNICODE, workSegments } from './status-band/format'
import { statusRows } from './status-band/register'

// The same value the mod writes: the loader reads an atom's key off the file
// that uses it, so it is spelled again here.
const statusBand = atom({ plugin: 'mods', key: 'statusBand' } as const, null)

// The engine takes one hook per plugin on the band above the prompt, so a mod
// that draws there hands its rows over here.
// The status rows are three, or two with the setup on the headline where the
// band has no third, and a fourth for the cycle and the queue where the band
// has it (else they ride on the setup); under a blank one where another row fits.
const STATUS_ROWS = 3
const MIN_STATUS_ROWS = 2
const WORK_ROWS = STATUS_ROWS + 1

export const register: Register = (on, options) => {
  // `$.state` outlives a reload, so a mod switched off mid-session still has its
  // last value there: the option decides, not the value.
  if (options.statusBandEnabled === false) return

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || MIN_STATUS_ROWS > e.props.maxRows) return next(e)

    const status = await read($, statusBand)

    if (status === null) return next(e)

    const glyphs = options.statusBandAscii === true ? ASCII : UNICODE
    const isSplit = STATUS_ROWS <= e.props.maxRows
    const hasWorkRow = isSplit && WORK_ROWS <= e.props.maxRows && workSegments(status, glyphs).length > 0
    // A setup with no figure read yet draws no row, leaving room for the blank one.
    const rows = hasWorkRow
      ? WORK_ROWS
      : isSplit && setupSegments(status, glyphs).length > 0
        ? STATUS_ROWS
        : MIN_STATUS_ROWS

    return statusRows($.ui.resolve(e), status, {
      hasMargin: rows < e.props.maxRows,
      isSplit,
      hasWorkRow,
      glyphs,
    })
  })
}
