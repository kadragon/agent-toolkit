"""Isolate and verify the Codex marketplace used by one Herdr wave."""

import hashlib
import io
import json
import os
import queue
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import tomllib
from pathlib import Path, PurePosixPath

CATALOG = ".agents/plugins/marketplace.json"
MANIFEST = ".codex-plugin/plugin.json"
LEGACY_PLUGINS = ("dev", "prod")
PLUGINS = (*LEGACY_PLUGINS, "guard")
WAVE_FILE = "wave.json"
WAVE_LABEL = "dispatch_wave"
PREFIX = "dispatch-wave-"
CODEX_VERSION = "codex-cli 0.172.0"
TIMEOUT = 25
HOOK_ENTRYPOINT = re.compile(
    r'(?:python3?|bash) "(?:\$env:PLUGIN_ROOT|\$\{PLUGIN_ROOT\}'
    r'|\$\{CLAUDE_PLUGIN_ROOT:-\$\{PLUGIN_ROOT:\?set CLAUDE_PLUGIN_ROOT or PLUGIN_ROOT\}\})'
    r'/(?P<path>hooks/[A-Za-z0-9_./-]+)"'
)


class PinError(Exception):
    """The launch cannot prove it will run the verified snapshot."""


def command(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, encoding="utf-8", timeout=TIMEOUT, **kwargs).stdout


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def wave_path(value):
    path = Path(value).expanduser().absolute()
    temp = Path(tempfile.gettempdir()).resolve()
    if (path.name != WAVE_FILE or not path.parent.name.startswith(PREFIX)
            or path.parent.parent.resolve() != temp or path.resolve() != temp / path.parent.name / WAVE_FILE):
        raise PinError("expected a wave receipt created by dispatch pin in the local temp directory")
    return path.resolve()


def reparse(info):
    return getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT


