#!/usr/bin/env python3
"""Bring a PR branch that fell behind base up to date before merge — no rebase, no force push.

Usage: pre_merge_resync.py --base <base_branch> [--remote origin]

Run from the feature branch's checkout (a `.worktrees/` worktree included) with a clean
tracked tree. Steps:

1. `commit` and `feature-push` authority are checked first (cycle_state.py authorize); denied →
   nothing written. `commit` is checked again before the merge commit, `feature-push` before push.
2. Fetch `<remote>/<base>` and the PR branch; pin base to one SHA. Base already in HEAD → done:
   `up-to-date` when the PR branch is HEAD, else the unpushed earlier merge is pushed.
3. Read what the branch bumped, from its merge-base to HEAD: every `plugin.json` under a
   `.claude-plugin/` or `.codex-plugin/` directory and every `SKILL.md` whose version changed,
   each by exactly one semver step — that step is the level re-applied. A multi-step change
   stops the run. The branch's `CHANGELOG.md` must only add entry lines; they are re-inserted.
4. `git merge --no-ff --no-commit <remote>/<base>`. A single one-line conflict hunk on the file's
   own version field takes base's side; any other conflict, or any failure before the merge
   commit, aborts the merge and stops.
5. Each bumped file's version is set to base's version plus the original level; CHANGELOG.md is
   base's file with the branch's entries re-inserted under `## Unreleased`, their
   `(<plugin> v<old>)` rewritten to the new version. The merge commit is made, `feature-push`
   is checked again, and the branch is pushed fast-forward — never forced.

Output: one JSON object on stdout (`status`: up-to-date | resynced | conflict | denied | error).
Exit 0 for up-to-date/resynced, 1 otherwise. A squash hub merge drops the merge commit.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE.parent.parent / "task-next" / "scripts" / "cycle_state.py"
NODES = HERE.parent.parent / "task-next" / "scripts" / "task_nodes.py"
CHANGELOG = "CHANGELOG.md"
MANIFEST = re.compile(r"(?:^|/)\.(?:claude|codex)-plugin/plugin\.json$")
JSON_VERSION = re.compile(r'^(\s*"version"\s*:\s*")([^"]+)(".*)$')
SKILL_VERSION = re.compile(r"^(version:[ \t]*)(\S+)(.*)$")
# An entry's version suffix, the group right before its date: `(dev v1.2.3, mods v0.1.0) (2026-01-01)`.
SUFFIX = re.compile(r"\(([^()]*)\)(?= \(\d{4}-\d{2}-\d{2}\))")
SUFFIX_TERM = re.compile(r"(^|, )([\w.-]+) v(\d+\.\d+\.\d+)(?=,|$)")
ENV = {**os.environ, "GIT_EDITOR": "true", "GIT_MERGE_AUTOEDIT": "no"}


class Stop(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


def git(*args, check=True):
    proc = subprocess.run(["git", *args], capture_output=True, text=True, env=ENV)
    if check and proc.returncode:
        raise Stop("error", f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def out(*args):
    return git(*args).stdout.rstrip("\n")


def read(path):
    """File text with its line endings intact; read_text folds CRLF to LF."""
    return Path(path).read_bytes().decode("utf-8")


def write(path, text):
    Path(path).write_bytes(text.encode("utf-8"))


def show_checkout(rev, path):
    """A blob as checkout would write it (core.autocrlf, .gitattributes eol), byte for byte."""
    proc = subprocess.run(["git", "cat-file", "--filters", f"{rev}:{path}"], capture_output=True, env=ENV)
    if proc.returncode:
        raise Stop("error", f"git cat-file --filters {rev}:{path} failed: "
                            f"{proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout.decode("utf-8")


def is_version_file(path):
    return bool(MANIFEST.search(path)) or Path(path).name == "SKILL.md"


def version_pattern(path):
    return SKILL_VERSION if Path(path).name == "SKILL.md" else JSON_VERSION


def version_line_index(path, lines):
    """Index of the line holding the version: JSON's first `"version"`, SKILL.md's frontmatter."""
    pattern = version_pattern(path)
    if pattern is SKILL_VERSION:
        if not lines or lines[0].strip() != "---":
            return None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return None
            if pattern.match(lines[i]):
                return i
        return None
    return next((i for i, line in enumerate(lines) if pattern.match(line)), None)


def version_at(rev, path):
    proc = git("show", f"{rev}:{path}", check=False)
    if proc.returncode:
        return None
    lines = proc.stdout.splitlines()
    i = version_line_index(path, lines)
    return version_pattern(path).match(lines[i]).group(2) if i is not None else None


def parse(version):
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def classify(old, new):
    """The single semver step from old to new, or None."""
    o, n = parse(old), parse(new)
    if not o or not n:
        return None
    steps = {"major": (o[0] + 1, 0, 0), "minor": (o[0], o[1] + 1, 0), "patch": (o[0], o[1], o[2] + 1)}
    return next((level for level, target in steps.items() if target == n), None)


def bump(version, level):
    v = parse(version)
    if not v:
        raise Stop("error", f"cannot bump non-semver version '{version}'")
    return {"major": f"{v[0] + 1}.0.0", "minor": f"{v[0]}.{v[1] + 1}.0",
            "patch": f"{v[0]}.{v[1]}.{v[2] + 1}"}[level]


def branch_bumps(merge_base, names):
    bumps = {}
    for path in names:
        if not is_version_file(path):
            continue
        old, new = version_at(merge_base, path), version_at("HEAD", path)
        if old is None or new is None or old == new:
            continue
        level = classify(old, new)
        if level is None:
            raise Stop("error", f"{path}: {old} → {new} is not one semver step; resync by hand")
        bumps[path] = {"from": old, "branch": new, "level": level}
    return bumps


def branch_entries(merge_base):
    diff = out("diff", "-U0", merge_base, "HEAD", "--", CHANGELOG)
    entries = []
    for line in diff.splitlines():
        if line.startswith(("+++", "---", "@@", "diff ", "index ", "new file", "deleted file")):
            continue
        body = line[1:]
        if line.startswith("-") and body.strip():
            raise Stop("error", f"branch edits an existing {CHANGELOG} line ('{body}'); resync by hand")
        if line.startswith("+") and body.strip():
            if not body.startswith("- "):
                raise Stop("error", f"branch adds a non-entry {CHANGELOG} line ('{body}'); resync by hand")
            entries.append(body)
    return entries


def resolve_version_hunks(path):
    """Take base's side of every conflict hunk in path; False when a hunk is not version-only."""
    lines = read(path).splitlines(keepends=True)
    pattern = version_pattern(path)
    result, i, at = [], 0, []
    while i < len(lines):
        if not lines[i].startswith("<<<<<<< "):
            result.append(lines[i])
            i += 1
            continue
        ours, theirs, section = [], [], "ours"
        i += 1
        while i < len(lines) and not lines[i].startswith(">>>>>>> "):
            line = lines[i]
            if line.startswith("||||||| "):
                section = "ancestor"
            elif line.rstrip("\r\n") == "=======":
                section = "theirs"
            elif section == "ours":
                ours.append(line)
            elif section == "theirs":
                theirs.append(line)
            i += 1
        if i == len(lines):
            return False
        i += 1
        if len(ours) != 1 or len(theirs) != 1 or not all(
                pattern.match(x.rstrip("\r\n")) for x in ours + theirs):
            return False
        at.append(len(result))
        result.extend(theirs)   # merging base into the branch: "theirs" is base
    if len(at) != 1:
        return False            # marker-less (modify/delete) or several hunks: not ours to settle
    # Only the file's own version field — not a `version:` in a SKILL.md body or a nested key.
    if version_line_index(path, [x.rstrip("\r\n") for x in result]) != at[0]:
        return False
    write(path, "".join(result))
    return True


