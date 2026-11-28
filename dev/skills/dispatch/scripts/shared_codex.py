import difflib
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path

from codex_app_server import request
from pinned_wave import CATALOG, MANIFEST, TIMEOUT, catalog_plugins, command

LABEL = "dispatch_shared_codex"
MARKET = "kadragon"
PENDING = {"modified", "untrusted"}


def cache_label(home):
    identity = os.path.normcase(str(home.resolve()))
    return f"{LABEL}={hashlib.sha256(identity.encode()).hexdigest()[:16]}"


def is_commit(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is not None


def remote_head(repo):
    git = ["git", "-C", str(repo)]
    command([*git, "fetch", "origin"])
    head = command([*git, "ls-remote", "--exit-code", "origin", "HEAD"]).strip()
    match = re.fullmatch(r"([0-9a-f]{40}|[0-9a-f]{64})	HEAD", head)
    if match is None:
        raise ValueError("cannot resolve the marketplace default branch commit")
    return match[1]


def marketplace_pin(home):
    """Return the commit the home's configured marketplace is pinned to, or None when it floats."""
    try:
        config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    ref = (config.get("marketplaces") or {}).get(MARKET, {}).get("ref")
    return ref if is_commit(ref) else None


def pin_marketplace(home, commit):
    """Set `ref` of the configured marketplace to a full commit, keeping the rest of the file."""
    path = home / "config.toml"
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        lines = []
    header = f"[marketplaces.{MARKET}]"
    start = next((index for index, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        raise ValueError(f"{path} has no {header} section; add the marketplace to this Codex home first")
    end = next((index for index in range(start + 1, len(lines)) if lines[index].lstrip().startswith("[")), len(lines))
    pin = f'ref = "{commit}"\n'
    for index in range(start + 1, end):
        if re.match(r"\s*ref\s*=", lines[index]):
            lines[index] = pin
            break
    else:
        if not lines[start].endswith("\n"):
            lines[start] += "\n"
        lines.insert(start + 1, pin)
    text = "".join(lines)
    if tomllib.loads(text)["marketplaces"][MARKET].get("ref") != commit:
        raise ValueError(f"cannot pin {path}: the {header} section did not take the ref")
    temporary = path.with_name(path.name + ".dispatch-tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def remote_versions(repo, installed, commit=None):
    git = ["git", "-C", str(repo)]
    if commit is None:
        commit = remote_head(repo)
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


def inventory(binary, home, cwd, versions, *, require_guard=False):
    response = request(binary, home, "hooks/list", {"cwds": [str(cwd)]},
                       timeout=TIMEOUT, cwd=cwd, experimental=True)
    [group] = response["data"]
    if Path(group["cwd"]).resolve() != cwd or group["errors"] or group["warnings"]:
        raise ValueError("Codex hook inventory is incomplete for the target directory")
    hooks = []
    sources = {}
    relevant = {}
    for hook in group["hooks"]:
        name, _, market = (hook.get("pluginId") or "").partition("@")
        if require_guard and market == MARKET and name == "guard" and not hook["enabled"]:
            raise ValueError("a guard@kadragon hook is disabled in the target directory")
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
    if require_guard and "guard" not in sources:
        raise ValueError("no active guard@kadragon hooks in the target directory")
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
