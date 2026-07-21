#!/usr/bin/env python3
"""disable_plugins.py — resolve bare plugin names to plugin@market keys and write
project-scope disable entries to .claude/settings.json.

Usage:
  python3 disable_plugins.py [--project=PATH] <plugin-name> [<plugin-name> ...]
  python3 disable_plugins.py --test

  --project=PATH  write the disable into PATH/.claude/settings.json instead of the
                  current directory. Use when auditing a repo other than cwd
                  (harness-curate `all` / `--project` scope).

Resolution:
  - Reads global settings (CLAUDE_CONFIG_DIR or ~/.claude)/settings.json for
    the enabledPlugins dict.
  - For each bare plugin name, finds the key whose text before '@' matches.
  - Only keys currently set to true are disable candidates (already-false or
    absent keys are skipped with a notice — project override is only needed
    when the plugin is globally enabled).

Write target:
  <cwd>/.claude/settings.json   (project scope, never the global file)
  - Reads existing content (any keys/sections are preserved).
  - Creates enabledPlugins dict if absent.
  - Sets each resolved key to false.
  - Disable-only: writing true is refused unconditionally.
  - Atomic: temp file + os.replace so a crash leaves the file intact.

Self-check (--test):
  Exercises key resolution, already-false skip, key-preservation, create-if-absent,
  and the disable-only guard against an in-memory fixture.  Exits 0 on PASS, 1 on FAIL.
  Never touches real ~/.claude files.
"""

import json
import os
import sys
import tempfile


# ---------------------------------------------------------------------------
# Pure-function core (testable without real filesystem)
# ---------------------------------------------------------------------------

def resolve_enabled_keys(global_enabled: dict, plugin_names: list[str]) -> dict[str, str]:
    """Return {bare_name: full_key} for names that have a currently-true key.

    Keys already false (or absent) are not returned — a project-scope false on a
    globally-false key has no visible effect and indicates a logic error.
    """
    result: dict[str, str] = {}
    for name in plugin_names:
        # A bare name can match several marketplaces (e.g. foo@old, foo@current).
        # Scan ALL matches — never stop at the first — and disable only the
        # currently-true one. Stopping early could land on a stale false key and
        # silently skip the genuinely-enabled key.
        matches = [k for k in global_enabled if k.split("@")[0] == name]
        if not matches:
            print(f"  [skip] {name!r}: no matching key in global enabledPlugins")
            continue
        enabled = [k for k in matches if global_enabled[k]]
        if not enabled:
            print(f"  [skip] {name!r}: already false in global settings (no-op)")
        elif len(enabled) > 1:
            print(f"  [skip] {name!r}: ambiguous — multiple enabled keys {enabled}; disable manually")
        else:
            result[name] = enabled[0]
    return result


