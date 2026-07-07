# HWPX Skill — Environment Reference

## Python Invocation

| OS | Command | Note |
|----|---------|------|
| Windows | `python` (system) or `.venv\Scripts\python` | `python3` alias usually absent |
| macOS/Linux | `python3` or `.venv/bin/python` | |

**Install required packages first** (`validate.py` needs `defusedxml`; the OLE `.hwp` fallback recipe below needs `olefile`):

```bash
python -m pip install olefile defusedxml
```

> ⚠️ **Use `python -m pip install`, not bare `pip install`.** `python` and `pip` can resolve to *different* interpreters (e.g. a Windows Store Python alias for `pip` vs. a separately-installed `python`) — a reported-successful `pip install` can still leave the `python` you actually run with `ModuleNotFoundError`. `python -m pip install ...` guarantees the install target matches the interpreter that will import it. If this recurs, cross-check with `pip --version` (shows which interpreter it's bound to) vs. `where.exe python` / `which python3`.

- venv optional. If `python -c "import lxml"` succeeds, use as-is. Otherwise `python -m pip install lxml`.
- Workflow examples use `python3` / `source "$VENV"`. **On Windows, use `python` and omit `source` line.**

## SKILL_DIR

`SKILL_DIR` = absolute path of the directory holding SKILL.md (`.../skills/hwpx`).

Scripts reference it as `$SKILL_DIR/scripts/...` in bash examples. In PowerShell, replace with the full absolute path (no `$SKILL_DIR` expansion available).

## Windows Encoding Gotchas

### Console output (Korean/non-ASCII)

`print`ing Korean in diagnostic `python -c "..."` or heredoc produces cp949 mojibake on Windows.

To print Korean safely, add as the first line of any diagnostic script:

```python
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
```

Bundled scripts in `scripts/` apply UTF-8 stdout/stderr internally — no extra step needed. Always specify `encoding="utf-8"` for file I/O.

### subprocess Korean output

`subprocess.run(capture_output=True, text=True)` defaults to cp949 on Windows → `UnicodeDecodeError` on Korean stdout/stderr.

Always pass `encoding` and `errors` explicitly:

```python
subprocess.run(
    [...],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace"
)
```

### PYTHONUTF8 — system-wide UTF-8 for all Python processes

Setting `PYTHONUTF8=1` makes Python use UTF-8 for all text I/O without per-script `sys.stdout.reconfigure`. Eliminates cp949 issues in scripts and inline `python -c "..."` calls.

**Claude Code (project-level)** — add to `.claude/settings.json`:
```json
{
  "env": {
    "PYTHONUTF8": "1"
  }
}
```

**Claude Code (global)** — add to `~/.claude/settings.json` under `"env"`.

When set, the `sys.stdout.reconfigure` calls in bundled scripts become redundant (harmless to keep). Inline `python -c "print('한글')"` also works without extra setup.

## Special Character Matching

Quote variants (`ʹ` U+02B9 vs U+0374), PUA (U+F0E8), dash/middle-dot variants, and other visually-similar glyphs are encoding-unstable when typed as literals in a script or heredoc — the same glyph can resolve to a different codepoint each run.

**Always specify special characters via `'\uXXXX'` escapes**, not literal characters.

## Non-ASCII Matching Logic — No `python -c`

Putting non-ASCII characters (`■`, `○`, Korean) into `python -c "..."` source and running via Bash can corrupt them in transit through shell encoding, causing silent failure where `str.index()`/`rfind()` returns `-1`.

**Write check/replace code with non-ASCII matching to a `.py` file** using the Write tool, then run via `python script.py`.

## Temp Files

Use the **working document's folder** for temp files (e.g. `.hwpx_work/`), not `/tmp`.

Windows `python` interprets `/tmp` as a drive-relative path, which diverges from the Bash tool's `/tmp` — use project-relative paths only.

## Fallback: extracting text from a legacy OLE `.hwp` without Hancom (reference only)

This is a documented workaround for when Hancom/COM isn't available or `convert_hwp.ps1` fails (see the magic-bytes note in SKILL.md Workflow 2/3) — not a new supported script or workflow. Requires `olefile` (`python -m pip install olefile`, see above).

**Fast preview** — the `PrvText` OLE stream holds a plain-text preview capped at roughly the first 1000 characters:

```python
import olefile

with olefile.OleFileIO("file.hwp") as ole:
    if ole.exists("PrvText"):
        data = ole.openstream("PrvText").read()
        print(data.decode("utf-16-le"))
```

**Full body text** — `BodyText/SectionN` streams are raw-deflate compressed (`zlib.decompressobj(-15)`, no zlib header) and contain a sequence of HWPTAG records; walk them and pull text from `HWPTAG_PARA_TEXT` (`0x42`) records:

```python
import zlib
import olefile

HWPTAG_PARA_TEXT = 0x42

def _records(buf: bytes):
    pos = 0
    while pos + 4 <= len(buf):
        header = int.from_bytes(buf[pos:pos + 4], "little")
        tag_id = header & 0x3FF
        length = (header >> 20) & 0xFFF
        pos += 4
        if length == 0xFFF:  # extended length marker
            length = int.from_bytes(buf[pos:pos + 4], "little")
            pos += 4
        yield tag_id, buf[pos:pos + length]
        pos += length

with olefile.OleFileIO("file.hwp") as ole:
    section_names = sorted(
        n for n in ole.listdir() if len(n) == 2 and n[0] == "BodyText" and n[1].startswith("Section")
    )
    text_parts = []
    for name in section_names:
        raw = ole.openstream(name).read()
        data = zlib.decompressobj(-15).decompress(raw)
        for tag_id, payload in _records(data):
            if tag_id == HWPTAG_PARA_TEXT:
                # UTF-16LE, with occasional control/inline-object marker code points to filter
                text_parts.append(payload.decode("utf-16-le", errors="ignore"))
    print("\n".join(text_parts))
```

This is best-effort text extraction only — no formatting/table structure, and inline control characters (footnotes, field markers) need extra filtering for clean output. For anything beyond a quick text preview, prefer `convert_hwp.ps1` (Hancom COM) when available.
