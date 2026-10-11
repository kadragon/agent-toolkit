export type NextSteps = { turnId: string; suggestions: string[] }

declare module 'claude-code' {
  interface PluginState {
    mods: { nextSteps: NextSteps | null }
  }
}