def write_disabled(project_settings_path: str, keys_to_disable: list[str]) -> None:
    """Atomically write false for each key into the project settings file.

    Refuses to write true under any circumstance (disable-only guard).
    Preserves all existing keys and top-level sections.
    Creates the file and/or enabledPlugins section if absent.
    """
    if not keys_to_disable:
        print("  [info] nothing to write")
        return

    # Type guard — keys must be strings, not a bare boolean. The disable-only
    # invariant itself is enforced by the hardcoded `= False` write below; this
    # only catches a caller passing malformed (non-string) key data.
    for k in keys_to_disable:
        if not isinstance(k, str):
            raise TypeError(f"BUG: key must be str, got {k!r}")

    # Read existing project settings (create from scratch if absent)
    existing: dict = {}
    if os.path.exists(project_settings_path):
        try:
            with open(project_settings_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(
                f"Cannot parse {project_settings_path}: {exc}"
            ) from exc

    # Create enabledPlugins section if absent
    if "enabledPlugins" not in existing:
        existing["enabledPlugins"] = {}

    # Apply false entries (disable-only — never write true)
    for key in keys_to_disable:
        # Belt-and-suspenders: even if caller passes wrong data
        existing["enabledPlugins"][key] = False

    # Atomic write: temp file in same dir + os.replace
    settings_dir = os.path.dirname(project_settings_path)
    os.makedirs(settings_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=settings_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_path, project_settings_path)
    except Exception:
        # clean up temp on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    print(f"  [ok] wrote {project_settings_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if "--test" in argv:
        return run_tests()

    plugin_names = [a for a in argv if not a.startswith("--")]
    if not plugin_names:
        print("Usage: disable_plugins.py [--project=PATH] <plugin-name> [...]  |  --test", file=sys.stderr)
        return 1

    # Write target defaults to cwd, but the audited repo may differ from cwd when
    # harness-curate runs with `all` / `--project` scope. Let the caller name the
    # repo explicitly so the disable lands in the project whose evidence was scored,
    # not the caller's directory.
    project_root = os.getcwd()
    for a in argv:
        if a.startswith("--project="):
            project_root = os.path.expanduser(a.split("=", 1)[1])

    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    global_settings_path = os.path.join(config_dir, "settings.json")

    # Read global enabledPlugins
    global_enabled: dict = {}
    if os.path.exists(global_settings_path):
        try:
            with open(global_settings_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [error] cannot read global settings {global_settings_path}: {exc}", file=sys.stderr)
            return 1
        global_enabled = raw.get("enabledPlugins", {})
    else:
        print(f"  [warn] global settings not found: {global_settings_path}")

    print(f"Global enabledPlugins: {list(global_enabled.keys())}")

    resolution = resolve_enabled_keys(global_enabled, plugin_names)
    if not resolution:
        print("No plugins resolved to a currently-enabled key — nothing written.")
        return 0

    print(f"Resolved to disable: {list(resolution.values())}")

    project_settings_path = os.path.join(project_root, ".claude", "settings.json")
    write_disabled(project_settings_path, list(resolution.values()))

    print(
        "\nNote: project-scope disable takes effect after /plugin reload or session restart."
        " Merge behavior with global settings may be environment-dependent."
    )
    return 0


# ---------------------------------------------------------------------------
# Self-check (--test) — never touches real ~/.claude
# ---------------------------------------------------------------------------

PASS_COUNT = 0
FAIL_COUNT = 0


def _assert(condition: bool, label: str) -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS: {label}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL: {label}")


def run_tests() -> int:
    global PASS_COUNT, FAIL_COUNT
    PASS_COUNT = 0
    FAIL_COUNT = 0

    print("=== disable_plugins.py --test ===\n")

    # ---- Fixture global enabledPlugins ----
    global_enabled = {
        "dev@kadragon": True,
        "frontend-design@claude-plugins-official": True,
        "prod@kadragon": False,   # already false — should be skipped
        "other-tool@vendor": True,
    }

    # ---- Test 1: basic resolution ----
    print("Test 1: resolve_enabled_keys — basic hit")
    result = resolve_enabled_keys(global_enabled, ["dev"])
    _assert(result == {"dev": "dev@kadragon"}, "dev resolves correctly")

    # ---- Test 2: already-false skip ----
    print("\nTest 2: resolve_enabled_keys — already-false skip")
    result = resolve_enabled_keys(global_enabled, ["prod"])
    _assert(result == {}, "already-false key skipped (no-op)")

    # ---- Test 3: missing key skip ----
    print("\nTest 3: resolve_enabled_keys — no matching key")
    result = resolve_enabled_keys(global_enabled, ["nonexistent"])
    _assert(result == {}, "nonexistent plugin skipped with notice")

    # ---- Test 4: multiple names ----
    print("\nTest 4: resolve_enabled_keys — multiple names")
    result = resolve_enabled_keys(global_enabled, ["dev", "frontend-design", "prod", "nonexistent"])
    _assert(set(result.values()) == {"dev@kadragon", "frontend-design@claude-plugins-official"},
            "only truly-enabled keys returned for multiple names")

    # ---- Test 4b: multi-marketplace — stale false key must not mask enabled key ----
    print("\nTest 4b: resolve_enabled_keys — multi-marketplace collision")
    multi = {"foo@old": False, "foo@current": True}
    result = resolve_enabled_keys(multi, ["foo"])
    _assert(result == {"foo": "foo@current"},
            "enabled key found despite an earlier stale false key for same bare name")
    multi_both = {"foo@a": True, "foo@b": True}
    result = resolve_enabled_keys(multi_both, ["foo"])
    _assert(result == {}, "two enabled keys for one bare name → ambiguous, skipped (not mis-disabled)")

    # ---- Test 5: write_disabled creates file + section from scratch ----
    print("\nTest 5: write_disabled — create-if-absent")
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_settings = os.path.join(tmpdir, ".claude", "settings.json")
        write_disabled(proj_settings, ["dev@kadragon"])
        with open(proj_settings) as fh:
            data = json.load(fh)
        _assert(data.get("enabledPlugins", {}).get("dev@kadragon") is False,
                "key written as false in new file")
        _assert("enabledPlugins" in data, "enabledPlugins section created")

    # ---- Test 6: write_disabled preserves existing keys ----
    print("\nTest 6: write_disabled — key preservation")
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_settings = os.path.join(tmpdir, ".claude", "settings.json")
        os.makedirs(os.path.dirname(proj_settings))
        existing = {
            "permissions": {"allow": ["Bash(*)"]},
            "enabledPlugins": {"other-tool@vendor": True},
        }
        with open(proj_settings, "w") as fh:
            json.dump(existing, fh)
        write_disabled(proj_settings, ["dev@kadragon"])
        with open(proj_settings) as fh:
            data = json.load(fh)
        _assert(data.get("permissions") == {"allow": ["Bash(*)"]},
                "permissions section preserved")
        _assert(data["enabledPlugins"].get("other-tool@vendor") is True,
                "existing other-tool@vendor key preserved as-is")
        _assert(data["enabledPlugins"].get("dev@kadragon") is False,
                "new disable entry written")

    # ---- Test 7: write_disabled — disable-only guard (cannot write True) ----
    print("\nTest 7: write_disabled — disable-only guard")
    # Simulate a caller passing a boolean True as a key name — the guard catches it
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_settings = os.path.join(tmpdir, ".claude", "settings.json")
        raised = False
        try:
            write_disabled(proj_settings, [True])  # type: ignore[list-item]
        except (ValueError, TypeError):
            raised = True
        _assert(raised, "write True as key name raises an error (disable-only)")

    # ---- Test 8: atomic write leaves correct content on success ----
    print("\nTest 8: write_disabled — atomic write integrity")
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_settings = os.path.join(tmpdir, ".claude", "settings.json")
        write_disabled(proj_settings, ["x@y", "a@b"])
        with open(proj_settings) as fh:
            data = json.load(fh)
        _assert(data["enabledPlugins"].get("x@y") is False, "x@y written false")
        _assert(data["enabledPlugins"].get("a@b") is False, "a@b written false")
        all_vals = list(data["enabledPlugins"].values())
        _assert(all(v is False for v in all_vals), "all written values are False (disable-only)")

    print(f"\n=== Results: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL ===")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
