import type { Register } from 'claude-code'

import { register as band } from './band'
import { register as nextSteps } from './next-steps/register'
import { register as statusBand } from './status-band/register'

// The engine loads one hooks module per plugin, so every mod registers here.
// Each is called by name: the loader refuses a callee it cannot trace to a file.
export const register: Register = (on, options) => {
  nextSteps(on, options)
  statusBand(on, options)
  band(on, options)
}
