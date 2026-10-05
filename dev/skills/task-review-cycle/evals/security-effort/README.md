# Security-effort fixtures

Fixture set for the `EFFORT=high`-on-`SECURITY_HIT` decision
(`../trigger-eval.json` holds trigger cases only; this directory holds the
recall experiment). Each `.patch` is a minimal diff that plants one known
vulnerability chain: f1–f6 in a single clean file, f7 across two changed
files plus one unchanged caller the repo must also carry. Every fixture trips the `SECURITY_HIT`
capture in `../../references/risk-routing.md`, so each one represents the
diff class the `EFFORT="high"` rule fires on.

| Fixture | File (trips `SECURITY_HIT` via) | Planted bug |
|---|---|---|
| `f1-auth.patch` | `auth/middleware.py` (`auth`) | `?debug=true` skips token check, grants admin |
| `f2-secret.patch` | `secret_store.py` (`secret`) | `except` handler logs `SECRET_KEY` in plaintext |
| `f3-cmdinj.patch` | `network_fetcher.py` (`network`) | `shell=True` f-string command injection |
| `f4-ssrf.patch` | `network/proxy.py` (`network`) | fixed host replaced by user-supplied URL (allowlist + https pin gone) |
| `f5-race.patch` | `auth/invite.py` (`auth`) | atomic `UPDATE … WHERE used = 0` split into SELECT-then-UPDATE: one invite code redeemable twice under concurrency |
| `f6-crypto.patch` | `crypto/tokens.py` (`crypto`) | `compare_digest` kept but against `expected[:len(sig)]`: an empty signature verifies any payload |
| `f7-multifile-auth.patch` | `auth/decorators.py` + `auth/session.py` (`auth`) | `require_role` now tests `role in roles`, and unverified accounts get role `""`; the unchanged caller `api/admin.py` passes the string `"admin"`, and `"" in "admin"` is true — an unverified account reaches the admin route |

f1–f4 are the 2026-10-04 set: each bug is caught outright at default effort
(ceiling effect). f5–f7 are the discriminating follow-up: the bug hides behind
a safe-looking refactor (f5), a still-present safe primitive (f6), or a chain
that only closes through a file outside the diff (f7). f7's repo also needs
`api/admin.py` (identical in `base/` and `vuln/`) so the reviewer can read the
caller. For f7, recall requires the full chain (unverified account reaches
`/admin/purge`); a finding on either half alone is scored partial.

## Re-run

Each fixture is a `base/` + `vuln/` file pair at the same repo-relative path
(the `.patch` files are the same diffs, for quick reading). For a recall run,
per fixture, copy only that fixture's file(s) into a throwaway repo — e.g. for
f1, `base/auth/middleware.py` then `vuln/auth/middleware.py` — commit after
each copy, point a `base` branch at the clean commit, then from that repo run
`claude-review.sh` twice — default and high effort:

```bash
REVIEW_SH="<repo>/dev/skills/task-review-cycle/scripts/claude-review.sh"
bash "$REVIEW_SH" base ""      # default effort
bash "$REVIEW_SH" base "high"  # high effort
```

Score recall (planted bug reported at P0/P1 with a failure demo) and false
positives mechanically: FP = a finding on a line the patch did not add
(strict-line rule — reproducible without judgment; a finding that describes
the planted bug but cites a context line is annotated, not silently
dropped). See `RESULTS.md` for the 2026-10-04 run.
