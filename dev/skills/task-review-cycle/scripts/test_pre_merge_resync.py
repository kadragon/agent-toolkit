#!/usr/bin/env python3
"""Regression tests for pre_merge_resync.py on temp repos with a bare origin.

Two branches bump the same plugin (both manifests, a SKILL.md version line, a CHANGELOG
entry) from one base. The first merges; the second resyncs to the next patch number with
its CHANGELOG entry on that version, its other changes intact, pushed fast-forward, and then
merges too. A non-version conflict aborts with no push; missing `feature-push` authority
writes nothing; a multi-step bump stops.

Run: python3 dev/skills/task-review-cycle/scripts/test_pre_merge_resync.py
Exits 0 on success, 1 on the first failure.
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "pre_merge_resync.py"
CONTRACT = ("**Approval source:** user-invoked: fixture workflow\n"
            "**Allowed Git actions:** {actions}\n**Git limits:** none\n")
MANIFEST = '{{\n  "name": "dev",\n  "version": "{v}",\n  "description": "fixture"\n}}\n'
SKILL = "---\nname: s\nversion: {v}\n---\n# Skill\n\n{body}\n"
CHANGELOG = "# Changelog\n\n## Unreleased\n\n{entries}- [done] init (2026-01-01)\n"


def git(repo, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and proc.returncode:
        raise AssertionError(f"git {args} failed: {proc.stderr}")
    return proc.stdout.strip()


def write(repo, files):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def grant(repo, branch, actions="commit, feature-push, pr-write, base-merge"):
    slot = repo / ".git/task-cycle" / hashlib.sha256(branch.encode()).hexdigest()
    slot.mkdir(parents=True, exist_ok=True)
    (slot / "contract.md").write_text(CONTRACT.format(actions=actions), encoding="utf-8")


def release(v, body="body", entries=""):
    return {
        "dev/.claude-plugin/plugin.json": MANIFEST.format(v=v),
        "dev/.codex-plugin/plugin.json": MANIFEST.format(v=v),
        "dev/skills/s/SKILL.md": SKILL.format(v=v, body=body),
        "CHANGELOG.md": CHANGELOG.format(entries=entries),
    }


def setup(tmp):
    origin = tmp / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    repo = tmp / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"),
                       ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
        git(repo, "config", key, value)
    git(repo, "checkout", "-q", "-b", "main")
    write(repo, {**release("1.0.0"), "a.txt": "one\ntwo\nthree\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "[TEST] init")
    git(repo, "push", "-q", "-u", "origin", "main")
    git(repo, "remote", "set-head", "origin", "main")
    return repo


def branch(repo, name, files, message):
    git(repo, "checkout", "-q", "-b", name, "origin/main")
    write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    git(repo, "push", "-q", "-u", "origin", name)
    grant(repo, name)


def squash_merge(repo, name):
    git(repo, "checkout", "-q", "main")
    git(repo, "pull", "-q", "--ff-only", "origin", "main")
    git(repo, "merge", "-q", "--squash", name)
    git(repo, "commit", "-qm", f"[TEST] merge {name}")
    git(repo, "push", "-q", "origin", "main")


def resync(repo):
    proc = subprocess.run([sys.executable, str(SCRIPT), "--base", "main"], cwd=repo,
                          capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def entry(title, v):
    return f"- [done] {title} (dev v{v}) (2026-02-02)\n"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def test_classify():
    spec = importlib.util.spec_from_file_location("resync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check(module.classify("1.0.0", "1.0.1") == "patch", "patch")
    check(module.classify("1.2.3", "1.3.0") == "minor", "minor")
    check(module.classify("1.2.3", "2.0.0") == "major", "major")
    check(module.classify("1.0.0", "1.0.2") is None, "two steps are not one level")
    check(module.bump("1.0.1", "minor") == "1.1.0", "bump minor")


def test_two_branches_both_merge(tmp):
    repo = setup(tmp)
    branch(repo, "feat/a", {**release("1.0.1", entries=entry("A thing", "1.0.1")), "x.txt": "a\n"},
           "[TEST] a")
    branch(repo, "feat/b", {**release("1.0.1", body="body edited by B",
                                      entries=entry("B thing", "1.0.1")), "y.txt": "b\n"},
           "[TEST] b")
    squash_merge(repo, "feat/a")

    git(repo, "checkout", "-q", "feat/b")
    before = git(repo, "rev-parse", "origin/feat/b")
    rc, result = resync(repo)
    check(rc == 0 and result["status"] == "resynced", f"resync failed: {result}")
    for name in ("dev/.claude-plugin/plugin.json", "dev/.codex-plugin/plugin.json"):
        check('"version": "1.0.2"' in (repo / name).read_text(), f"{name} not at 1.0.2")
        check('"description": "fixture"' in (repo / name).read_text(), f"{name} lost its fields")
    skill = (repo / "dev/skills/s/SKILL.md").read_text()
    check("version: 1.0.2" in skill and "body edited by B" in skill, f"SKILL.md wrong: {skill}")
    log = (repo / "CHANGELOG.md").read_text()
    check(log.index("B thing (dev v1.0.2)") < log.index("A thing (dev v1.0.1)"),
          f"CHANGELOG order/version wrong: {log}")
    check("v1.0.1) (2026-02-02)\n- [done] init" in log and log.count("B thing") == 1,
          f"CHANGELOG duplicated or lost entries: {log}")
    check((repo / "x.txt").exists() and (repo / "y.txt").exists(), "a change was lost")
    head = git(repo, "rev-parse", "HEAD")
    check(git(repo, "rev-parse", "origin/feat/b") == head, "resync did not push")
    check(len(git(repo, "rev-list", "--parents", "-n1", "HEAD").split()) == 3, "not a merge commit")
    git(repo, "merge-base", "--is-ancestor", before, head)   # fast-forward: no force push
    check(not git(repo, "status", "--porcelain", "--untracked-files=no"), "tree left dirty")

    rc, again = resync(repo)
    check(rc == 0 and again["status"] == "up-to-date", f"second run not a no-op: {again}")

    squash_merge(repo, "feat/b")
    check('"version": "1.0.2"' in git(repo, "show", "origin/main:dev/.claude-plugin/plugin.json"),
          "second merge did not land at 1.0.2")


def test_version_line_conflict_takes_base(tmp):
    """Base moved to a different version than the branch: the version lines conflict."""
    repo = setup(tmp)
    branch(repo, "feat/m", {**release("1.1.0", entries=entry("M thing", "1.1.0")), "x.txt": "m\n"},
           "[TEST] m")
    branch(repo, "feat/n", {**release("1.0.1", body="body edited by N",
                                      entries=entry("N thing", "1.0.1")), "y.txt": "n\n"},
           "[TEST] n")
    squash_merge(repo, "feat/m")
    git(repo, "checkout", "-q", "feat/n")
    rc, result = resync(repo)
    check(rc == 0 and result["status"] == "resynced", f"version conflict not resolved: {result}")
    for name in ("dev/.claude-plugin/plugin.json", "dev/.codex-plugin/plugin.json"):
        text = (repo / name).read_text()
        check('"version": "1.1.1"' in text and "<<<<<<<" not in text, f"{name} wrong: {text}")
    skill = (repo / "dev/skills/s/SKILL.md").read_text()
    check("version: 1.1.1" in skill and "body edited by N" in skill and "<<<<<<<" not in skill,
          f"SKILL.md wrong: {skill}")
    check("N thing (dev v1.1.1)" in (repo / "CHANGELOG.md").read_text(), "entry not re-versioned")


def test_non_version_conflict_stops(tmp):
    repo = setup(tmp)
    branch(repo, "feat/c", {**release("1.0.1"), "a.txt": "one\nC\nthree\n"}, "[TEST] c")
    branch(repo, "feat/d", {**release("1.0.1"), "a.txt": "one\nD\nthree\n"}, "[TEST] d")
    squash_merge(repo, "feat/c")
    git(repo, "checkout", "-q", "feat/d")
    head = git(repo, "rev-parse", "HEAD")
    rc, result = resync(repo)
    check(rc == 1 and result["status"] == "conflict" and result["paths"] == ["a.txt"],
          f"non-version conflict not reported: {result}")
    check(git(repo, "rev-parse", "HEAD") == head, "HEAD moved on a conflict")
    check(git(repo, "rev-parse", "origin/feat/d") == head, "remote changed on a conflict")
    check(git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False) == "",
          "merge left in progress")
    check(not git(repo, "status", "--porcelain", "--untracked-files=no"), "tree left dirty")


def test_mixed_hunk_in_version_file_stops(tmp):
    """A conflict hunk holding a version line and another line is not version-only."""
    repo = setup(tmp)
    manifest = "dev/.claude-plugin/plugin.json"
    branch(repo, "feat/p", {**release("1.1.0"),
                            manifest: MANIFEST.format(v="1.1.0").replace("fixture", "P")}, "[TEST] p")
    branch(repo, "feat/q", {**release("1.0.1"),
                            manifest: MANIFEST.format(v="1.0.1").replace("fixture", "Q")}, "[TEST] q")
    squash_merge(repo, "feat/p")
    git(repo, "checkout", "-q", "feat/q")
    head = git(repo, "rev-parse", "HEAD")
    rc, result = resync(repo)
    check(rc == 1 and result["status"] == "conflict" and manifest in result.get("paths", []),
          f"mixed hunk not stopped: {result}")
    check(git(repo, "rev-parse", "HEAD") == head, "HEAD moved on a mixed hunk")
    check(not git(repo, "status", "--porcelain", "--untracked-files=no"), "tree left dirty")


def test_denied_writes_nothing(tmp):
    repo = setup(tmp)
    branch(repo, "feat/e", {**release("1.0.1"), "x.txt": "e\n"}, "[TEST] e")
    branch(repo, "feat/f", {**release("1.0.1"), "y.txt": "f\n"}, "[TEST] f")
    grant(repo, "feat/f", actions="commit, pr-write")
    squash_merge(repo, "feat/e")
    git(repo, "checkout", "-q", "feat/f")
    head = git(repo, "rev-parse", "HEAD")
    rc, result = resync(repo)
    check(rc == 1 and result["status"] == "denied", f"missing feature-push not denied: {result}")
    check(git(repo, "rev-parse", "HEAD") == head, "HEAD moved without authority")
    check(not git(repo, "status", "--porcelain", "--untracked-files=no"), "tree written without authority")


def test_multi_step_bump_stops(tmp):
    repo = setup(tmp)
    branch(repo, "feat/g", {**release("1.0.1"), "x.txt": "g\n"}, "[TEST] g")
    branch(repo, "feat/h", {**release("1.0.2"), "y.txt": "h\n"}, "[TEST] h")
    squash_merge(repo, "feat/g")
    git(repo, "checkout", "-q", "feat/h")
    head = git(repo, "rev-parse", "HEAD")
    rc, result = resync(repo)
    check(rc == 1 and "not one semver step" in result.get("message", ""), f"multi-step not stopped: {result}")
    check(git(repo, "rev-parse", "HEAD") == head, "HEAD moved on a multi-step bump")


def main():
    test_classify()
    for test in (test_two_branches_both_merge, test_version_line_conflict_takes_base,
                 test_non_version_conflict_stops, test_mixed_hunk_in_version_file_stops,
                 test_denied_writes_nothing, test_multi_step_bump_stops):
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
    print("pre_merge_resync: all tests passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
