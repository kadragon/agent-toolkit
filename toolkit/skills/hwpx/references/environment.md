# HWPX Skill — Environment Reference

## Python Invocation

| OS | Command | Note |
|----|---------|------|
| Windows | `python` (system) or `.venv\Scripts\python` | `python3` alias usually absent |
| macOS/Linux | `python3` or `.venv/bin/python` | |

- venv optional. If `python -c "import lxml"` succeeds, use as-is. Otherwise `pip install lxml`.
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

## Special Character Matching

Quote variants (`ʹ` U+02B9 vs U+0374), PUA (U+F0E8), dash/middle-dot variants, and other visually-similar glyphs are encoding-unstable when typed as literals in a script or heredoc — the same glyph can resolve to a different codepoint each run.

**Always specify special characters via `'\uXXXX'` escapes**, not literal characters.

## Non-ASCII Matching Logic — No `python -c`

Putting non-ASCII characters (`■`, `○`, Korean) into `python -c "..."` source and running via Bash can corrupt them in transit through shell encoding, causing silent failure where `str.index()`/`rfind()` returns `-1`.

**Write check/replace code with non-ASCII matching to a `.py` file** using the Write tool, then run via `python script.py`.

## Temp Files

Use the **working document's folder** for temp files (e.g. `./_work/`), not `/tmp`.

Windows `python` interprets `/tmp` as a drive-relative path, which diverges from the Bash tool's `/tmp` — use project-relative paths only.
