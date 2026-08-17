#!/usr/bin/env python3
"""
Unit tests for check_skill_frontmatter.py — the frontmatter validity gate.

Two load-bearing groups:

* per-file validation — the `plain scalar with a colon-space` shape that made
  `dev/skills/task-review/SKILL.md` load with empty metadata before PR #164;
* discovery — an asset with NO frontmatter, or with a UTF-8 BOM before `---`, must
  still be found and reported. Content-gated discovery would skip exactly those.

Fixture repos are staged with `git add` (never committed), so `git ls-files` sees them
without tripping the repo's commit-message hook.

Run: python3 scripts/ci/test_check_skill_frontmatter.py
"""

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "check_skill_frontmatter.py"
spec = importlib.util.spec_from_file_location("check_skill_frontmatter", SCRIPT)
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


def run_on(root: Path, rel: str, text: str) -> list[str]:
    """Write `text` at `root/rel` and return check_file()'s violations for it."""
    return mod.check_file(write(root, rel, text), root)


def make_repo(tmp: Path, files: dict[str, str]) -> Path:
    """Stage `files` in a throwaway git repo. `git add` only — no commit needed."""
    root = tmp
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for rel, text in files.items():
        write(root, rel, text)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def run_main(root: Path) -> tuple[int, str]:
    """Run main() against a fixture root, returning (exit code, stdout)."""
    original = mod.REPO_ROOT
    mod.REPO_ROOT = root
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = mod.main()
    finally:
        mod.REPO_ROOT = original
    return code, buf.getvalue()


VALID_SKILL = """---
name: task-review
description: >-
  Post-dev review cycle — commit → reviews (Claude + agy + Codex) → apply →
  retrospect → CI → merge. Flags: --no-hub (local only), --auto (skip
  confirmation).
---

# Dev Review Cycle
"""

# The pre-PR-#164 line, verbatim in shape: an unquoted scalar carrying `: `.
REGRESSION_SKILL = """---
name: task-review
description: Post-dev review cycle — commit → apply → merge. --no-hub: local only. --auto: skip confirmation.
---

# Dev Review Cycle
"""


def test_parsing(root):
    print("\nfrontmatter parsing")
    valid = run_on(root, "dev/skills/task-review/SKILL.md", VALID_SKILL)
    check("valid folded scalar passes", valid == [], str(valid))

    regression = run_on(root, "dev/skills/task-review/SKILL.md", REGRESSION_SKILL)
    check(
        "plain scalar with `: ` is rejected (PR #164 regression)",
        len(regression) == 1 and "failed to parse as YAML" in regression[0],
        str(regression),
    )

    unclosed = run_on(
        root, "dev/skills/unclosed/SKILL.md", "---\nname: unclosed\ndescription: x\n"
    )
    check(
        "unclosed frontmatter block is rejected",
        len(unclosed) == 1 and "never closed" in unclosed[0],
        str(unclosed),
    )

    not_mapping = run_on(root, "dev/skills/listy/SKILL.md", "---\n- a\n- b\n---\n")
    check(
        "non-mapping frontmatter is rejected",
        len(not_mapping) == 1 and "not a YAML mapping" in not_mapping[0],
        str(not_mapping),
    )

    no_fm = run_on(root, "dev/skills/nofm/SKILL.md", "# Just a heading\n")
    check(
        "asset with no frontmatter at all is rejected",
        len(no_fm) == 1 and "does not open with a `---`" in no_fm[0],
        str(no_fm),
    )

    bom = run_on(root, "dev/skills/bom/SKILL.md", "﻿---\nname: bom\ndescription: x\n---\n")
    check(
        "UTF-8 BOM before the delimiter is rejected",
        len(bom) == 1 and "UTF-8 BOM" in bom[0],
        str(bom),
    )


