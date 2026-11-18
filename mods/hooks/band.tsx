import { atom, read } from 'claude-code'
import type { Register } from 'claude-code'

import { noteTerminalColumns } from './pr-recap/register'
import { ASCII, setupSegments, UNICODE } from './status-band/format'
import { statusRows } from './status-band/register'

// The same value the mod writes: the loader reads an atom's key off the file
// that uses it, so it is spelled again here.
const statusBand = atom({ plugin: 'mods', key: 'statusBand' } as const, null)

// The engine takes one hook per plugin on the band above the prompt, so a mod
// that draws there hands its rows over here.
// The status rows are three, or two with the setup on the headline where the
// band has no third; under a blank one where another row fits.
const STATUS_ROWS = 3
const MIN_STATUS_ROWS = 2

export const register: Register = (on, options) => {
  // `$.state` outlives a reload, so a mod switched off mid-session still has its
  // last value there: the option decides, not the value.
  const isStatusBandOn = options.statusBandEnabled !== false
  const isPrRecapOn = options.prRecapEnabled !== false

  if (!isStatusBandOn && !isPrRecapOn) return

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    // The band spans the terminal: the pr-recap pane sizes its dock off it.
    if (isPrRecapOn) noteTerminalColumns($, e.viewport?.columns)
    if (!isStatusBandOn || e.props.hasSurvey || MIN_STATUS_ROWS > e.props.maxRows) return next(e)

    const status = await read($, statusBand)

    if (status === null) return next(e)

    const glyphs = options.statusBandAscii === true ? ASCII : UNICODE
    const isSplit = STATUS_ROWS <= e.props.maxRows
    // A setup with no figure read yet draws no row, leaving room for the blank one.
    const rows = isSplit && setupSegments(status, glyphs).length > 0 ? STATUS_ROWS : MIN_STATUS_ROWS

    return statusRows($.ui.resolve(e), status, {
      hasMargin: rows < e.props.maxRows,
      isSplit,
      glyphs,
      columns: e.viewport?.columns,
    })
  })
}
