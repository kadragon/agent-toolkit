# Out-of-Scope Review Findings

Deferred items surfaced during task-review. Not blocking; triage later.

## backlog_candidates

## lint

- [ ] **[P3] ruff pre-commit gate blocks on pre-existing violations in any touched `*/scripts/*.py`** — the local (repo-untracked) `.git/hooks/pre-commit` runs `ruff check` on staged scripts, and `dev/skills/harness-curate/scripts/scan_transcripts.py` alone carries 13 pre-existing hits (BLE001 x5, S112 x3, SIM115 x2, PIE810, SIM103), plus EXE001 + I001 in `dev/skills/task-next/scripts/backlog_candidates.py`. Verified pre-existing: HEAD and working-tree violation sets are identical. Touching any of these files for an unrelated reason therefore fails the commit — dev v4.0.14 had to use `--no-verify`. Note most blind `except Exception` sites are deliberate ("never raise, never block session start"), so the fix is a repo-level ruff config that encodes the intended ruleset (or per-site `# noqa` with a reason), NOT rewriting the handlers. CI does not run ruff, so this is local-gate-only today.

## backlog_candidates

- [ ] **[P3] `_strip_html_comments` drops the file's last line when a comment reaches true EOF** — `_strip_html_comments("<!--\nx\n-->")` returns 2 lines for a 3-line input. Same root cause as the fenced-block bug fixed in dev v4.0.14 (the `"\n" * count` replacement under-represents the final line when the match ends at EOF with nothing after it), but in the untouched comment stripper. Functionally inert today: the dropped line is always blank, and `_region_end` uses `math.inf` for the EOF boundary rather than a line total, so no token's line number shifts. Found by qa-verifier while re-verifying the fenced-block fix. Fix: mirror the `+ "\n" if out else ""` treatment, and extend Test 3d's line-count loop to cover `_strip_html_comments` on the same fixtures.