def test_required_keys(root):
    print("\nrequired keys")
    empty_desc = run_on(
        root, "dev/skills/empty/SKILL.md", '---\nname: empty\ndescription: ""\n---\n'
    )
    check(
        "empty description is rejected",
        len(empty_desc) == 1 and "is empty" in empty_desc[0],
        str(empty_desc),
    )

    missing_desc = run_on(root, "dev/skills/nodesc/SKILL.md", "---\nname: nodesc\n---\n")
    check(
        "missing description is rejected",
        len(missing_desc) == 1 and "missing required key" in missing_desc[0],
        str(missing_desc),
    )

    null_desc = run_on(
        root, "dev/skills/nullval/SKILL.md", "---\nname: nullval\ndescription:\n---\n"
    )
    check(
        "valueless `description:` is rejected as such, not as missing",
        len(null_desc) == 1 and "has no value" in null_desc[0],
        str(null_desc),
    )

    non_string = run_on(
        root, "dev/skills/listdesc/SKILL.md", "---\nname: listdesc\ndescription: [a]\n---\n"
    )
    check(
        "non-string description is rejected",
        len(non_string) == 1 and "must be a string" in non_string[0],
        str(non_string),
    )


def test_name_path_agreement(root):
    print("\nname/path agreement")
    mismatch = run_on(
        root, "dev/skills/renamed/SKILL.md", "---\nname: old-name\ndescription: x\n---\n"
    )
    check(
        "skill `name:` must match its directory",
        len(mismatch) == 1 and "does not match the path" in mismatch[0],
        str(mismatch),
    )

    agent_ok = run_on(
        root, "prod/agents/persona-actor.md", "---\nname: persona-actor\ndescription: x\n---\n"
    )
    check("agent `name:` matching its file stem passes", agent_ok == [], str(agent_ok))

    agent_bad = run_on(
        root, "prod/agents/persona-actor.md", "---\nname: other\ndescription: x\n---\n"
    )
    check(
        "agent `name:` mismatching its file stem is rejected",
        len(agent_bad) == 1 and "does not match the path" in agent_bad[0],
        str(agent_bad),
    )


def test_asset_shapes(root):
    print("\nasset-type shapes")
    command = run_on(
        root,
        "dev/commands/security-overview.md",
        '---\ndescription: "Scan alerts"\nallowed-tools: ["Bash"]\n---\n',
    )
    check("command without `name:` passes", command == [], str(command))

    design_doc = run_on(
        root, "docs/design/foo.md", "---\ntitle: Foo\nstatus: draft\n---\n\n# Foo\n"
    )
    check(
        "non-asset markdown is not held to asset keys",
        design_doc == [],
        str(design_doc),
    )

    broken_doc = run_on(
        root, "docs/design/bar.md", "---\ntitle: Bar --flag: oops\n---\n"
    )
    check(
        "non-asset markdown must still parse as YAML",
        len(broken_doc) == 1 and "failed to parse as YAML" in broken_doc[0],
        str(broken_doc),
    )

    print("\nclassification")
    check(
        "skill path classifies as skill",
        mod.classify("dev/skills/x/SKILL.md") == "skill",
        str(mod.classify("dev/skills/x/SKILL.md")),
    )
    check(
        "command path classifies as command",
        mod.classify("dev/commands/y.md") == "command",
        str(mod.classify("dev/commands/y.md")),
    )
    check(
        "agent path classifies as agent",
        mod.classify("prod/agents/z.md") == "agent",
        str(mod.classify("prod/agents/z.md")),
    )
    check(
        "unrelated markdown classifies as non-asset",
        mod.classify("docs/runbook.md") is None,
        str(mod.classify("docs/runbook.md")),
    )
    check(
        "a skill's references/*.md is not itself an asset",
        mod.classify("dev/skills/x/references/table.md") is None,
        str(mod.classify("dev/skills/x/references/table.md")),
    )


