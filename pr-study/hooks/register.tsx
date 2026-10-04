import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { FileStat, Study, StudyNotes } from '../types'

const PANE = 'pr-study'
const EMPTY: StudyNotes = {
  phase: 'idle', markdown: '', study: null, files: [], branch: '', base: '', updatedAt: '', diffKey: '', checked: [],
}
const notes = atom({ plugin: 'pr-study', key: 'notes' } as const, EMPTY)

// Diff sent to the model is capped so one refresh stays a cheap haiku call.
const MAX_DIFF_CHARS = 60000
const MAX_MISTAKES_CHARS = 8000
const MAX_PANE_CHARS = 9500
const MAX_FILES_SHOWN = 8

const SYSTEM = `You write study notes for a developer reviewing their own pull request.
Reply with ONE JSON object and nothing else, no code fence:
{"summary": string, "points": [{"title": string, "file": string, "why": string, "level": 1|2|3}],
 "questions": [string], "review": [{"mistake": string, "why": string}]}
- All prose in Korean; code, identifiers and paths verbatim.
- summary: one sentence, <= 60 chars, what this change does.
- points: 3-5 concepts the reader must understand to own this change. title <= 30 chars,
  file = the most relevant path, why <= 70 chars, level = difficulty (1 easy, 3 hard).
- questions: 3 recall questions answerable from the diff, no answers.
- review: only past repo-quiz mistakes that this diff touches; else [].`

let running = false

// Cheap fingerprint so an unchanged diff after a turn skips the model call.
function diffKey(base: string, diff: string): string {
  let h = 5381
  for (let i = 0; i < diff.length; i++) h = ((h << 5) + h + diff.charCodeAt(i)) | 0
  // Version prefix: bump when StudyNotes changes shape so a reload regenerates.
  return `v2:${base}:${diff.length}:${h >>> 0}`
}

async function git($: EngineInterface, args: string[]): Promise<string | undefined> {
  const r = await $.process.run(['git', ...args])
  return r.exitCode === 0 ? r.stdout.trim() : undefined
}

async function findBase($: EngineInterface): Promise<string | undefined> {
  for (const ref of ['origin/main', 'main', 'origin/master', 'master']) {
    const base = await git($, ['merge-base', 'HEAD', ref])
    if (base) return base
  }
  return undefined
}

function parseNumstat(text: string): FileStat[] {
  return text
    .split('\n')
    .map(line => line.split('\t'))
    .filter(cols => cols.length >= 3)
    // Binary files report "-" for both counts.
    .map(([add, del, ...path]) => ({ path: path.join('\t'), add: Number(add) || 0, del: Number(del) || 0 }))
}

function parseStudy(text: string): Study | null {
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start < 0 || end <= start) return null
  try {
    const raw = JSON.parse(text.slice(start, end + 1)) as Partial<Study>
    if (typeof raw.summary !== 'string' || !Array.isArray(raw.points)) return null
    return {
      summary: raw.summary,
      points: raw.points.slice(0, 5).map(p => ({ ...p, level: Math.min(3, Math.max(1, Number(p.level) || 1)) })),
      questions: Array.isArray(raw.questions) ? raw.questions.slice(0, 5) : [],
      review: Array.isArray(raw.review) ? raw.review : [],
    }
  } catch {
    return null
  }
}

async function refresh($: EngineInterface, force = false): Promise<void> {
  if (running) return
  running = true
  try {
    const base = await findBase($)
    if (!base) {
      await update($, notes, (n): StudyNotes => ({ ...n, phase: 'error', markdown: 'git 저장소나 main 브랜치를 찾지 못함.' }))
      return
    }
    // Committed branch work plus uncommitted edits, both against the merge-base.
    const diff = (await git($, ['diff', base])) ?? ''
    const key = diffKey(base, diff)
    if (!force && (await read($, notes)).diffKey === key) return
    const files = parseNumstat((await git($, ['diff', '--numstat', base])) ?? '')
    const branch = (await git($, ['rev-parse', '--abbrev-ref', 'HEAD'])) ?? ''
    const head = { files, branch, base: base.slice(0, 7), updatedAt: new Date().toLocaleTimeString() }
    if (diff === '') {
      await update($, notes, (): StudyNotes => ({ ...EMPTY, ...head, phase: 'empty', diffKey: key }))
      return
    }
    await update($, notes, (n): StudyNotes => ({ ...n, ...head, phase: 'loading' }))
    let mistakes = ''
    try {
      mistakes = (await $.fs.read('.repo-quiz/mistakes.md')).slice(-MAX_MISTAKES_CHARS)
    } catch {
      // No repo-quiz history yet; review stays empty.
    }
    const stat = files.map(f => `${f.path} +${f.add} -${f.del}`).join('\n')
    const prompt = [
      `<files>\n${stat}\n</files>`,
      `<diff>\n${diff.slice(0, MAX_DIFF_CHARS)}${diff.length > MAX_DIFF_CHARS ? '\n[truncated]' : ''}\n</diff>`,
      mistakes ? `<repo-quiz-mistakes>\n${mistakes}\n</repo-quiz-mistakes>` : '',
    ].join('\n\n')
    const r = await $.model.complete({ model: 'haiku', system: SYSTEM, prompt, maxTokens: 2000, timeoutMs: 90000 })
    await update($, notes, (): StudyNotes => {
      if (!r.isAnswered) {
        // Empty key: a failed generation retries on the next turn.
        return { ...EMPTY, ...head, phase: 'error', markdown: `생성 실패: ${r.reason}` }
      }
      const study = parseStudy(r.text)
      return { ...EMPTY, ...head, phase: 'ready', study, markdown: study ? '' : r.text.slice(0, MAX_PANE_CHARS), diffKey: key }
    })
  } finally {
    running = false
  }
}

