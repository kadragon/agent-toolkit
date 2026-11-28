"""Inspect the shared kadragon marketplace before an idle Codex warm-up."""

import difflib
import hashlib
import json
import os
from pathlib import Path

from codex_app_server import request
from pinned_wave import CATALOG, MANIFEST, TIMEOUT, catalog_plugins, command

LABEL = "dispatch_shared_codex"
MARKET = "kadragon"
PENDING = {"modified", "untrusted"}


def cache_label(home):
    identity = os.path.normcase(str(home.resolve()))
    return f"{LABEL}={hashlib.sha256(identity.encode()).hexdigest()[:16]}"


def remote_versions(repo, installed):
    git = ["git", "-C", str(repo)]
    command([*git, "fetch", "origin"])
    ref = command([*git, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
    commit = command([*git, "rev-parse", "--verify", f"{ref}^{{commit}}"]).strip()
    names = catalog_plugins(json.loads(command([*git, "show", f"{commit}:{CATALOG}"])))
    selected = set(names) & installed.keys()
    if not selected:
        raise ValueError("no installed kadragon plugins; install the intended plugins before preparing the wave")
    if "dev" in selected and "guard" in names and "guard" not in installed:
        raise ValueError("install and enable guard@kadragon before preparing this wave")
    return {
        name: json.loads(command([*git, "show", f"{commit}:{name}/{MANIFEST}"]))["version"]
        for name in names if name in selected
    }


def inventory(home, cwd, versions):
    response = request("codex", home, "hooks/list", {"cwds": [str(cwd)]},
                       timeout=TIMEOUT, cwd=cwd, experimental=True)
    [group] = response["data"]
    if Path(group["cwd"]).resolve() != cwd or group["errors"] or group["warnings"]:
        raise ValueError("Codex hook inventory is incomplete for the target directory")
    hooks = []
    sources = {}
    relevant = {}
    for hook in group["hooks"]:
        name, _, market = (hook.get("pluginId") or "").partition("@")
        if market == MARKET and hook["enabled"]:
            root = (home / "plugins/cache" / MARKET / name / versions[name]).resolve()
            manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
            source = (root / manifest.get("hooks", "hooks/hooks.json")).resolve()
            if hook["source"] != "plugin" or not source.is_relative_to(root) or Path(hook["sourcePath"]).resolve() != source:
                raise ValueError(f"Codex loaded {name} hooks outside the expected plugin version")
            sources[name] = (root, source)
            relevant.setdefault(name, []).append(hook["trustStatus"])
        if hook["enabled"] and hook["trustStatus"] in PENDING:
            hooks.append({field: hook.get(field) for field in (
                "key", "pluginId", "sourcePath", "eventName", "matcher", "command", "trustStatus",
            )})
    # A plugin is a trusted baseline only when all its enabled hooks are trusted.
    snapshot = {
        name: {"version": versions[name], "trusted": all(state == "trusted" for state in relevant[name]),
               "files": hook_files(root, source)}
        for name, (root, source) in sources.items()
    }
    return hooks, snapshot


def hook_files(root, source):
    files = {source.relative_to(root).as_posix(): source.read_text(encoding="utf-8")}
    for path in sorted((root / "hooks").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            if not path.resolve().is_relative_to(root):
                raise ValueError("hook file leads outside the installed plugin")
            files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return files


def trusted_diff(pending, snapshot, baseline):
    plugins = {(hook["pluginId"] or "").split("@", 1)[0] for hook in pending
               if (hook["pluginId"] or "").endswith(f"@{MARKET}")}
    result = {}
    for name in sorted(plugins):
        if name not in baseline:
            result[name] = {"reason": "no locally recorded trusted hook contents"}
            continue
        before, after = baseline[name], snapshot[name]
        diff = []
        for path in sorted(before["files"].keys() | after["files"].keys()):
            old = before["files"].get(path, "").splitlines()
            new = after["files"].get(path, "").splitlines()
            diff.extend(difflib.unified_diff(old, new, f"{before['version']}/{path}",
                                             f"{after['version']}/{path}", lineterm=""))
        result[name] = {"trusted_version": before["version"], "current_version": after["version"],
                        "diff": "\n".join(diff)}
    return result