def file_hash(path):
    info = path.lstat()
    if info.st_nlink != 1 or not stat.S_ISREG(info.st_mode) or reparse(info):
        raise PinError(f"expected an ordinary file: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tree_hash(root):
    digest = hashlib.sha256()

    def visit(directory):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or reparse(info):
            raise PinError(f"expected an ordinary directory: {directory}")
        for item in sorted(directory.iterdir()):
            mode = item.lstat().st_mode
            if stat.S_ISDIR(mode):
                visit(item)
            else:
                entry = [item.relative_to(root).as_posix(), mode & 0o111, file_hash(item)]
                digest.update(json.dumps(entry).encode("ascii"))

    visit(root)
    return digest.hexdigest()


def catalog_plugins(catalog):
    sources = {entry["name"]: entry["source"] for entry in catalog["plugins"]}
    for names in (PLUGINS, LEGACY_PLUGINS):
        expected = {name: {"source": "local", "path": f"./{name}"} for name in names}
        if catalog["name"] == "kadragon" and len(catalog["plugins"]) == len(names) and sources == expected:
            return names
    raise PinError("unsupported agent-toolkit marketplace layout")


def export_snapshot(repo, commit, source):
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise PinError("use the full verified agent-toolkit commit ID")
    git = ["git", "-C", str(repo)]
    if command([*git, "rev-parse", "--verify", f"{commit}^{{commit}}"]).strip() != commit:
        raise PinError("the supplied ID is not the commit being exported")
    catalog = json.loads(command([*git, "show", f"{commit}:{CATALOG}"]))
    names = catalog_plugins(catalog)
    data = subprocess.run([*git, "archive", "--format=tar", commit, "--", CATALOG, *names],
                          check=True, capture_output=True, timeout=TIMEOUT).stdout
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive:
            relative = PurePosixPath(member.name)
            if (not relative.parts or relative.is_absolute() or ".." in relative.parts
                    or any(re.search(r'[\\:*?"<>|\x00-\x1f]', part) for part in relative.parts)
                    or not (member.isfile() or member.isdir())):
                raise PinError(f"unsupported archive entry: {member.name!r}")
            path = source.joinpath(*relative.parts)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream, path.open("xb") as output:
                    shutil.copyfileobj(stream, output)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
    return catalog, names


def home_env(root):
    return {**os.environ, "CODEX_HOME": str(root / "home")}


def codex_command(root, binary, *args, cwd=None):
    return command([binary, *args], cwd=cwd or root, env=home_env(root))


def effective_settings(home):
    config_file = home / "config.toml"
    file_hash(config_file)
    with config_file.open("rb") as stream:
        config = tomllib.load(stream)
    config.pop("projects", None)
    tui = config.get("tui")
    if isinstance(tui, dict) and tui.get("screen_reader_detection_done") is True:
        # Codex 0.172.0 writes this marker during startup on Windows.
        del tui["screen_reader_detection_done"]
        if not tui:
            del config["tui"]
    hooks = config.get("hooks")
    if isinstance(hooks, dict):
        hooks.pop("state", None)
        if not hooks:
            del config["hooks"]
    return config


def cache_path(root, wave, name):
    return root / "home/plugins/cache" / wave["market"] / name / wave["versions"][name]


def verify_files(path, wave, *, check_binary=True):
    root = path.parent
    if effective_settings(root / "home") != wave["settings"]:
        raise PinError("isolated Codex settings changed")
    if tree_hash(root / "source") != wave["source_hash"]:
        raise PinError("pinned marketplace source changed")
    if check_binary and file_hash(Path(wave["binary"])) != wave["binary_hash"]:
        raise PinError("pinned Codex executable changed")
    for name in wave["versions"]:
        cache = cache_path(root, wave, name)
        if (cache.resolve() != cache or {p.name for p in cache.parent.iterdir()} != {cache.name}
                or tree_hash(cache) != wave["cache_hash"][name]):
            raise PinError(f"pinned {name} plugin cache changed")


def read_wave(path):
    wave = read_json(path)
    if (not isinstance(wave, dict) or wave.get("schema") != 1 or wave.get("market") != path.parent.name
            or set(wave["versions"]) not in (set(PLUGINS), set(LEGACY_PLUGINS))
            or any(not re.fullmatch(r"\d+\.\d+\.\d+", v) for v in wave["versions"].values())):
        raise PinError("invalid or unsupported wave receipt")
    return wave


def protect_tree(path):
    for directory, _, files in os.walk(path, topdown=False):
        parent = Path(directory)
        for name in files:
            file = parent / name
            file.chmod(file.stat().st_mode & ~0o222)
        if os.name != "nt":
            parent.chmod(0o555)


def remove(root):
    root = wave_path(root / WAVE_FILE).parent
    if os.name != "nt":
        for tree in (root / "source", root / "home/plugins/cache"):
            if tree.resolve().is_relative_to(root) and not tree.is_symlink():
                for directory, _, _ in os.walk(tree):
                    Path(directory).chmod(0o700)

    def remove_readonly(function, name, error):
        path = Path(name)
        if not (os.name == "nt" and isinstance(error, PermissionError) and path.resolve().is_relative_to(root)
                and stat.S_ISREG(path.lstat().st_mode) and not reparse(path.lstat())):
            raise error
        path.chmod(stat.S_IWRITE)
        function(path)

    shutil.rmtree(root, onexc=remove_readonly)


def prepare(repo, commit, binary):
    binary = Path(binary).expanduser().resolve()
    if binary.name.lower() != ("codex.exe" if os.name == "nt" else "codex"):
        raise PinError("pass the path to the native Codex executable")
    root = Path(tempfile.mkdtemp(prefix=PREFIX)).resolve()
    try:
        home = root / "home"
        home.mkdir()
        if codex_command(root, str(binary), "--version").strip() != CODEX_VERSION:
            raise PinError(f"the isolation adapter was verified with {CODEX_VERSION}")
        (home / "config.toml").write_text('cli_auth_credentials_store = "file"\n', encoding="utf-8")
        source = root / "source"
        catalog, names = export_snapshot(repo, commit, source)
        market_id = root.name
        catalog["name"] = market_id
        (source / CATALOG).write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
        wave = {"schema": 1, "commit": commit, "market": market_id, "binary": str(binary),
                "binary_hash": file_hash(binary), "source_hash": tree_hash(source),
                "versions": {}, "cache_hash": {}, "children": []}
        added = json.loads(codex_command(root, str(binary), "plugin", "marketplace", "add", str(source), "--json"))
        if added["marketplaceName"] != market_id or Path(added["installedRoot"]).resolve() != source:
            raise PinError("Codex did not register the isolated local marketplace")
        for name in names:
            version = read_json(source / name / MANIFEST)["version"]
            if not re.fullmatch(r"\d+\.\d+\.\d+", version):
                raise PinError(f"unsupported {name} version: {version!r}")
            wave["versions"][name] = version
            plugin_id = f"{name}@{market_id}"
            installed = json.loads(codex_command(root, str(binary), "plugin", "add", plugin_id, "--json"))
            if installed["pluginId"] != plugin_id or Path(installed["installedPath"]).resolve() != cache_path(root, wave, name):
                raise PinError(f"Codex installed {name} outside its pinned version directory")
            wave["cache_hash"][name] = tree_hash(source / name)
        wave["settings"] = effective_settings(home)
        local = wave["settings"]["marketplaces"][market_id]
        if (set(wave["settings"]) != {"marketplaces", "plugins", "cli_auth_credentials_store"}
                or wave["settings"]["cli_auth_credentials_store"] != "file"
                or wave["settings"]["plugins"] != {f"{p}@{market_id}": {"enabled": True} for p in names}
                or set(wave["settings"]["marketplaces"]) != {market_id}
                or local["source_type"] != "local" or not Path(local["source"]).samefile(source)):
            raise PinError("Codex created unexpected isolated settings")
        path = root / WAVE_FILE
        wave["hooks"], trusted = hook_inventory(path, wave, root)
        if not wave["hooks"] or trusted:
            raise PinError("expected an isolated inventory of hooks pending review")
        verify(path, wave, root)
        protect_tree(source)
        for name in names:
            protect_tree(cache_path(root, wave, name))
        path.write_text(json.dumps(wave, ensure_ascii=False), encoding="utf-8")
        return path, wave
    except BaseException:
        remove(root)
        raise


def hook_inventory(path, wave, cwd):
    root = path.parent
    response = inspect_hooks(root, wave["binary"], cwd)
    [group] = response["data"]
    if Path(group["cwd"]).resolve() != cwd or group["warnings"] or group["errors"]:
        raise PinError("Codex hook inventory could not be verified for the target directory")
    hooks = {}
    trusted = True
    owner = "guard" if "guard" in wave["versions"] else "dev"
    for hook in group["hooks"]:
        name, _, market = (hook["pluginId"] or "").partition("@")
        if (market != wave["market"] or name != owner or hook["source"] != "plugin"
                or not hook["enabled"] or hook["isManaged"] or not hook["currentHash"]
                or hook["key"] in hooks):
            raise PinError("an unexpected, inactive or managed hook is visible in the target")
        cache = cache_path(root, wave, name)
        manifest = read_json(cache / MANIFEST)
        declared = cache / manifest.get("hooks", "hooks/hooks.json")
        source = Path(hook["sourcePath"]).resolve()
        if declared.resolve() != source or not source.is_relative_to(cache):
            raise PinError("Codex loaded hooks outside the verified plugin manifest")
        entry = HOOK_ENTRYPOINT.fullmatch(hook["command"])
        if not entry:
            raise PinError("Codex hook command has no verifiable plugin entrypoint")
        script = (cache / entry["path"]).resolve()
        if not script.is_relative_to(cache / "hooks"):
            raise PinError("Codex hook entrypoint leaves its pinned hooks directory")
        file_hash(script)
        hooks[hook["key"]] = [source.relative_to(root).as_posix(), hook["currentHash"], hook["command"]]
        trusted = trusted and hook["trustStatus"] == "trusted"
    return hooks, trusted


def inspect_hooks(root, binary, cwd):
    with subprocess.Popen([binary, "app-server"], cwd=cwd, env=home_env(root), stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8") as proc:
        incoming = queue.Queue()

        def read():
            try:
                for line in proc.stdout:
                    incoming.put(line)
            finally:
                incoming.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + TIMEOUT

        def send(message):
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def receive(id_):
            while time.monotonic() < deadline:
                line = incoming.get(timeout=max(0, deadline - time.monotonic()))
                if line is None:
                    break
                data = json.loads(line)
                if data.get("id") == id_:
                    if "result" not in data:
                        raise PinError("Codex could not verify the hook inventory")
                    return data["result"]
            raise PinError("Codex app server did not answer")

        try:
            send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "dispatch", "version": "1"},
                "capabilities": {"experimentalApi": True},
            }})
            if Path(receive(1)["codexHome"]).resolve() != root / "home":
                raise PinError("Codex app server loaded a different home")
            send({"method": "initialized"})
            send({"id": 2, "method": "hooks/list", "params": {"cwds": [str(cwd)]}})
            return receive(2)
        except queue.Empty:
            raise PinError("Codex app server did not answer") from None
        finally:
            proc.kill()
            reader.join(timeout=TIMEOUT)


