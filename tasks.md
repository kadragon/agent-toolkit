## Review Backlog

### PR #121 — harness-curator: fuzzy-match project transcript dir on case/underscore drift (2026-07-07)

- [ ] [debt] `_loose_key()` in scan_transcripts.py strips all non a-z0-9 chars (incl. non-ASCII/Korean and path separators), so two distinct project paths can collapse to the same key and `resolve_project_dir()` picks the wrong transcript dir (favors max file count). Reviewers hedged this as low-confidence (review: P3/40, codex: P2/no score) — deferred rather than fixed this cycle. If addressed: prefer the exact `encode_project()` match whenever it exists, only fall back to fuzzy matching when the exact dir is absent — narrows but does not fully close the collision risk. (source: review, codex) — dev-tools/skills/harness-curator/scripts/scan_transcripts.py:99,120
