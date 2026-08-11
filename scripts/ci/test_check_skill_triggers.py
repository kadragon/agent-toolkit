#!/usr/bin/env python3
"""
Unit tests for check_skill_triggers.py — the Half-A trigger-fixture ranking gate.

Two load-bearing groups:

* ranking correctness — a stripped-of-distinctive-tokens description loses rank 1,
  a tie at rank 1 fails a positive, a negative that still ranks 1st fails, language
  mismatch is skipped not scored, a waived query is skipped with its reason echoed;
* fail-closed discovery — zero skills, a malformed/non-array/non-UTF-8 fixture, a
  fixture whose scorable positives number 0.

Fixture repos are staged with `git add` (never committed), so `git ls-files` sees
them without tripping the repo's commit-message hook.

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


def skill_md(name: str, description: str) -> str:
    return f"---\nname: {name}\ndescription: {json.dumps(description)}\n---\n\n# {name}\n"


def run_report(root: Path) -> tuple[list, bool]:
    return mod.build_report(root)


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
            "a skill directory with no evals/ at all is silently fine (ratchet is a later ticket)",
            not failed,
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
    test_real_repo_shape()

    total = len(_results)
    passed = sum(_results)
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
