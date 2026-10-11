import { atom, update } from 'claude-code'
import type { Elements, Register, RenderElement } from 'claude-code'

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
}

type BandElements = Pick<Elements['terminal'], 'Box' | 'Button' | 'Text'>

// This mod's rows of the band above the prompt. `hooks/band.tsx` draws them:
// the engine takes one band hook per plugin, and `$` stays in that hook's file.
export const nextStepRows = (
  { Box, Button, Text }: BandElements,
  suggestions: readonly string[],
  onPick: (text: string) => Promise<void>,
  onDismiss: () => Promise<void>,
): RenderElement => {
  return (
    <Box flexDirection="column">
      <Text dimColor>Next steps (a digit fills the prompt, 0 dismisses)</Text>
      {suggestions.map((text, index) => (
        <Button
          key={`next-step-${index + 1}`}
          hotkey={String(index + 1)}
          label={text}
          plain
          onPress={() => onPick(text)}
        />
      ))}
      <Button
        key="next-step-dismiss"
        hotkey="0"
        label="Dismiss"
        plain
        dimColor
        onPress={onDismiss}
      />
    </Box>
  )
}
