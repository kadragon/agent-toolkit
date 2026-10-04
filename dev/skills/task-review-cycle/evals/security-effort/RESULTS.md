# 2026-10-04 run — default vs high effort on the security path

Question: does `EFFORT=high` on a `SECURITY_HIT` diff catch planted bugs that
default effort misses, or cost fewer false positives? The user-cited Opus 5.5
guide passage reads, verbatim:

> One early tester said Opus 5.5 at its lowest effort caught more bugs than
> Opus 5 at high effort, with fewer false alarms.

(source: https://claude.dev/blog/getting-the-most-out-of-opus-5-5/ §3
"Ask it to review the code"). That is cross-model anecdote from a single
tester, not same-effort evidence, so this run tests the rule directly.

Method: 4 throwaway repos, each one clean commit + one vuln commit built
from this directory's shipped `base/`/`vuln/` pairs (one pair per repo),
`base` branch on the clean commit. `claude-review.sh base ""` and
`claude-review.sh base "high"` per fixture — 8 headless reviews, all exit 0,
all outputs parseable JSON arrays, kept in `runs/`. Raw outputs are the
record; the table below is the scoring. Model: the `claude` CLI default on
2026-10-04 (not pinned — a re-run limit). A first run used files differing
cosmetically (unsorted imports, an extra unused `import os` in f3-vuln,
`except Exception as exc:`); no finding in any run referenced those lines,
and the run below re-measures the shipped bytes, so the fidelity question
is settled by measurement, not by argument.

FP definition (from `README.md`): a finding that does not describe the
planted bug or its direct consequences. Restatements of the same bug and
same-line consequences count as recall, not FP.

| Fixture | Planted bug | Default: recall / FP / total | High: recall / FP / total |
|---|---|---|---|
| f1 auth bypass | `?debug=true` → admin | P0 conf 100 + demo / 0 / 2 | P0 conf 100 + demo / 0 / 2 |
| f2 secret leak | `SECRET_KEY` logged | P0 conf 95 + demo / 0 / 3 | P0 conf 100 + demo / 0 / 4 |
| f3 cmd injection | `shell=True` f-string | P0 conf 100 + demo / 0 / 4 | P0 conf 100 + demo / 0 / 3 |
| f4 SSRF | fixed host → user URL | P0 conf 100 + demo / 0 / 6 | P0 conf 100 + demo / 0 / 4 |

Recall: 8/8 — every planted bug caught at P0, confidence 95–100, each with
a concrete failure demo. No empty `failure` fields. FP: 0 in all 8 cells.
Totals (verbosity) vary 2–6 with no effort pattern (default 15, high 13).

## Decision (change only on evidence)

No measured recall gain and no false-positive difference on this set → the
`EFFORT="high"` rule in `SKILL.md` Step 2 / `references/risk-routing.md`
stays. Two limits keep this honest rather than exonerating: a ceiling effect
(default already catches these outright, so the set cannot separate the
efforts) and n=4 on an unpinned model. The discriminating follow-up (subtler
bugs: race, crypto misuse, multi-file auth flows) is queued in `backlog.md`
— revisit there before touching the rule. The cost of a missed security bug
still outweighs the extra tokens on security diffs.
