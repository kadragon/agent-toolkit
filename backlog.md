# Backlog

## Now

## Next


## Someday

## History

- [x] [HARNESS] `commit-guard/guard.py` — branch guard now models in-chain `git checkout -b/-B/--orphan <n>` / `git switch -c/-C/--create/--orphan <n>`: a `git checkout -b X && git commit ...` one-liner on main is allowed (commit lands on the new branch). Attribution carries only across `&&` and is dropped across `||`/`;`/`|`/`&`/newline/`cd`, closing the `||`/`;`/cross-repo mis-attribution holes. (v3.6.5)
- [x] [HARNESS] `commit-guard/guard.py` — type guard now fails open on statically-undecidable messages: a `-m "$(...)"` / backtick command-substitution message skips the type check instead of blocking, per the hook's fail-open contract. (v3.6.5)
