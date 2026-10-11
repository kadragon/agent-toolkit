import type { Register } from 'claude-code'

import { register as nextSteps } from './next-steps/register'

// The engine loads one hooks module per plugin, so every mod registers here.
// Each is called by name: the loader refuses a callee it cannot trace to a file.
export const register: Register = (on, options) => {
  nextSteps(on, options)
}
