#!/usr/bin/env python3
"""Deterministic trigger-fixture ranking check (Half A of the trigger/collision spec).

Guards a silent failure mode one level above `check_skill_frontmatter.py`: a
`description:` that parses fine and passes that check but no longer carries tokens
distinctive enough to win the queries it claims to answer. Nothing today scores
`docs/eval-criteria.md`'s Trigger Accuracy criterion (weight 30%) mechanically —
`prod/skills/persona-debate/evals/trigger-eval.json` holds 20 declared cases and no
job reads it. See `docs/design/skill-trigger-collision-check.md` for the full spec;
this script implements only Half A (fixture ranking). Half B (pairwise collision) is
a separate ticket.

**What this establishes.** A TF-IDF/cosine ranker is a lexical *proxy* for the
model-judged router `skill-creator`'s `run_eval.py` performs. It scores a
**necessary condition** — that the owning skill's description carries tokens
distinctive enough to win its own declared queries — never a sufficient one.
Passing this check does not certify that a skill fires correctly in practice.

Algorithm (measured against the real repo; see the ticket that added this file for
the reference numbers):

- Corpus = every discovered skill's `description:` string.
- Tokenizer: `[a-z0-9]+|[가-힣]+` on the lowercased string.
- tf = 1 + log(count); idf = log((N+1)/(df+1)) + 1 (smoothed, like sklearn's
  `TfidfVectorizer(sublinear_tf=True)`); vectors L2-normalized; cosine = dot product
  of normalized vectors.
- Query vectors are restricted to in-corpus tokens (out-of-corpus tokens dropped,
  never crash, never divide by zero — an empty resulting vector scores 0.0 against
  every description). A query whose vector is empty this way is **unscoreable**: it
  carries zero corpus-token overlap, so `rank()` would report a universal all-zero
  tie with no ranking signal, not a genuine ambiguity. Skipped and counted under its
  own label, distinct from the language skip and the waiver skip — for positive and
  negative queries alike.
- Script class — `ko` when Hangul characters are >= 30% of a string's letter
  characters, else `en` (a string with zero letters defaults to `en`, since there is
  no positive evidence of Korean). A query is scored only when its class matches the
  owning skill's description class; mismatches are skipped and counted, never scored
  as a failure — token overlap between mismatched scripts is uninformative noise
  (measured: persona-debate's Korean queries score ~0 against every one of the 13
  English descriptions alike).

Pass bar:

- `should_trigger: true` passes only if the owning skill ranks 1st with no tie at
  rank 1 (`docs/eval-criteria.md` asks for the *unambiguous* best match).
- `should_trigger: false` passes only if the owning skill does not rank 1st.
- A query carrying `"waived": "<reason>"` is skipped (not scored); the reason is
  echoed in the report so a proxy false negative never pressures the gate itself.
- A fixture must yield >= 1 scorable *positive* query (vacuous-fixture floor) — no
  floor is imposed on negatives yet (persona-debate currently has 0 scorable
  negatives; see the design doc's §4). Unscoreable queries (zero corpus-token
  overlap) never count toward this tally — a fixture whose only positive is
  unscoreable still fails the floor, correctly, since it covers nothing.

Usage: python3 scripts/ci/check_skill_triggers.py
Exit: 0 if every scored query and every fixture's floor passes, 1 on any violation
(including discovery finding zero skills, or a malformed fixture), 2 if PyYAML is
unavailable. Always prints a full report before the verdict.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard, not logic
    print(
        "ERROR: PyYAML required — this check parses `description:` frontmatter at "
        "the loader's strictness.\n"
        "  CI:    pip install pyyaml\n"
        "  local: python3 -m venv .venv && .venv/bin/pip install pyyaml "
        "(system python3 is PEP 668 externally-managed on macOS)",
        file=sys.stderr,
    )
    sys.exit(2)

REPO_ROOT = Path(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
)

TOKEN_RE = re.compile(r"[a-z0-9]+|[가-힣]+")
KO_THRESHOLD = 0.30
TIE_EPSILON = 1e-9


def list_skill_files(root: Path) -> list[Path]:
    tracked = subprocess.check_output(
        ["git", "-c", "core.quotePath=false", "ls-files", "--", "*/skills/*/SKILL.md"],
        text=True,
        cwd=root,
    ).splitlines()
    return sorted(root / rel for rel in tracked)


def parse_description(path: Path) -> tuple[str | None, str | None, str | None]:
    """Return (name, description, error). error is set (name/description None) on failure.

    Frontmatter *shape* validity is `check_skill_frontmatter.py`'s job; this parses
    just enough to get `name:`/`description:` and reports plainly if it cannot.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, None, f"could not read file: {exc}"

    lines = text.splitlines()
    if not lines or lines[0].strip().lstrip("﻿") != "---":
        return None, None, "no `---` frontmatter block to parse"
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, None, "frontmatter block never closed"

    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        return None, None, f"frontmatter failed to parse as YAML: {exc}"

    if not isinstance(data, dict):
        return None, None, "frontmatter is not a YAML mapping"

    name = data.get("name")
    description = data.get("description")
    if not isinstance(name, str) or not name.strip():
        return None, None, "missing or empty `name:`"
    if not isinstance(description, str) or not description.strip():
        return None, None, "missing or empty `description:`"
    return name.strip(), description.strip(), None


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def script_class(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    hangul = sum(1 for c in letters if "가" <= c <= "힣")
    return "ko" if (hangul / len(letters)) >= KO_THRESHOLD else "en"


def _term_counts(tokens: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tok in tokens:
        counts[tok] = counts.get(tok, 0) + 1
    return counts


def _l2_normalize(vec: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(w * w for w in vec.values()))
    if norm == 0.0:
        return {}
    return {tok: w / norm for tok, w in vec.items()}


class Corpus:
    """TF-IDF vector space built from the discovered descriptions."""

    def __init__(self, descriptions: dict[str, str]) -> None:
        self.descriptions = descriptions
        doc_tokens = {name: tokenize(text) for name, text in descriptions.items()}
        doc_counts = {name: _term_counts(toks) for name, toks in doc_tokens.items()}

        df: dict[str, int] = {}
        for counts in doc_counts.values():
            for tok in counts:
                df[tok] = df.get(tok, 0) + 1

        n_docs = len(descriptions)
        self.idf = {tok: math.log((n_docs + 1) / (d + 1)) + 1 for tok, d in df.items()}

        self.doc_vectors: dict[str, dict[str, float]] = {}
        for name, counts in doc_counts.items():
            raw = {
                tok: (1 + math.log(cnt)) * self.idf[tok] for tok, cnt in counts.items()
            }
            self.doc_vectors[name] = _l2_normalize(raw)

    def vectorize_query(self, text: str) -> dict[str, float]:
        counts = _term_counts(tokenize(text))
        raw = {
            tok: (1 + math.log(cnt)) * self.idf[tok]
            for tok, cnt in counts.items()
            if tok in self.idf  # out-of-corpus tokens dropped, never divide by zero
        }
        return _l2_normalize(raw)

    def rank(self, query_vec: dict[str, float]) -> list[tuple[str, float]]:
        scores = []
        for name, doc_vec in self.doc_vectors.items():
            common = query_vec.keys() & doc_vec.keys()
            dot = sum(query_vec[tok] * doc_vec[tok] for tok in common)
            scores.append((name, dot))
        scores.sort(key=lambda pair: pair[1], reverse=True)
        return scores


def load_fixture(path: Path) -> tuple[list | None, str | None]:
    """Return (entries, error). error is set (entries None) on any malformed shape."""
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return None, f"could not read fixture: {exc}"

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"fixture is not valid UTF-8: {exc}"

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"fixture is not valid JSON: {exc}"

    if not isinstance(data, list):
        return None, f"fixture is not a JSON array (parsed as {type(data).__name__})"

    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            return None, f"element [{i}] is not an object (got {type(entry).__name__})"
        query = entry.get("query")
        if not isinstance(query, str) or not query.strip():
            return None, f"element [{i}] missing a non-empty `query` string"
        waived = entry.get("waived")
        if waived is not None and not isinstance(waived, str):
            return None, f"element [{i}] `waived` must be a string"
        should_trigger = entry.get("should_trigger")
        if waived is None:
            if not isinstance(should_trigger, bool):
                return None, f"element [{i}] missing a boolean `should_trigger`"
        elif should_trigger is not None and not isinstance(should_trigger, bool):
            return None, f"element [{i}] `should_trigger` must be a boolean when present"

    return data, None


def build_report(root: Path) -> tuple[list[str], bool]:
    """Return (report lines, failed) for a repository root."""
    lines: list[str] = []
    failed = False

    skill_files = list_skill_files(root)
    if not skill_files:
        lines.append(
            "FAIL: discovery found zero skills (*/skills/*/SKILL.md). "
            "Either the pathspec regressed or this is not the plugin repo."
        )
        return lines, True

    descriptions: dict[str, str] = {}
    skill_dirs: dict[str, Path] = {}
    for path in skill_files:
        name, description, error = parse_description(path)
        rel = str(path.relative_to(root))
        if error:
            lines.append(
                f"ERROR {rel}: {error} — excluded from the ranking corpus "
                "(check_skill_frontmatter.py is the gate for this)"
            )
            continue
        descriptions[name] = description
        skill_dirs[name] = path.parent

    if not descriptions:
        lines.append("FAIL: no skill had a parsable `description:` — zero-size corpus.")
        return lines, True

    corpus = Corpus(descriptions)
    desc_class = {name: script_class(text) for name, text in descriptions.items()}

    lines.append(f"Corpus: {len(descriptions)} skill descriptions.")
    for name in sorted(descriptions):
        lines.append(f"  {name}: class={desc_class[name]}")
    lines.append("----")

    any_fixture = False
    for name in sorted(skill_dirs):
        fixture_path = skill_dirs[name] / "evals" / "trigger-eval.json"
        if not fixture_path.exists():
            continue
        any_fixture = True
        rel_fixture = str(fixture_path.relative_to(root))

        entries, error = load_fixture(fixture_path)
        if error:
            lines.append(f"ERROR {rel_fixture}: {error}")
            failed = True
            continue

        owning_class = desc_class[name]
        scored_pos_pass = scored_pos_fail = 0
        scored_neg_pass = scored_neg_fail = 0
        skipped_lang = 0
        skipped_unscorable = 0
        waived_count = 0
        total_pos = total_neg = 0
        detail_lines: list[str] = []

        for entry in entries:
            query = entry["query"]
            should_trigger = entry.get("should_trigger")
            if isinstance(should_trigger, bool):
                if should_trigger:
                    total_pos += 1
                else:
                    total_neg += 1

            waived_reason = entry.get("waived")
            if waived_reason is not None:
                waived_count += 1
                detail_lines.append(f"  WAIVED  {query!r} — {waived_reason}")
                continue

            if script_class(query) != owning_class:
                skipped_lang += 1
                continue

            query_vec = corpus.vectorize_query(query)
            if not query_vec:
                # Zero corpus-token overlap: rank() would score every skill at
                # exactly 0.0 — a universal all-zero tie with no ranking signal,
                # not a genuine ambiguity. Unscoreable, not a failure, for both
                # positive and negative queries alike.
                skipped_unscorable += 1
                detail_lines.append(
                    f"  SKIP (unscorable) {query!r} — zero corpus-token overlap"
                )
                continue

            ranked = corpus.rank(query_vec)
            top_score = ranked[0][1]
            top_names = [n for n, s in ranked if abs(s - top_score) < TIE_EPSILON]
            owner_rank1 = name in top_names and len(top_names) == 1

            if should_trigger:
                if owner_rank1:
                    scored_pos_pass += 1
                else:
                    scored_pos_fail += 1
                    tie_note = (
                        f" (tie at rank 1: {sorted(top_names)})"
                        if name in top_names and len(top_names) > 1
                        else f" (top: {ranked[0][0]}={ranked[0][1]:.4f})"
                    )
                    detail_lines.append(
                        f"  FAIL positive {query!r} — {name} not unambiguous rank 1"
                        f"{tie_note}"
                    )
                    failed = True
            else:
                owner_top1_any_tie = name in top_names
                if not owner_top1_any_tie:
                    scored_neg_pass += 1
                else:
                    scored_neg_fail += 1
                    detail_lines.append(
                        f"  FAIL negative {query!r} — {name} ranked 1st "
                        f"(score={top_score:.4f})"
                    )
                    failed = True

        scored_total = scored_pos_pass + scored_pos_fail + scored_neg_pass + scored_neg_fail
        lines.append(
            f"{name}  ({rel_fixture})\n"
            f"  scored={scored_total} "
            f"(positive pass={scored_pos_pass} fail={scored_pos_fail}, "
            f"negative pass={scored_neg_pass} fail={scored_neg_fail}) "
            f"skipped-by-language={skipped_lang} unscorable={skipped_unscorable} "
            f"waived={waived_count}\n"
            f"  coverage: positives {scored_pos_pass + scored_pos_fail}/{total_pos} scorable, "
            f"negatives {scored_neg_pass + scored_neg_fail}/{total_neg} scorable"
        )
        lines.extend(detail_lines)

        if scored_pos_pass + scored_pos_fail == 0:
            lines.append(
                f"FAIL {rel_fixture}: 0 scorable positive queries "
                "(vacuous-fixture floor — every positive was skipped by language or waived)"
            )
            failed = True

    if not any_fixture:
        lines.append(
            "No skill has an evals/trigger-eval.json yet — nothing to score "
            "(the ratchet requiring one is a separate ticket)."
        )

    lines.append("----")
    lines.append(
        "This check establishes a necessary condition only — that each fixture's "
        "scorable queries rank their owning skill correctly by lexical similarity. "
        "Passing does NOT certify a skill fires correctly in practice; "
        "skill-creator's model-judged runner is the semantic tier above it."
    )

    return lines, failed


def main() -> int:
    lines, failed = build_report(REPO_ROOT)
    for line in lines:
        print(line)

    if failed:
        print("FAIL: see ERROR/FAIL lines above.")
        return 1

    print("OK: all scorable trigger-fixture queries passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