function bar(n: number, scale: number, width: number): string {
  return n === 0 ? '' : '█'.repeat(Math.max(1, Math.round((n / scale) * width)))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'pr-study',
      description: 'Open the PR study pane and regenerate notes from the current diff',
    })
    // Opened unasked: the engine seats it only from 144 columns, else it waits.
    void $.ui.open({ id: PANE, title: 'PR 공부' })
    void refresh($)

    return next(e)
  })

  on('command.run', { command: 'pr-study' }, async $ => {
    await $.ui.open({ id: PANE, title: 'PR 공부' })
    void refresh($, true)

    return { text: 'PR 공부 pane 갱신 중.' }
  })

  // Main-loop turns only: subagent turns would re-diff once per subagent step.
  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId === undefined) void refresh($)

    return done
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Markdown, Button } = $.ui.resolve(e)
    // $.state outlives reloads; merge so a value saved by an older shape still draws.
    const n: StudyNotes = { ...EMPTY, ...(await read($, notes)) }
    const cols = Math.max(24, e.props.bodyColumns)
    const totalAdd = n.files.reduce((s, f) => s + f.add, 0)
    const totalDel = n.files.reduce((s, f) => s + f.del, 0)
    const scale = Math.max(1, ...n.files.map(f => f.add + f.del))
    const nameWidth = Math.min(28, Math.floor(cols * 0.45))
    const barWidth = Math.max(4, cols - nameWidth - 12)
    const s = n.study
    const toggle = (i: number) =>
      update($, notes, (cur): StudyNotes => ({
        ...cur,
        checked: (cur.checked ?? []).includes(i) ? cur.checked.filter(x => x !== i) : [...(cur.checked ?? []), i],
      }))

    return (
      <Box flexDirection="column" gap={1}>
        <Box flexDirection="column">
          <Text>
            <Text bold color="cyan">⎇ {n.branch || '…'}</Text>
            <Text dimColor> ← {n.base || '?'}</Text>
          </Text>
          {n.files.length > 0 && (
            <Text>
              <Text dimColor>{n.files.length} files  </Text>
              <Text color="green">+{totalAdd}</Text>
              <Text> </Text>
              <Text color="red">−{totalDel}</Text>
            </Text>
          )}
        </Box>

        {n.phase === 'loading' && <Text color="yellow">◌ diff 분석 중…</Text>}
        {n.phase === 'idle' && <Text dimColor>아직 생성 전 · /pr-study</Text>}
        {n.phase === 'empty' && <Text dimColor>✓ main 대비 변경점 없음</Text>}
        {n.phase === 'error' && <Text color="red">✗ {n.markdown}</Text>}

        {n.files.length > 0 && (
          <Box flexDirection="column">
            {n.files.slice(0, MAX_FILES_SHOWN).map(f => (
              <Box flexDirection="row">
                <Box width={nameWidth}>
                  <Text wrap="truncate-start">{f.path}</Text>
                </Box>
                <Text> </Text>
                <Text color="green">{bar(f.add, scale, barWidth)}</Text>
                <Text color="red">{bar(f.del, scale, barWidth)}</Text>
                <Text dimColor> {f.add + f.del}</Text>
              </Box>
            ))}
            {n.files.length > MAX_FILES_SHOWN && <Text dimColor>… +{n.files.length - MAX_FILES_SHOWN} files</Text>}
          </Box>
        )}

        {s && (
          <Box borderStyle="round" borderColor="cyan" paddingX={1}>
            <Text bold>{s.summary}</Text>
          </Box>
        )}

        {s && s.points.length > 0 && (
          <Box flexDirection="column">
            <Text bold color="magenta">◆ 공부 포인트</Text>
            {s.points.map((p, i) => (
              <Box flexDirection="column" borderStyle="single" borderColor="gray" paddingX={1}>
                <Text>
                  <Text bold>{i + 1}. {p.title}</Text>
                  <Text color="yellow">  {'●'.repeat(p.level)}</Text>
                  <Text dimColor>{'○'.repeat(3 - p.level)}</Text>
                </Text>
                <Text color="cyan" wrap="truncate-start">{p.file}</Text>
                <Text dimColor>{p.why}</Text>
              </Box>
            ))}
          </Box>
        )}

        {s && s.questions.length > 0 && (
          <Box flexDirection="column">
            <Text bold color="blue">? 스스로 확인 <Text dimColor>({n.checked.length}/{s.questions.length})</Text></Text>
            {s.questions.map((q, i) => (
              <Box flexDirection="row" gap={1}>
                <Button key={`q${i}`} plain onPress={() => toggle(i)}>
                  {n.checked.includes(i) ? '☑' : '☐'}
                </Button>
                <Text dimColor={n.checked.includes(i)} strikethrough={n.checked.includes(i)}>{q}</Text>
              </Box>
            ))}
          </Box>
        )}

        {s && s.review.length > 0 && (
          <Box flexDirection="column" borderStyle="round" borderColor="red" paddingX={1}>
            <Text bold color="red">↺ 복습 연결</Text>
            {s.review.map(r => (
              <Text>
                <Text bold>{r.mistake}</Text>
                <Text dimColor> — {r.why}</Text>
              </Text>
            ))}
          </Box>
        )}

        {n.phase === 'ready' && !s && n.markdown !== '' && <Markdown text={n.markdown} />}

        <Text dimColor>{n.updatedAt ? `${n.updatedAt} · /pr-study 강제 갱신` : '/pr-study 로 생성'}</Text>
      </Box>
    )
  })
}
