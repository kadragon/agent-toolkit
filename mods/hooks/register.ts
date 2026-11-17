import type { Register } from 'claude-code'

import { register as agentFlow, startAgentFlow } from './agent-flow/register'
import { register as band } from './band'
import { register as limitNotice } from './limit-notice/register'
import { register as statusBand, startStatusBand } from './status-band/register'

// The engine loads one hooks module per plugin, so every mod registers here.
// Each is called by name: the loader refuses a callee it cannot trace to a file.
export const register: Register = (on, options) => {
  statusBand(on, options)
  limitNotice(on, options)
  agentFlow(on, options)
  band(on, options)

  // The engine takes one session.start hook per plugin: each mod's start runs
  // here, after the engine's own, and does nothing while its mod is off.
  on('session.start', async ($, e, next) => {
    const result = await next(e)

    startStatusBand($)
    await startAgentFlow($)

    return result
  })
}