def set_version(path, version):
    lines = read(path).splitlines(keepends=True)
    i = version_line_index(path, [x.rstrip("\r\n") for x in lines])
    if i is None:
        raise Stop("error", f"{path}: version line not found after merge")
    eol = lines[i][len(lines[i].rstrip("\r\n")):]
    match = version_pattern(path).match(lines[i].rstrip("\r\n"))
    lines[i] = f"{match.group(1)}{version}{match.group(3)}{eol}"
    write(path, "".join(lines))


def plugin_names(path, rev):
    """Names a CHANGELOG entry may use for this manifest's plugin: its top directory and its name."""
    names = set()
    parts = Path(path).parts
    if len(parts) > 2:
        names.add(parts[-3])
    proc = git("show", f"{rev}:{path}", check=False)
    if not proc.returncode:
        try:
            name = json.loads(proc.stdout).get("name")
        except (ValueError, AttributeError):
            name = None
        if name:
            names.add(name)
    return names


def authorize(branch, *actions):
    for action in actions:
        proc = subprocess.run([sys.executable, str(STATE), "authorize", "--branch", branch,
                               "--action", action], capture_output=True, text=True)
        if proc.returncode:
            raise Stop("denied", proc.stderr.strip() or f"{action} not established")


def push(branch, remote, base, **result):
    authorize(branch, "feature-push")
    pushed = git("push", "--quiet", remote, f"HEAD:refs/heads/{branch}", check=False)
    result = {"branch": branch, "base": f"{remote}/{base}", "head": out("rev-parse", "HEAD"), **result}
    if pushed.returncode:
        raise Stop("error", f"merge committed locally, push failed: {pushed.stderr.strip()}", **result)
    return {"status": "resynced", "pushed": True, **result}