def test_discovery():
    print("\ndiscovery (fixture repos)")

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/good/SKILL.md": "---\nname: good\ndescription: fine\n---\n",
                "dev/skills/nofm/SKILL.md": "# no frontmatter here\n",
                "dev/skills/bom/SKILL.md": "﻿---\nname: bom\ndescription: x\n---\n",
            },
        )
        code, out = run_main(root)
        check(
            "asset with no frontmatter fails the run (not silently skipped)",
            code == 1 and "dev/skills/nofm/SKILL.md" in out,
            out,
        )
        check(
            "BOM asset fails the run (not silently skipped)",
            code == 1 and "dev/skills/bom/SKILL.md" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/good/SKILL.md": "---\nname: good\ndescription: fine\n---\n",
                "prod/agents/a.md": "---\nname: a\ndescription: d\n---\n",
                "dev/commands/c.md": "---\ndescription: d\n---\n",
                "docs/design/plain.md": "# no frontmatter, not an asset\n",
                "README.md": "---\ntitle: Readme\n---\n",
            },
        )
        code, out = run_main(root)
        check(
            "clean fixture passes with the right asset count",
            code == 0 and "OK: 3 plugin assets valid" in out,
            out,
        )
        check(
            "non-asset markdown without frontmatter is not reported at all",
            "docs/design/plain.md" not in out,
            out,
        )
        check(
            "non-asset markdown with frontmatter is reported but not key-checked",
            "OK   README.md (non-asset frontmatter)" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(Path(tmp), {"docs/notes.md": "# nothing shipped here\n"})
        code, out = run_main(root)
        check(
            "zero discovered assets fails closed",
            code == 1 and "discovery found zero plugin assets" in out,
            out,
        )




# --- invocation axis (docs/invocation.md) ------------------------------------

LOCKED_SKILL = """---
name: task-review
description: Post-dev review cycle for this branch.
disable-model-invocation: true
---

# Dev Review Cycle
"""

OPEN_SKILL = """---
name: task-grill
description: Resolve material ambiguity by interviewing the user.
---

# To Grill
"""

SIDECAR_LOCKED = 'interface:\n  display_name: "Review"\npolicy:\n  allow_implicit_invocation: false\n'


def axis_repo(tmp: Path, extra: dict) -> Path:
    """A minimal coherent repo: one locked skill with its sidecar, one open skill."""
    files = {
        "dev/skills/task-review/SKILL.md": LOCKED_SKILL,
        "dev/skills/task-review/agents/openai.yaml": SIDECAR_LOCKED,
        "dev/skills/task-grill/SKILL.md": OPEN_SKILL,
    }
    files.update(extra)
    return make_repo(tmp, files)


def test_axis_coherence():
    print("\naxis coherence")
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run_main(axis_repo(Path(tmp), {}))
        check("coherent tree passes", code == 0 and "both platform halves agree" in out, out)

    with tempfile.TemporaryDirectory() as tmp:
        # Claude half only — the sidecar is simply absent.
        root = make_repo(Path(tmp), {"dev/skills/task-review/SKILL.md": LOCKED_SKILL})
        code, out = run_main(root)
        check(
            "Claude-only lock fails",
            code == 1 and "its Codex half does not match" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        # Codex half only.
        root = make_repo(
            Path(tmp),
            {
                "dev/skills/task-grill/SKILL.md": OPEN_SKILL,
                "dev/skills/task-grill/agents/openai.yaml": SIDECAR_LOCKED,
            },
        )
        code, out = run_main(root)
        check(
            "Codex-only lock fails",
            code == 1 and "does not set `disable-model-invocation: true`" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = axis_repo(Path(tmp), {})
        (root / "dev/skills/task-review/agents/openai.yaml").write_text(
            "policy: [not, a, mapping\n", encoding="utf-8"
        )
        code, out = run_main(root)
        check(
            "unparseable sidecar fails rather than being skipped",
            code == 1 and "does not parse as YAML" in out,
            out,
        )


def test_call_graph():
    print("\ncall graph")
    caller = OPEN_SKILL + '\nCall the Skill tool with "dev:task-review" and `args: --auto`.\n'
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": caller}))
        check(
            "a MODEL-invoked caller naming a user-invoked skill fails",
            code == 1 and "names user-invoked skill `dev:task-review`" in out,
            out,
        )

    ok_caller = OPEN_SKILL + '\nCall the Skill tool with "dev:task-grill".\n'
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": ok_caller}))
        check("calling a model-invoked skill passes", code == 0, out)

    with tempfile.TemporaryDirectory() as tmp:
        ref = 'Hand off: call the Skill tool with "dev:task-review" and `args: --auto`.\n'
        code, out = run_main(
            axis_repo(Path(tmp), {"dev/skills/task-grill/references/tree.md": ref})
        )
        check(
            "a bundled reference file is scanned too, not just SKILL.md",
            code == 1 and "references/tree.md" in out,
            out,
        )


def test_notation():
    print("\nnotation")
    with tempfile.TemporaryDirectory() as tmp:
        body = OPEN_SKILL + "\nSee `Skill(dev:task-spec)` for the spec step.\n"
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": body}))
        check("residual Skill(ns:name) fails", code == 1 and "retired `Skill(ns:name)`" in out, out)

    with tempfile.TemporaryDirectory() as tmp:
        marked = OPEN_SKILL + (
            "\n<!-- notation-exempt: label a hook prints, not a call -->\n"
            "See `Skill(dev:task-spec)` for the spec step.\n"
        )
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": marked}))
        check("a marker on the line above exempts the site", code == 0, out)

    with tempfile.TemporaryDirectory() as tmp:
        fenced = OPEN_SKILL + (
            "\n<!-- notation-exempt: emitted string, not a call -->\n"
            "```json\n"
            '{"instruction": "Use Skill(dev:task-spec) to run it"}\n'
            "```\n"
        )
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": fenced}))
        check("a marker above a fence covers the code inside it", code == 0, out)

    with tempfile.TemporaryDirectory() as tmp:
        # Router prose with no namespace is outside the rule by construction.
        router = OPEN_SKILL + "\nThe hook emits `Use Skill(X)` on match.\n"
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": router}))
        check("namespace-less `Skill(X)` is not flagged", code == 0, out)

    with tempfile.TemporaryDirectory() as tmp:
        fm_marked = (
            "---\nname: task-grill\n"
            "description: Callable from other skills via `Skill(dev:task-grill)`.\n"
            "# notation-exempt: description text, decided separately\n---\n\n# To Grill\n"
        )
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": fm_marked}))
        check("a frontmatter marker covers the key block above it", code == 0, out)

    with tempfile.TemporaryDirectory() as tmp:
        # One justified exemption must not launder a second, unmarked violation
        # sitting under a different key in the same frontmatter block.
        two_keys = (
            "---\nname: task-grill\n"
            "description: Callable from other skills via `Skill(dev:task-grill)`.\n"
            "# notation-exempt: description text, decided separately\n"
            "when_to_use: see `Skill(dev:task-review)` for the review step\n"
            "---\n\n# To Grill\n"
        )
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": two_keys}))
        check(
            "a marker does NOT exempt an unmarked violation under another key",
            code == 1 and "SKILL.md:5 uses" in out and "SKILL.md:3 uses" not in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        # An indented `#` is a continuation line of the folded scalar above it: YAML
        # folds it into the description the loader reads, so honouring it as a marker
        # would both leak the marker text and exempt the line it sits in.
        indented = (
            "---\nname: task-grill\n"
            "description: >-\n"
            "  text with `Skill(dev:task-review)`\n"
            "  # notation-exempt: indented, so not a marker\n"
            "  more text\n"
            "---\n\n# To Grill\n"
        )
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": indented}))
        check(
            "an indented marker inside a folded scalar is not honoured",
            code == 1 and "retired `Skill(ns:name)`" in out,
            out,
        )


def test_pre_migration_tree_fails():
    """The item's own acceptance bar: the checks must reject the shape the repo had
    before the invocation-axis migration — all three violations at once."""
    print("\npre-migration tree")
    pre_caller = (
        "---\nname: task-next\ndescription: Pull the next queued item.\n---\n\n"
        "Invoke `Skill(dev:task-review)` with `args: --auto`.\n"
        'Call the Skill tool with "dev:task-review" and `args: --auto`.\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(
            Path(tmp),
            {
                # user-invoked in Claude, no Codex sidecar
                "dev/skills/task-review/SKILL.md": LOCKED_SKILL,
                "dev/skills/task-next/SKILL.md": pre_caller,
            },
        )
        code, out = run_main(root)
        check("pre-migration tree exits non-zero", code == 1, out)
        check("  ...on axis coherence", "its Codex half does not match" in out, out)
        check("  ...on the call graph", "names user-invoked skill" in out, out)
        check("  ...on notation", "retired `Skill(ns:name)`" in out, out)




def test_axis_flag_strictness():
    print("\nboolean strictness")
    with tempfile.TemporaryDirectory() as tmp:
        quoted = (
            "---\nname: task-review\ndescription: d\n"
            'disable-model-invocation: "true"\n---\n\n# x\n'
        )
        root = make_repo(Path(tmp), {"dev/skills/task-review/SKILL.md": quoted})
        code, out = run_main(root)
        check(
            "a quoted `\"true\"` fails instead of reading as unlocked",
            code == 1 and "is not a YAML boolean" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = axis_repo(Path(tmp), {})
        (root / "dev/skills/task-review/agents/openai.yaml").write_text(
            'policy:\n  allow_implicit_invocation: "false"\n', encoding="utf-8"
        )
        code, out = run_main(root)
        check(
            "a quoted sidecar boolean fails too",
            code == 1 and "is not a YAML boolean" in out,
            out,
        )


def test_call_graph_spellings():
    print("\ncall spellings")
    forms = {
        "backticked": "Call the Skill tool with `dev:task-review`.",
        "single-quoted": "Call the Skill tool with 'dev:task-review'.",
        "unquoted": "Call the Skill tool with dev:task-review now.",
        "target before the tool name": "Invoke dev:task-review via the Skill tool.",
        "wrapped across two lines": 'Call the Skill tool with\n"dev:task-review".',
    }
    for label, call in forms.items():
        with tempfile.TemporaryDirectory() as tmp:
            body = OPEN_SKILL + "\n" + call + "\n"
            code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": body}))
            check(f"{label} call is caught", code == 1 and "names user-invoked skill" in out, out)

    with tempfile.TemporaryDirectory() as tmp:
        two = OPEN_SKILL + (
            '\nCall the Skill tool twice, for "dev:task-grill" and "dev:task-review".\n'
        )
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": two}))
        check(
            "the SECOND target of a two-call line is checked",
            code == 1 and "dev:task-review" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        described = OPEN_SKILL + (
            "\n<!-- call-graph-exempt: states the rule, does not call it -->\n"
            'The Skill tool listing shows "dev:task-review" as user-invoked; never call it.\n'
        )
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": described}))
        check("a marked descriptive mention is not a call", code == 0, out)

    with tempfile.TemporaryDirectory() as tmp:
        other_ns = OPEN_SKILL + '\nCall the Skill tool with "other:task-review".\n'
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": other_ns}))
        check("a different namespace is a different skill", code == 0, out)


def test_marker_blast_radius():
    print("\nmarker blast radius")
    with tempfile.TemporaryDirectory() as tmp:
        # Opening fence on line 1 must not leave a stale intro that exempts the rest.
        leaky = "```\ncode notation-exempt: whatever\n```\n`Skill(dev:task-spec)` unmarked!\n"
        code, out = run_main(
            axis_repo(Path(tmp), {"dev/skills/task-grill/references/r.md": leaky})
        )
        check(
            "a leading fence does not exempt the rest of the file",
            code == 1 and "retired `Skill(ns:name)`" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        prose = OPEN_SKILL + (
            "\nMark such a site `notation-exempt: <reason>` to opt out.\n"
            "`Skill(dev:task-spec)` here is NOT exempt.\n"
        )
        code, out = run_main(axis_repo(Path(tmp), {"dev/skills/task-grill/SKILL.md": prose}))
        check(
            "prose describing the marker is not itself a marker",
            code == 1 and "retired `Skill(ns:name)`" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as tmp:
        agent = "---\nname: helper\ndescription: d\n---\n\nUse `Skill(dev:task-spec)` here.\n"
        code, out = run_main(axis_repo(Path(tmp), {"dev/agents/helper.md": agent}))
        check("agent definitions are scanned too", code == 1 and "dev/agents/helper.md" in out, out)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test_parsing(root)
        test_required_keys(root)
        test_name_path_agreement(root)
        test_asset_shapes(root)
    test_discovery()
    test_axis_coherence()
    test_call_graph()
    test_notation()
    test_pre_migration_tree_fails()
    test_axis_flag_strictness()
    test_call_graph_spellings()
    test_marker_blast_radius()

    total = len(_results)
    passed = sum(_results)
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
