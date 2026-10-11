// Pure suggestion logic: no engine types, so it runs and tests without `$`.

export const MAX_SUGGESTIONS = 3
export const MIN_ANSWER_CHARS = 100
const MAX_SUGGESTION_CHARS = 120
const MAX_CONTEXT_CHARS = 4000

export type Turn = {
  answer: string
  reason: 'answer' | 'aborted' | 'refusal' | 'error'
  agentId?: string
}

export const isEligible = (turn: Turn): boolean =>
  turn.reason === 'answer' &&
  turn.agentId === undefined &&
  turn.answer.trim().length >= MIN_ANSWER_CHARS

// Keeps the end of a long text: the close of an answer says what comes next.
const tail = (text: string): string =>
  text.length > MAX_CONTEXT_CHARS ? text.slice(-MAX_CONTEXT_CHARS) : text

export const buildPrompt = (userPrompt: string, answer: string): string =>
  [
    'A coding assistant just answered its user. Suggest what the user is most',
    `likely to ask for next: at most ${MAX_SUGGESTIONS} short prompts, written as the`,
    'user would type them, in the language the user wrote in. Suggest only what',
    'the conversation supports. Do not claim tests, reviews or commits happened',
    'unless the answer says so. If nothing useful follows, reply NONE.',
    'Reply with one prompt per line and nothing else.',
    '',
    '<user_prompt>',
    tail(userPrompt),
    '</user_prompt>',
    '<assistant_answer>',
    tail(answer),
    '</assistant_answer>',
  ].join('\n')

export const parseSuggestions = (reply: string): string[] => {
  const seen = new Set<string>()
  const suggestions: string[] = []

  for (const raw of reply.split('\n')) {
    const line = raw
      .replace(/^\s*(?:[-*•]|\d+[.):])\s*/, '')
      .replace(/^["'`]+|["'`]+$/g, '')
      .trim()

    if (line === '' || line.toUpperCase() === 'NONE') continue
    if (line.length > MAX_SUGGESTION_CHARS || seen.has(line)) continue

    seen.add(line)
    suggestions.push(line)

    if (suggestions.length === MAX_SUGGESTIONS) break
  }

  return suggestions
}
