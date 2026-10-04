# 2026-10-04 run — default vs high effort on the security path

Question: does `EFFORT=high` on a `SECURITY_HIT` diff catch planted bugs that
default effort misses, or cost fewer false positives? The Opus 5.5 guide claim
(one early tester: lowest effort out-found high effort with fewer false
alarms) is cross-model anecdote, not same-effort evidence, so this run tests
the rule directly.

Method: 4 throwaway repos, each one clean commit + one vuln commit (this
directory's `base/`/`vuln/` pairs), `base` branch on the clean commit.
`claude-review.sh base ""` and `claude-review.sh base "high"` per fixture —
8 headless reviews, all exit 0, all outputs parseable JSON arrays.
Model: the `claude` CLI default on 2026-10-04 (not pinned — a re-run limit).

| Fixture | Planted bug | Default | High |
|---|---|---|---|
| f1 auth bypass | `?debug=true` → admin | P0 conf 100 + failure demo (2 findings) | P0 conf 100 + failure demo (2 findings) |
| f2 secret leak | `SECRET_KEY` logged | P0 conf 98 + failure demo (2 findings) | P0 conf 98 + failure demo (3 findings) |
| f3 cmd injection | `shell=True` f-string | P0 conf 100 + failure demo (3 findings) | P0 conf 100 + failure demo (3 findings) |
| f4 SSRF | allowlist removed | P0 conf 98 + failure demo (5 findings) | P0 conf 98 + failure demo (5 findings) |

Recall: 4/4 at both efforts — every planted bug caught at P0, confidence
98–100, each with a concrete failure demo. No empty `failure` fields.
Finding counts: identical except f2-high (+1 P1 conf 70, `SECRET_KEY.encode()`
inside the `try` — a defensible robustness note in the same bug family, not
a false alarm either way).

## Decision (change only on evidence)

No measured recall gain and no false-positive difference on this set → the
`EFFORT="high"` rule in `SKILL.md` Step 2 / `references/risk-routing.md`
stays. Two limits keep this honest rather than exonerating: a ceiling effect
(default already catches these outright, so the set cannot separate the
efforts) and n=4 on an unpinned model. Revisit with subtler bugs (race,
crypto-misuse, multi-file auth flows) before touching the rule — the cost of
a missed security bug still outweighs the extra tokens on security diffs.

Fidelity note: the measured runs used files differing cosmetically from the
shipped pair — f3-vuln carried an extra unused `import os` no review flagged,
and all files have since been import-sorted (`ruff check` repo gate) with
`except Exception as exc:` → `except Exception:`. Every planted bug is
byte-identical in behavior; no finding in any run referenced imports or the
exception binding, so recall/FP tallies are unaffected.
