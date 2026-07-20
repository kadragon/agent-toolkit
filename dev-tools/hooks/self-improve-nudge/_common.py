"""Shared helpers for self-improve-nudge's Stop writer (nudge.py) and
SessionStart reader (surface.py).

The two hooks fire in different sessions but must agree on ONE per-project
location for the pending-nudge handoff file. Both derive it from the working
directory via encode_project(), so a Stop in project X and the next
SessionStart in project X resolve to the identical path regardless of which
session_id is active — that symmetric key derivation is the whole contract.
"""

import os
import re


def encode_project(path):
    """Project cwd -> stable dir-name key. Mirrors task-audit-nudge.encode_project
    so both hooks (and the sibling curator state) key projects identically."""
    path = os.path.normcase(os.path.abspath(path))
    return re.sub(r"[/.:\\]", "-", path)


def config_dir():
    """Root config dir for the active platform (~/.claude or ~/.codex).
    Both platforms store per-project state under <dir>/projects/<encoded>.

    Codex sets CLAUDE_PLUGIN_ROOT as a compat alias (docs/platform-specs.md), so
    its presence does NOT mean Claude — detect Codex via CODEX_HOME / script path
    BEFORE the Claude default. Keying off CLAUDE_PLUGIN_ROOT here would send a
    Codex session's pending file to ~/.claude, where a Claude session on the same
    project would consume it (cross-platform leakage)."""
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        return os.environ["CLAUDE_CONFIG_DIR"]
    if os.environ.get("CODEX_HOME"):
        return os.environ["CODEX_HOME"]
    if "/.codex/" in os.path.realpath(__file__):
        return os.path.expanduser("~/.codex")
    return os.path.expanduser("~/.claude")


def pending_path(cwd, cdir=None):
    """Per-project pending-nudge file. Writer and reader both call this with the
    same cwd -> same path across sessions."""
    cdir = cdir or config_dir()
    return os.path.join(
        cdir, "projects", encode_project(cwd), ".self-improve-pending.json"
    )