def verify(path, wave, cwd):
    verify_files(path, wave)
    root = path.parent
    data = json.loads(codex_command(root, wave["binary"], "plugin", "list", "--marketplace",
                                   wave["market"], "--json", cwd=cwd))
    installed = {entry["pluginId"]: entry for entry in data["installed"]}
    if set(installed) != {f"{p}@{wave['market']}" for p in wave["versions"]}:
        raise PinError("Codex did not load the complete pinned marketplace")
    for name in wave["versions"]:
        entry = installed[f"{name}@{wave['market']}"]
        if (not entry["enabled"] or entry["version"] != wave["versions"][name]
                or entry["source"]["source"] != "local"
                or Path(entry["source"]["path"]).resolve() != root / "source" / name):
            raise PinError(f"Codex resolved {name} to a different marketplace source")
    hooks, trusted = hook_inventory(path, wave, cwd)
    if hooks != wave["hooks"]:
        raise PinError("Codex hook definitions differ from the verified snapshot")
    verify_files(path, wave)
    return trusted


def ensure_shared_guards_are_preserved(home):
    try:
        config = effective_settings(home)
    except FileNotFoundError:
        config = {}
    policy = {"approval_policy", "approval_rules", "approvals_reviewer", "permissions", "sandbox_mode",
              "sandbox_workspace_write", "shell_environment_policy", "default_permissions", "hooks", "profile",
              "allow_login_shell", "features"}
    guards = sorted(policy.intersection(config))
    if (home / "hooks.json").exists():
        guards.append("hooks.json")
    if any((home / "rules").glob("*.rules")):
        guards.append("rules")
    if guards:
        raise PinError(f"isolated home would omit shared guards ({', '.join(guards)}); use shared-cache readiness")


def verify_herdr():
    schema = json.loads(command(["hc", "schema"]))
    params = next((m["params"] for m in schema["methods"] if m["name"] == "terminal.run"), [])
    if not {"env", "argv", "labels", "parent", "no_notify", "outlive_parent"} <= {p["name"] for p in params}:
        raise PinError("Herdr cannot prove per-terminal environment support; use shared-cache readiness")
