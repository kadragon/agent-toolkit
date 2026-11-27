"""Locate Claude Code and Codex transcript and state files for a project."""

import glob
import json
import os
import re


def encode_project(path):
    """Map a project path to its transcript dir name: '/', '.', '\\', ':' -> '-'.

    Normalizes to an absolute, case-folded path first so Windows drive-letter
    case differences (`C:` vs `c:`) don't fragment state across sessions.

    INVARIANT — do not "fix" the collision. This must REPRODUCE Claude Code's own project-dir
    naming in order to FIND dirs Claude already created, so its lossiness is inherited, not ours:
    `/tmp/foo.bar` and `/tmp/foo-bar` both encode to `-tmp-foo-bar` because Claude collapses them
    too. De-colliding (e.g. appending a path hash) would make every lookup miss its real
    directory — trading a rare theoretical clash for guaranteed total failure.
    """
    path = os.path.normcase(os.path.abspath(path))
    return re.sub(r"[/.:\\]", "-", path)


def _loose_key(name):
    """Case/underscore/hyphen-insensitive key for fuzzy-matching an encoded dir name.

    Claude Code's own project-dir naming has drifted across versions (e.g. some
    transcripts landed under 'C--Dev-work-space-my-app', others under
    'c--dev-work_space-my-app' for the SAME repo) — different case and different
    treatment of '_' vs '-'. encode_project() only produces one exact candidate, so
    an exact-match lookup silently misses real data sitting under a sibling encoding.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _jsonl_count(d):
    try:
        return len(glob.glob(os.path.join(d, "*.jsonl")))
    except OSError:
        return 0


def codex_home():
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def codex_state_dir(codex_root, real_path):
    """Codex has no project-keyed directory to hold this skill's own bookkeeping (session
    files are date-partitioned, not project-partitioned — see module docstring), so mint one
    under the SAME encode_project() scheme Claude's side already uses, purely for
    .harness-curator-state.json. This does not hold real Codex session data."""
    return os.path.join(codex_root, "projects", encode_project(real_path))


def _codex_session_meta_cwd(fp):
    """Read just the leading records of a Codex rollout file to find session_meta.payload.cwd.
    session_meta is normally the first line, but a few extra lines are tolerated in case a
    future format prepends something. None if not found/unreadable — never raises."""
    try:
        with open(fp, encoding="utf-8") as fh:
            for _, line in zip(range(5), fh):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("type") == "session_meta":
                    payload = r.get("payload")
                    return payload.get("cwd") if isinstance(payload, dict) else None
    except OSError:
        pass
    return None


def find_codex_session_files(codex_root, real_path, since_ms=None):
    """*.jsonl under <codex_root>/sessions (archived_sessions excluded — see module
    docstring) whose session_meta.cwd matches real_path. Cheap because only the leading
    lines of each file are read (benchmarked at ~0.1s for 1400+ files), not the whole file.
    since_ms drops files not modified after it before their head is read."""
    root = os.path.join(codex_root, "sessions")
    if not os.path.isdir(root):
        return []
    target = os.path.normcase(os.path.abspath(real_path))
    matches = []
    for fp in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        if since_ms is not None:
            try:
                if os.path.getmtime(fp) * 1000 <= since_ms:
                    continue
            except OSError:
                continue
        cwd = _codex_session_meta_cwd(fp)
        if cwd and os.path.normcase(os.path.abspath(cwd)) == target:
            matches.append(fp)
    return matches


def resolve_project_dir(path, proj_root):
    """Find the transcript dir for `path`, tolerating the case/separator drift above.

    Prefers an exact encode_project() match, but only when it actually holds
    transcripts — a directory can exist with zero *.jsonl files (e.g. created solely
    by this skill's own Step 6 state-file write, which uses a raw, non-normcased
    substitution that can diverge from encode_project() and spuriously "claim" the
    exact-match slot). When the exact dir has no jsonl data, scan proj_root for
    directories whose loose key matches and pick whichever (exact or fuzzy sibling)
    has the most *.jsonl files. Falls back to the exact (possibly nonexistent) path
    so downstream 'no data' reporting is unchanged when truly nothing matches.
    """
    exact = os.path.join(proj_root, encode_project(path))
    exact_count = _jsonl_count(exact) if os.path.isdir(exact) else -1
    if exact_count > 0:
        return exact
    if not os.path.isdir(proj_root):
        return exact
    target_key = _loose_key(encode_project(path))
    best, best_count = None, exact_count
    for n in os.listdir(proj_root):
        d = os.path.join(proj_root, n)
        if not os.path.isdir(d) or _loose_key(n) != target_key:
            continue
        count = _jsonl_count(d)
        if count > best_count:
            best, best_count = d, count
    return best if best is not None else exact
