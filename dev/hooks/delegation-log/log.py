#!/usr/bin/env python3
"""delegation-log — PostToolUse(Task) recorder.

Appends one JSONL line per Task tool call to the *per-repo* log
`<git-root>/.claude/logs/delegations.jsonl`. Records subagent type and a
privacy-preserving description hash so the harness-curate skill can later
detect delegation patterns (repeated similar tasks → skill candidate).

Record schema: {ts, subagent_type, description_hash, cwd, session}
  ts               — epoch milliseconds
  subagent_type    — tool_input.subagent_type (empty string if absent)
  description_hash — sha256(normalize(description))[:16]
                     normalize = lowercase + collapse whitespace
  cwd              — working directory from the hook payload
  session          — session_id from the hook payload

Design contract: never-raise, always exit 0. A logging failure must never
disrupt the session.
"""

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time

_IS_WIN = sys.platform == "win32"
# O_NOFOLLOW: raises ELOOP on Unix if path is a symlink; undefined on Windows (use 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
# whole-file lock region for msvcrt.locking
_LOCK_BYTES = 0x7FFFFFFF

try:
    import fcntl as _fcntl
    _LOCK_EX = _fcntl.LOCK_EX  # eager: AttributeError here → next branch below
    _LOCK_UN = _fcntl.LOCK_UN

    def _lock(f):
        _fcntl.flock(f.fileno(), _LOCK_EX)  # type: ignore[attr-defined]

    def _unlock(f):
        _fcntl.flock(f.fileno(), _LOCK_UN)  # type: ignore[attr-defined]

except (ImportError, AttributeError):
    try:
        import msvcrt as _msvcrt

        # Windows mandatory byte-range lock guarding append_capped's read-modify-write.
        # LK_NBLCK (non-blocking): if a concurrent PostToolUse hook holds the region,
        # raise immediately so the outer except drops this entry rather than stalling.
        def _lock(f):  # type: ignore[misc]
            os.lseek(f.fileno(), 0, os.SEEK_SET)
            _msvcrt.locking(f.fileno(), _msvcrt.LK_NBLCK, _LOCK_BYTES)  # type: ignore[attr-defined]

        def _unlock(f):  # type: ignore[misc]
            os.lseek(f.fileno(), 0, os.SEEK_SET)
            _msvcrt.locking(f.fileno(), _msvcrt.LK_UNLK, _LOCK_BYTES)  # type: ignore[attr-defined]

    except (ImportError, AttributeError):
        # neither fcntl nor msvcrt: locking skipped (safe for serial use)
        def _lock(_f):  # type: ignore[misc]
            pass

        def _unlock(_f):  # type: ignore[misc]
            pass


LOG_REL = os.path.join(".claude", "logs", "delegations.jsonl")
MAX_LINES = 1000          # bound the per-repo log; keep the newest N


def git_root(cwd):
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            root = out.stdout.strip()
            if root:
                return root
    except Exception:
        pass
    return None


def log_path(cwd):
    """Per-repo log path; fall back to CLAUDE_PROJECT_DIR; else None (skip)."""
    root = git_root(cwd) or os.environ.get("CLAUDE_PROJECT_DIR")
    if not root or not os.path.isdir(root):
        return None
    return os.path.join(root, LOG_REL)


