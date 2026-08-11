#!/usr/bin/env python3
"""
Unit tests for check_skill_triggers.py — the Half-A trigger-fixture ranking gate.

Two load-bearing groups:

* ranking correctness — a stripped-of-distinctive-tokens description loses rank 1,
  a tie at rank 1 fails a positive, a negative that still ranks 1st fails, language
  mismatch is skipped not scored, a waived query is skipped with its reason echoed;
* fail-closed discovery — zero skills, a malformed/non-array/non-UTF-8 fixture, a
  fixture whose scorable positives number 0;
* the ratchet — a changed SKILL.md without a fixture fails and is named, one with a
  fixture passes, an untouched fixture-less skill is not flagged, a deletion is not
  flagged, an unresolvable diff base skips instead of failing locally, and that same
  state FAILS under `GITHUB_ACTIONS=true`.

Fixture repos are staged with `git add` (never committed), so `git ls-files` sees
them without tripping the repo's commit-message hook. The ratchet needs real commits
and an `origin/main` ref, so those cases use `make_repo_with_base` instead; it commits
with `--no-verify` and a neutralized `core.hooksPath` so a global hooks directory
cannot reach into the throwaway repo.

Run: python3 scripts/ci/test_check_skill_triggers.py
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "check_skill_triggers.py"
spec = importlib.util.spec_from_file_location("check_skill_triggers", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_repo(tmp: Path, files: dict) -> Path:
    """Stage `files` (path -> text, or path -> bytes) in a throwaway git repo."""
    root = tmp
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            # `--no-verify` does NOT cover signing: with a global
            # `commit.gpgsign=true` these fixture commits would fail before any
            # ratchet assertion runs.
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            *args,
        ],
        cwd=root,
        check=True,
    )


def make_repo_with_base(tmp: Path, base_files: dict, head_files: dict) -> Path:
    """Build a repo with a real `origin/main` base commit and a HEAD commit on top.

    `base_files` is committed and pointed at by `refs/remotes/origin/main`; then
    `head_files` is applied (a `None` value deletes the path) and committed, so
    `git diff origin/main...HEAD` reports exactly the intended change set.
    """
    root = tmp
    _git(root, "init", "-q")
    for rel, content in base_files.items():
        write(root, rel, content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--no-verify", "-m", "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")

    for rel, content in head_files.items():
        if content is None:
            (root / rel).unlink()
        else:
            write(root, rel, content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--no-verify", "-m", "head")
    return root


def skill_md(name: str, description: str) -> str:
    return f"---\nname: {name}\ndescription: {json.dumps(description)}\n---\n\n# {name}\n"


def run_report(root: Path, **kwargs) -> tuple[list, bool]:
    return mod.build_report(root, **kwargs)


def test_tokenize_and_class():
    print("\ntokenize / script class")
    check(
        "tokenizer splits latin and hangul runs",
        mod.tokenize("Hello 세계 42") == ["hello", "세계", "42"],
        str(mod.tokenize("Hello 세계 42")),
    )
    check("pure english classifies en", mod.script_class("hello world") == "en")
    check("pure korean classifies ko", mod.script_class("안녕하세요 세계") == "ko")
    check(
        "no letter characters at all defaults to en (no positive evidence of Korean)",
        mod.script_class("123 456 !!!") == "en",
    )
    # Exactly at the 30% boundary: 3 hangul letters / 10 letters = 30% -> ko (>=).
    boundary = "가나다" + "abcdefg"
    ratio = 3 / 10
    check(
        "boundary case: hangul ratio computed as expected (sanity)",
        abs((3 / len([c for c in boundary if c.isalpha()])) - ratio) < 1e-9,
    )
    check("30% hangul ratio classifies ko (>= threshold)", mod.script_class(boundary) == "ko")
    below = "가나" + "abcdefghij"  # 2/12 = 16.7% < 30%
    check("below-threshold hangul ratio classifies en", mod.script_class(below) == "en")


def test_corpus_ranking():
    print("\ncorpus ranking")
    corpus = mod.Corpus(
        {
            "alpha": "manages widget inventory and warehouse restocking",
            "beta": "drafts marketing copy for social media campaigns",
            "gamma": "reviews pull requests for security vulnerabilities",
        }
    )
    ranked = corpus.rank(corpus.vectorize_query("restock the warehouse widget inventory"))
    check(
        "distinct-description corpus ranks the matching skill 1st",
        ranked[0][0] == "alpha",
        str(ranked),
    )

    oov = corpus.vectorize_query("xyzzy plugh quux")
    check(
        "query with entirely out-of-corpus tokens does not crash and yields empty vector",
        oov == {},
        str(oov),
    )
    ranked_oov = corpus.rank(oov)
    check(
        "ranking an empty query vector does not divide by zero",
        len(ranked_oov) == 3 and all(s == 0.0 for _, s in ranked_oov),
        str(ranked_oov),
    )


def test_ranking_regressions():
    print("\nfixture scoring — regressions from the design doc's Testing Decisions table")

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/marketing/SKILL.md": skill_md(
                    "marketing", "drafts marketing copy for social media campaigns"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "restock the warehouse widget inventory please",
                            "should_trigger": True,
                        },
                        {
                            "query": "write a social media campaign for our new widget",
                            "should_trigger": False,
                        },
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check("distinct-description corpus + matching positives passes", not failed, out)

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "helps with widget stuff generally"
                ),
                "dev/skills/marketing/SKILL.md": skill_md(
                    "marketing", "drafts marketing copy for social media campaigns"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "restock widget inventory using social media",
                            "should_trigger": True,
                        }
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "description stripped of its distinctive tokens fails (owning skill not rank 1)",
            failed and "not unambiguous rank 1" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/twin-a/SKILL.md": skill_md(
                    "twin-a", "handles customer support tickets and refunds"
                ),
                "dev/skills/twin-b/SKILL.md": skill_md(
                    "twin-b", "handles customer support tickets and refunds"
                ),
                "dev/skills/twin-a/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "process a customer refund ticket",
                            "should_trigger": True,
                        }
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "positive query tying at rank 1 between two skills fails",
            failed and "tie at rank 1" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/marketing/SKILL.md": skill_md(
                    "marketing", "drafts marketing copy for social media campaigns"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "restock the warehouse widget inventory please",
                            "should_trigger": True,
                        },
                        {
                            "query": "restock our warehouse widget inventory today",
                            "should_trigger": False,
                        },
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "negative query that ranks the owning skill 1st fails",
            failed and "ranked 1st" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/marketing/SKILL.md": skill_md(
                    "marketing", "drafts marketing copy for social media campaigns"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "재고 창고를 다시 채워줘",
                            "should_trigger": True,
                        },
                        {
                            "query": "restock the warehouse widget inventory please",
                            "should_trigger": True,
                        },
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "korean query against an english description is skipped and counted, not scored",
            not failed and "skipped-by-language=1" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "재고 창고를 다시 채워줘",
                            "should_trigger": True,
                        }
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "fixture whose scorable positives number 0 fails (vacuous-fixture floor)",
            failed
            and "0 scorable positive queries" in out
            and "dev/skills/inventory/evals/trigger-eval.json" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/marketing/SKILL.md": skill_md(
                    "marketing", "drafts marketing copy for social media campaigns"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "restock the warehouse widget inventory please",
                            "should_trigger": True,
                        },
                        {
                            "query": "some unscoreable phrasing nobody would type",
                            "should_trigger": True,
                            "waived": "lexical proxy can't disambiguate this idiom",
                        },
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            'a "waived": "reason" query is skipped with the reason echoed',
            not failed
            and "waived=1" in out
            and "lexical proxy can't disambiguate this idiom" in out,
            out,
        )

    # Amendment 1 — a query with zero corpus-token overlap is unscoreable, not a
    # failure. Regression: `rank()` scored a degenerate all-zero universal tie,
    # and the negative path's "any tie at rank 1" rule then failed it as "ranked
    # 1st (score=0.0000)" even though there was no signal at all.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/marketing/SKILL.md": skill_md(
                    "marketing", "drafts marketing copy for social media campaigns"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "restock the warehouse widget inventory please",
                            "should_trigger": True,
                        },
                        {
                            "query": "xyzzy plugh quux corge grault",
                            "should_trigger": False,
                        },
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "negative query with zero corpus-token overlap is skipped as "
            "unscorable, counted, and does not fail the run",
            not failed
            and "unscorable=1" in out
            and "SKIP (unscorable) 'xyzzy plugh quux corge grault'" in out
            and "ranked 1st" not in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/marketing/SKILL.md": skill_md(
                    "marketing", "drafts marketing copy for social media campaigns"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "restock the warehouse widget inventory please",
                            "should_trigger": True,
                        },
                        {
                            "query": "xyzzy plugh quux corge grault",
                            "should_trigger": True,
                        },
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "positive query with zero corpus-token overlap is skipped as "
            "unscorable and not counted toward the scorable-positive tally",
            not failed
            and "unscorable=1" in out
            and "coverage: positives 1/2 scorable" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "xyzzy plugh quux corge grault",
                            "should_trigger": True,
                        }
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "a fixture whose only positive is zero-overlap still fails the "
            "vacuous-positive floor",
            failed
            and "0 scorable positive queries" in out
            and "dev/skills/inventory/evals/trigger-eval.json" in out,
            out,
        )

    for label, bad_content in [
        ("malformed JSON", "{not valid json"),
        ("non-array JSON", json.dumps({"query": "x", "should_trigger": True})),
        ("non-UTF-8 bytes", b"\xff\xfe not utf-8 at all"),
        (
            "bad element shape (missing query)",
            json.dumps([{"should_trigger": True}]),
        ),
        (
            "bad element shape (missing should_trigger)",
            json.dumps([{"query": "restock the widgets"}]),
        ),
    ]:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(
                Path(tmp),
                {
                    "dev/skills/inventory/SKILL.md": skill_md(
                        "inventory", "manages widget inventory and warehouse restocking"
                    ),
                    "dev/skills/inventory/evals/trigger-eval.json": bad_content,
                },
            )
            lines, failed = run_report(root)
            out = "\n".join(lines)
            check(
                f"malformed fixture ({label}) fails with the path named",
                failed and "dev/skills/inventory/evals/trigger-eval.json" in out,
                out,
            )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(Path(tmp), {"docs/notes.md": "# nothing shipped here\n"})
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "discovery finding zero skills fails closed",
            failed and "discovery found zero skills" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "a skill directory with no evals/ at all is fine when no diff base exists "
            "(ratchet skips)",
            not failed,
            out,
        )


def test_fail_closed_discovery_edges():
    print("\nfail-closed discovery edges — duplicate names, parse errors, BOM, waived shape")

    # F1 — two skills declaring the same `name:` in different plugin roots must fail
    # closed and name both paths, not silently let the later one win.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/dup/SKILL.md": skill_md("dup", "does a thing in dev"),
                "prod/skills/dup/SKILL.md": skill_md("dup", "does a thing in prod"),
                "dev/skills/other/SKILL.md": skill_md(
                    "other", "manages widget inventory and warehouse restocking"
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "duplicate skill name across plugin roots fails and names both paths",
            failed
            and "duplicate skill name" in out
            and "dev/skills/dup/SKILL.md" in out
            and "prod/skills/dup/SKILL.md" in out,
            out,
        )

    # F2 — a frontmatter parse error must fail the run, not just print ERROR and
    # exit 0 (the skill's fixture, if any, is silently dropped from scoring).
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/broken/SKILL.md": "no frontmatter here at all\n",
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "a frontmatter parse error fails the run, not just prints ERROR",
            failed and "ERROR dev/skills/broken/SKILL.md" in out and "not be scored" in out,
            out,
        )

    # F7 — a leading UTF-8 BOM must be a parse error, mirroring
    # check_skill_frontmatter.py's split_frontmatter, not silently stripped.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/bommed/SKILL.md": (
                    "﻿" + skill_md("bommed", "does a bommed thing")
                ),
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "a leading UTF-8 BOM is treated as a parse error (fails, not stripped)",
            failed and "ERROR dev/skills/bommed/SKILL.md" in out and "BOM" in out,
            out,
        )

    # F3 — a waived entry without a boolean `should_trigger` is malformed, not
    # silently skipped.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [{"query": "restock the widgets", "waived": "some reason"}]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "a waived entry missing `should_trigger` is rejected as malformed",
            failed and "missing a boolean `should_trigger`" in out,
            out,
        )

    # F3 — an empty or whitespace-only `waived` reason is malformed.
    for label, reason in [("empty", ""), ("whitespace-only", "   ")]:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(
                Path(tmp),
                {
                    "dev/skills/inventory/SKILL.md": skill_md(
                        "inventory", "manages widget inventory and warehouse restocking"
                    ),
                    "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                        [
                            {
                                "query": "restock the widgets",
                                "should_trigger": True,
                                "waived": reason,
                            }
                        ]
                    ),
                },
            )
            lines, failed = run_report(root)
            out = "\n".join(lines)
            check(
                f"a `waived` reason that is {label} is rejected as malformed",
                failed and "non-empty, non-whitespace string" in out,
                out,
            )

    # F8 — the vacuous-floor message must name the unscorable cause when that is
    # what actually consumed the positives, not just "language or waived".
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": skill_md(
                    "inventory", "manages widget inventory and warehouse restocking"
                ),
                "dev/skills/inventory/evals/trigger-eval.json": json.dumps(
                    [
                        {
                            "query": "xyzzy plugh quux corge grault",
                            "should_trigger": True,
                        }
                    ]
                ),
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "vacuous-floor message names the unscorable cause, not just language/waived",
            failed
            and "0 scorable positive queries" in out
            and "unscorable" in out,
            out,
        )


# Queries are written against the tokens the descriptions below actually carry — this
# fixture exists to satisfy the ratchet, so it must not fail the *ranking* half and
# leave R2 unable to tell the two failure sources apart.
GOOD_FIXTURE = json.dumps(
    [
        {"query": "warehouse inventory restocking", "should_trigger": True},
        {"query": "rotate credentials on the cluster nodes", "should_trigger": False},
    ]
)

# A second skill so the corpus is never a single document (idf collapses at N=1) and so
# the ratchet's diff scope can be told apart from a repo-wide fixture mandate.
OTHER_SKILL = skill_md("shipping", "deploy the cluster nodes and rotate credentials")


def test_ratchet():
    print("\nratchet — changed SKILL.md must leave its skill with a fixture")

    inventory = skill_md("inventory", "manages widget inventory and warehouse restocking")
    inventory_v2 = skill_md(
        "inventory", "manages widget inventory, warehouse restocking and reordering"
    )

    # R1 — the core rule: a changed SKILL.md with no fixture fails, naming the skill
    # AND the fixture path the author has to create.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo_with_base(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": inventory,
                "dev/skills/shipping/SKILL.md": OTHER_SKILL,
            },
            {"dev/skills/inventory/SKILL.md": inventory_v2},
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "a changed SKILL.md with no fixture fails, naming the skill and the fixture path",
            failed
            and "'inventory'" in out
            and "dev/skills/inventory/evals/trigger-eval.json" in out
            and "changed on this branch" in out,
            out,
        )
        check(
            "the ratchet failure does not flag the untouched fixture-less skill",
            "shipping" not in out.split("Ratchet:")[-1],
            out,
        )

    # R2 — a changed SKILL.md that already carries a fixture satisfies the ratchet.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo_with_base(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": inventory,
                "dev/skills/inventory/evals/trigger-eval.json": GOOD_FIXTURE,
                "dev/skills/shipping/SKILL.md": OTHER_SKILL,
            },
            {"dev/skills/inventory/SKILL.md": inventory_v2},
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "a changed SKILL.md that has a fixture passes the ratchet",
            not failed and "OK   dev/skills/inventory/SKILL.md" in out,
            out,
        )

    # R3 — scope is the diff, not the repo: touching an unrelated file must not demand
    # fixtures for the 12 skills that have none.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo_with_base(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": inventory,
                "dev/skills/shipping/SKILL.md": OTHER_SKILL,
                "docs/notes.md": "before\n",
            },
            {"docs/notes.md": "after\n"},
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "an untouched fixture-less skill is not flagged (ratchet is diff-scoped)",
            not failed and "nothing to require" in out,
            out,
        )

    # R4 — a deleted SKILL.md is a removed skill; demanding a fixture for it would be
    # unsatisfiable, so `--diff-filter=d` must exclude it.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo_with_base(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": inventory,
                "dev/skills/shipping/SKILL.md": OTHER_SKILL,
            },
            {"dev/skills/inventory/SKILL.md": None},
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "a deleted SKILL.md does not trip the ratchet",
            not failed and "nothing to require" in out,
            out,
        )

    # R5 — no origin/main (fresh clone, no remote): skip with a NOTE, never fail.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/inventory/SKILL.md": inventory,
                "dev/skills/shipping/SKILL.md": OTHER_SKILL,
            },
        )
        lines, failed = run_report(root)
        out = "\n".join(lines)
        check(
            "an unresolvable diff base skips the ratchet with a NOTE instead of failing",
            not failed and "Ratchet: NOTE" in out and "unresolvable" in out,
            out,
        )

        # R6 — the same unresolvable state in CI is a lost `fetch-depth: 0`, i.e. a
        # silently disabled gate, so it must fail there. `require_diff_base` is passed
        # explicitly rather than via os.environ: this whole suite runs under
        # GITHUB_ACTIONS in CI, and an env read inside build_report would make every
        # fixture repo above (none of which has an origin/main) fail.
        lines, failed = run_report(root, require_diff_base=True)
        out = "\n".join(lines)
        check(
            "an unresolvable diff base FAILS when the base is required (CI); "
            "fail-open is local-only",
            failed and "FAIL Ratchet" in out and "fetch-depth: 0" in out,
            out,
        )


def test_real_repo_shape():
    print("\nreal-repo sanity (invoked against this repo's own root)")
    root = mod.REPO_ROOT
    files = mod.list_skill_files(root)
    check("real repo discovers at least one skill", len(files) > 0, str(len(files)))


def main():
    test_tokenize_and_class()
    test_corpus_ranking()
    test_ranking_regressions()
    test_fail_closed_discovery_edges()
    test_ratchet()
    test_real_repo_shape()

    total = len(_results)
    passed = sum(_results)
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
