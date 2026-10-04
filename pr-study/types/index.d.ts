export type StudyPhase = 'idle' | 'loading' | 'ready' | 'empty' | 'error'
export type FileStat = { path: string; add: number; del: number }
export type StudyPoint = { title: string; file: string; why: string; level: number }
export type StudyReview = { mistake: string; why: string }
export type Study = { summary: string; points: StudyPoint[]; questions: string[]; review: StudyReview[] }
export type StudyNotes = {
  phase: StudyPhase
  // Fallback text when the model reply is not parseable JSON, or the error message.
  markdown: string
  study: Study | null
  files: FileStat[]
  branch: string
  base: string
  updatedAt: string
  diffKey: string
  // Indexes of self-check questions the reader ticked; reset per generation.
  checked: number[]
}

declare module 'claude-code' {
  interface PluginState {
    'pr-study': { notes: StudyNotes }
  }
}