def normalize(text):
    """Lowercase and collapse whitespace: 'Foo  Bar' → 'foo bar'."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def description_hash(text):
    """SHA-256 of normalized text, first 16 hex chars (64-bit fingerprint)."""
    return hashlib.sha256(normalize(text).encode()).hexdigest()[:16]


def build_record(data, now_ms):
    ti = data.get("tool_input", {}) or {}
    return {
        "ts": now_ms,
        "subagent_type": ti.get("subagent_type") or "",
        "description_hash": description_hash(ti.get("description") or ""),
        "cwd": data.get("cwd", ""),
        "session": data.get("session_id", ""),
    }


def append_capped(path, line):
    """Append one line, trimming to MAX_LINES, under an exclusive lock (Unix).

    On Unix: flock guards read-modify-write; O_NOFOLLOW rejects pre-planted symlinks
    (raises ELOOP → OSError, caught silently). On Windows: O_NOFOLLOW is unavailable,
    so both the log and .gitignore opens are guarded by an os.path.islink() pre-check
    (TOCTOU best-effort), and msvcrt.locking provides a non-blocking mandatory
    byte-range lock (locking is skipped only when neither fcntl nor msvcrt is
    importable). Self-contained: swallows OSError/UnicodeDecodeError so a logging
    failure never disrupts the session."""
    d = os.path.dirname(path)
    try:
        os.makedirs(d, exist_ok=True)
        gi = os.path.join(d, ".gitignore")
        try:
            if _O_NOFOLLOW == 0 and os.path.islink(gi):
                raise OSError("symlink at gitignore path")
            gi_fd = os.open(gi, os.O_CREAT | os.O_RDWR | _O_NOFOLLOW, 0o644)
            try:
                gf = os.fdopen(gi_fd, "r+", encoding="utf-8")
            except OSError:
                os.close(gi_fd)
                raise
            with gf:
                content = gf.read()
                # Suppress appending if any existing pattern already matches
                # 'delegations.jsonl' (e.g. *.jsonl, *, delegations.*).
                # Use the canonical log filename, not basename(path), so that
                # test paths (test.jsonl) don't affect the coverage check.
                _log_fname = os.path.basename(LOG_REL)
                if not any(fnmatch.fnmatch(_log_fname, ln.strip())
                           for ln in content.splitlines()
                           if ln.strip()):
                    gf.seek(0, 2)
                    prefix = "\n" if content and not content.endswith("\n") else ""
                    gf.write(prefix + "*\n")
        except (OSError, UnicodeDecodeError):
            # gitignore update failed (symlink, perms, or non-UTF-8 content); caught HERE
            # — not at the outer except — so the log write below is still attempted.
            # .gitignore maintenance is best-effort; logging is the primary behavior.
            pass
        if _O_NOFOLLOW == 0 and os.path.islink(path):
            raise OSError("symlink at log path")
        log_fd = os.open(path, os.O_RDWR | os.O_CREAT | _O_NOFOLLOW, 0o600)
        try:
            f = os.fdopen(log_fd, "r+", encoding="utf-8")
        except OSError:
            os.close(log_fd)
            raise
        with f:
            _lock(f)
            try:
                f.seek(0)
                lines = f.readlines()
                lines.append(line + "\n")
                if len(lines) > MAX_LINES:
                    lines = lines[-MAX_LINES:]
                f.seek(0)
                f.truncate()
                f.writelines(lines)
                f.flush()  # push buffered writes to the OS before releasing the lock,
                           # so a parallel reader cannot grab the lock and see stale data
            finally:
                _unlock(f)
    except (OSError, UnicodeDecodeError):
        # OSError: any FS failure (symlink/ELOOP, perms, msvcrt lock contention).
        # UnicodeDecodeError: a non-UTF-8 *log* file read (ValueError subclass, not an
        # OSError); the .gitignore decode case is handled at the inner except so it does
        # not abort the log write. Swallow both so a logging failure never disrupts the
        # session.
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Task":
        return
    path = log_path(data.get("cwd", os.getcwd()))
    if not path:
        return
    rec = build_record(data, int(time.time() * 1000))
    append_capped(path, json.dumps(rec, ensure_ascii=False))


def _test():
    """Embedded test suite. Run: python3 log.py --test"""
    import tempfile
    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL") + f" — {name}")
        if not cond:
            fails.append(name)

    # normalize + hash deterministic
    check("normalize collapses whitespace", normalize("Foo  Bar") == "foo bar")
    check("normalize lowercases", normalize("ABC") == "abc")
    check("normalize strips", normalize("  x  ") == "x")
    h1 = description_hash("Foo  Bar")
    h2 = description_hash("foo bar")
    check("hash deterministic: 'Foo  Bar' == 'foo bar'", h1 == h2)
    check("hash length 16", len(h1) == 16)

    # build_record
    rec = build_record({
        "tool_input": {"subagent_type": "agent", "description": "Run tests"},
        "cwd": "/repo", "session_id": "s1",
    }, 9999)
    check("record ts", rec["ts"] == 9999)
    check("record subagent_type", rec["subagent_type"] == "agent")
    check("record description_hash length", len(rec["description_hash"]) == 16)
    check("record cwd", rec["cwd"] == "/repo")
    check("record session", rec["session"] == "s1")

    # symlink planted at log path → append_capped must skip silently
    if _IS_WIN:
        print("SKIP — symlink protection test (O_NOFOLLOW unavailable on Windows)")
    else:
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "target.txt")
            with open(target, "w") as fh:
                fh.write("original\n")
            link = os.path.join(td, "link.jsonl")
            os.symlink(target, link)
            append_capped(link, '{"test":1}')
            with open(target) as fh:
                content = fh.read()
            check("symlink write skipped — target unmodified", content == "original\n")
            check("symlink still a symlink", os.path.islink(link))

    # .gitignore without trailing newline → write must start a new line
    with tempfile.TemporaryDirectory() as td:
        lp = os.path.join(td, "test.jsonl")
        gi_path = os.path.join(td, ".gitignore")
        with open(gi_path, "w", encoding="utf-8") as gh:
            gh.write("keep")  # no trailing newline
        append_capped(lp, '{"test":1}')
        with open(gi_path, encoding="utf-8") as gh:
            gi_content = gh.read()
        check(".gitignore line boundary preserved", gi_content == "keep\n*\n")

    # invalid-UTF-8 .gitignore → append must not raise AND must still record the log
    with tempfile.TemporaryDirectory() as td:
        lp = os.path.join(td, "test.jsonl")
        gi_path = os.path.join(td, ".gitignore")
        with open(gi_path, "wb") as gh:
            gh.write(b"\xff\xfe not valid utf-8\n")
        raised = False
        try:
            append_capped(lp, '{"test":1}')
        except UnicodeDecodeError:
            raised = True
        check("invalid-utf8 .gitignore does not raise", not raised)
        wrote = os.path.exists(lp) and \
            '{"test":1}' in open(lp, encoding="utf-8").read()
        check("log entry written despite undecodable .gitignore", wrote)

    print()
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        try:
            main()
        except BaseException:
            pass
        sys.exit(0)