def rewrite_suffix(entry, rewrites):
    """Re-version every `<plugin> v<old>` term of the version suffix; the title is left alone."""
    def swap(match):
        new = rewrites.get((match.group(2), match.group(3)))
        return f"{match.group(1)}{match.group(2)} v{new}" if new else match.group(0)
    return SUFFIX.sub(lambda group: f"({SUFFIX_TERM.sub(swap, group.group(1))})", entry, count=1)


def load_insert():
    spec = importlib.util.spec_from_file_location("_task_nodes", NODES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.insert_changelog_entry


def resync(base, remote):
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
    if not branch or branch == base:
        raise Stop("error", f"run from the feature branch, not '{branch or 'detached HEAD'}'")
    authorize(branch, "commit", "feature-push")
    os.chdir(out("rev-parse", "--show-toplevel"))   # git prints every path below repo-relative
    if out("status", "--porcelain", "--untracked-files=no"):
        raise Stop("error", "tracked changes present; commit or stash before resync")
    git("fetch", "--quiet", remote, f"+refs/heads/{base}:refs/remotes/{remote}/{base}",
        f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}")
    # Pinned once: other worktrees share the remote-tracking ref and may move it mid-run.
    target = out("rev-parse", f"refs/remotes/{remote}/{base}^{{commit}}")
    pr_head = out("rev-parse", f"refs/remotes/{remote}/{branch}^{{commit}}")
    if git("merge-base", "--is-ancestor", pr_head, "HEAD", check=False).returncode:
        raise Stop("error", f"{remote}/{branch} has commits this checkout lacks; pull them first")
    if not git("merge-base", "--is-ancestor", target, "HEAD", check=False).returncode:
        if pr_head == out("rev-parse", "HEAD"):
            return {"status": "up-to-date", "branch": branch, "base": f"{remote}/{base}"}
        return push(branch, remote, base, note="pushed a resync left unpushed by an earlier run")

    merge_base = out("merge-base", "HEAD", target)
    names = out("diff", "--name-only", merge_base, "HEAD").splitlines()
    bumps = branch_bumps(merge_base, names)
    entries = branch_entries(merge_base) if CHANGELOG in names else []
    if entries and git("cat-file", "-e", f"{target}:{CHANGELOG}", check=False).returncode:
        raise Stop("error", f"base no longer has {CHANGELOG}; resync by hand")
    insert = load_insert() if entries else None

    merged = git("merge", "--no-ff", "--no-commit", target, check=False)
    try:
        if merged.returncode:
            unmerged = out("diff", "--name-only", "--diff-filter=U").splitlines()
            if not unmerged:
                raise Stop("error", f"merge failed: {merged.stderr.strip() or merged.stdout.strip()}")
            stuck = [p for p in unmerged
                     if not ((p == CHANGELOG and entries) or (p in bumps and resolve_version_hunks(p)))]
            if stuck:
                raise Stop("conflict", "non-version conflict; merge aborted, nothing pushed", paths=stuck)

        versions = []
        rewrites = {}   # (plugin name, branch version) -> resynced version, for CHANGELOG entries
        for path, info in bumps.items():
            base_version = version_at(target, path)
            new = bump(base_version, info["level"]) if base_version else info["branch"]
            set_version(path, new)
            git("add", "--", path)
            versions.append({"file": path, "level": info["level"], "base": base_version, "to": new})
            if MANIFEST.search(path):
                rewrites.update({(name, info["branch"]): new for name in plugin_names(path, "HEAD")})

        if entries:
            text = show_checkout(target, CHANGELOG)
            updated = [rewrite_suffix(entry, rewrites) for entry in entries]
            for entry in reversed(updated):
                text, _ = insert(text, entry)
            write(CHANGELOG, text)
            git("add", "--", CHANGELOG)
            entries = updated

        if out("diff", "--name-only", "--diff-filter=U"):
            raise Stop("conflict", "unresolved paths remain; merge aborted, nothing pushed")
        authorize(branch, "commit")
        git("commit", "--quiet", "--no-edit")
    except (Stop, OSError) as failure:
        # Anything between the merge and its commit leaves MERGE_HEAD and a half-written index.
        git("merge", "--abort", check=False)
        if isinstance(failure, Stop):
            raise
        raise Stop("error", f"{failure}; merge aborted, nothing pushed") from failure
    return push(branch, remote, base, versions=versions, changelog_entries=entries)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True)
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args(argv)
    try:
        result = resync(args.base, args.remote)
    except Stop as stop:
        result = {"status": stop.status, "message": str(stop), **stop.extra}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in ("up-to-date", "resynced") else 1


if __name__ == "__main__":
    sys.exit(main())
