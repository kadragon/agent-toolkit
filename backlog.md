# Backlog

## Now

## Next


## Someday

- [ ] [HARNESS] `commit-guard/guard.py` — `_split_segments` discards which operator joins segments, so in-chain branch tracking (and `cd` cwd tracking) propagates across `||`. `git checkout -b X || git commit ...` mis-attributes branch X to the commit, though the commit only runs when the checkout *fails* (HEAD still on main). Adversarial-only; covered by fail-open. Fix would thread the joining operator into segment metadata and not propagate state across `||`. P3, conf 100. (source: QA probe)

## History

- [x] [HARNESS] `commit-guard/guard.py` — branch guard now models in-chain `git checkout -b/-B <n>` / `git switch -c/-C <n>`: a `git checkout -b X && git commit ...` one-liner on main is allowed (commit lands on the new branch). (v3.6.5)
- [x] [HARNESS] `commit-guard/guard.py` — type guard now fails open on statically-undecidable messages: a `-m "$(...)"` / backtick command-substitution message skips the type check instead of blocking, per the hook's fail-open contract. (v3.6.5)
