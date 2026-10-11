import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import { buildPrompt, isEligible, parseSuggestions } from './suggest'

// UX after the community `next-steps` mod (hamzafer.github.io): offer up to
// three prompts after a turn, fill the draft on a digit, never send.
const MODEL_TIMEOUT_MS = 8000
// The surfaces the engine raises the band above the prompt on.
const BAND_SURFACES: readonly string[] = ['terminal', 'desktop']

const nextSteps = atom({ plugin: 'mods', key: 'nextSteps' } as const, null)

export const register: Register = (on, options) => {
  if (options.nextStepsEnabled === false) return

  const model =
    typeof options.nextStepsModel === 'string' && options.nextStepsModel !== ''
      ? options.nextStepsModel
      : 'haiku'
  let userPrompt = ''
  let isRefused = false

  // A subagent's run raises no `turn.start`, so this is the main loop's prompt.
  on('turn.start', async ($, e, next) => {
    userPrompt = e.text
    await update($, nextSteps, () => null)

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)

    if (e.agentId !== undefined) return result

    // A suggestion is a convenience: nothing here may fail or change the turn.
    try {
      let suggestions: string[] = []
      const surfaces = isRefused || !isEligible(e) ? [] : await $.session.surfaces()

      if (surfaces.some(surface => BAND_SURFACES.includes(surface))) {
        const reply = await $.model
          .complete({
            model,
            prompt: buildPrompt(userPrompt, e.answer),
            maxTokens: 200,
            effort: 'low',
            timeoutMs: MODEL_TIMEOUT_MS,
          })
          .catch(() => null)

        if (reply === null) {
          // The engine refused to send the request (a blocked or unknown model):
          // every later turn would be refused the same way, so say it once and stop.
          isRefused = true
          $.ui.toast(
            `Next steps is off for this session: the "Next steps model" setting (${model}) was refused.`,
          )
        } else if (reply.isAnswered) {
          suggestions = parseSuggestions(reply.text)
        }
      }

      await update($, nextSteps, () =>
        suggestions.length > 0 ? { turnId: e.turnId, suggestions } : null,
      )
    } catch {
      await update($, nextSteps, () => null).catch(() => undefined)
    }

    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await read($, nextSteps)

    if (current === null || e.props.hasSurvey || e.props.isWorking) {
      return next(e)
    }

    const { Box, Button, Text } = $.ui.resolve(e)

    return (
      <Box flexDirection="column">
        <Text dimColor>Next steps (a digit fills the prompt, 0 dismisses)</Text>
        {current.suggestions.map((text, index) => (
          <Button
            key={`next-step-${index + 1}`}
            hotkey={String(index + 1)}
            label={text}
            plain
            onPress={async () => {
              // `insert` keeps a draft in progress; the band stays while no box took it.
              const filled = await $.prompt.fill({ text, mode: 'insert' })

              if (filled.isFilled) await update($, nextSteps, () => null)
            }}
          />
        ))}
        <Button
          key="next-step-dismiss"
          hotkey="0"
          label="Dismiss"
          plain
          dimColor
          onPress={() => update($, nextSteps, () => null)}
        />
      </Box>
    )
  })
}
