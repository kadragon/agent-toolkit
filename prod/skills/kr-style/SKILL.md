---
name: kr-style
description: >-
  Rewrite Korean prose that reads like a translation into Korean that reads like
  it was written in Korean — drops the English syntax, inflection, and
  preposition transfers, then verifies with a script that exits 0. Use before
  handing the user any Korean prose longer than a few paragraphs. NOT for
  typo/spacing correction, NOT for rendering one language into another, NOT for
  changing what the text claims.
version: 1.0.0
allowed-tools: Bash Read Edit Write Grep
---

# Korean Style

Korean written by a model carries the shape of the English it was thought in. The tells are
not vocabulary — they are three English grammatical categories that Korean does not have,
transferred wholesale (김순영, 새국어생활 22-1):

| Axis | What transfers | Surface form |
|------|----------------|--------------|
| 구문 형식 | syntax | `have` → `가지고 있다`, passive → `~에 의해 ~되다` |
| 굴절 형식 | obligatory gender/number/case | `-s` → `-들`, `she/they` → `그녀/그들` |
| 전치사구 | prepositions | `from` → `~로부터`, `through` → `~를 통해`, `of` → `~의` |

Korean marks none of these obligatorily, so every transferred one is a trace of an original
that was never there. Strip the trace, keep the meaning — **what the text claims never
changes**, only how it is said.

## Loop

1. **Get the text into a file.** Already a file: use it. Drafted in-conversation: write it to
   a scratch file first — the audit reads files, and an unaudited draft is the failure mode
   this skill exists to prevent.

2. **Run the audit.**

   Resolve the script relative to *this* SKILL.md (its parent dir):

   ```sh
   AUDIT=<dir-of-this-SKILL.md>/scripts/kr_audit.py
   python3 "$AUDIT" path/to/draft.md
   ```

   Every `[FAIL]` line names the rule, the line number, and the fix. `[ok]` lines are hits
   still under their frequency allowance — leave them alone, the allowance is the point.

3. **Rewrite each FAIL at its line.** Apply the fix the report names; the full rule table
   with before/after pairs is in `references/patterns.md` — read it when a report line's
   one-line fix is not enough to act on.

4. **Walk the manual checklist below.** The audit only sees surface patterns. The checklist
   is where Korean actually becomes Korean, and no script can decide any of it.

5. **Re-run the audit. Exit 0 is the completion criterion** — not "looks better". If a hit
   is a genuine false positive (a quoted source, a term of art, a proper noun), say so in one
   line to the user and leave the text alone; do not contort a sentence to satisfy a regex.

## Manual checklist

Five questions, asked over the whole draft. Each one is a positive target — what Korean does,
not what to avoid.

- **주어 생략** — Korean has no obligatory subject. Every `저는 / 우리는 / 이것은` that the
  context already supplies comes out. A paragraph where each sentence names its subject is
  English wearing Korean particles.
- **동사 중심** — English piles meaning into nouns, Korean into verbs. `검토를 진행한다` →
  `검토한다`. `~의 구현` → `~을 구현해`. Chase `-성 / -적 / -화` back to the verb or adjective
  it came from.
- **이중주어** — `X는 Y가 Z다` is the native answer to English `have`: `이 API는 응답이 느리다`,
  not `이 API는 느린 응답을 가지고 있다`.
- **은/는 vs 이/가** — new information and event description take `이/가`; the topic, and
  anything contrasted, takes `은/는`. Mechanically mapping every English subject to `은/는` is
  the single most common transfer and the audit cannot see it.
- **핵어 후치** — Korean is head-final: the load-bearing information lands at the end of the
  sentence, and a modifier that runs three 어절 or longer in front of its noun belongs in its
  own sentence.

## Register

Match the draft's own register — formal stays formal, spoken stays spoken. Rewriting is not
licence to raise or lower the honorific level, and one level holds across the whole document.
Code, identifiers, file paths, numbers, dates, quoted sources, and standard technical terms
(API, prompt, token) stay verbatim: they are not prose and are out of scope for every rule
here.

## Credits

- 김순영, [영한 번역에 나타난 번역투 문장](https://www.korean.go.kr/nkview/nklife/2012_1/22_0105.pdf),
  새국어생활 22권 1호 — the three-axis classification this skill is built on.
- [번역문에 나타난 국어의 모습](https://www.korean.go.kr/nkview/nklife/1990_2/21_4.html), 국립국어원
  — pronoun overuse, 주격/주제격 confusion, tense.
- 이근희(2005), 김정우(1996, 2007) — the worked before/after pairs quoted in `references/patterns.md`.
