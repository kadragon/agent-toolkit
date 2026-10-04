# Security-effort fixtures

Fixture set for the `EFFORT=high`-on-`SECURITY_HIT` decision
(`../trigger-eval.json` holds trigger cases only; this directory holds the
recall experiment). Each `.patch` is a minimal diff that plants exactly one
known vulnerability in a clean file. Every fixture trips the `SECURITY_HIT`
capture in `../../references/risk-routing.md`, so each one represents the
diff class the `EFFORT="high"` rule fires on.

| Fixture | File (trips `SECURITY_HIT` via) | Planted bug |
|---|---|---|
| `f1-auth.patch` | `auth/middleware.py` (`auth`) | `?debug=true` skips token check, grants admin |
| `f2-secret.patch` | `secret_store.py` (`secret`) | `except` handler logs `SECRET_KEY` in plaintext |
| `f3-cmdinj.patch` | `network_fetcher.py` (`network`) | `shell=True` f-string command injection |
| `f4-ssrf.patch` | `network/proxy.py` (`network`) | allowlist removed, user URL fetched directly |

## Re-run

Each fixture is a `base/` + `vuln/` file pair at the same repo-relative path
(the `.patch` files are the same diffs, for quick reading). For a recall run,
per fixture: copy `base/` into a throwaway repo, commit, overlay `vuln/`,
commit, point a `base` branch at the clean commit, then from that repo run
`claude-review.sh` twice — default and high effort:

```bash
REVIEW_SH="<repo>/dev/skills/task-review-cycle/scripts/claude-review.sh"
bash "$REVIEW_SH" base ""      # default effort
bash "$REVIEW_SH" base "high"  # high effort
```

Score recall (planted bug reported at P0/P1 with a failure demo) and false
positives (findings on non-planted lines). See `RESULTS.md` for the
2026-10-04 run.
