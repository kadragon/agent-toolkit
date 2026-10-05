# Bulk Edits

Moved out of SKILL.md Workflow 2. Read before a multi-item, multi-cell, or N-file edit. The single-file flow, the Hancom-open gate, and the row-delete gate stay in SKILL.md.

## Bulk / multi-stage edits

Many items → split into stages to catch silent failures early, verify each stage in Hancom.

1. **unpack once** — run **`HWPX_WORK=$(mktemp -d .hwpx_work_XXXXXX)`** first, then `python3 "$SKILL_DIR/scripts/office.py" unpack document.hwpx "$HWPX_WORK/unpacked/"`. Stage 3 packs into `$HWPX_WORK/step_N.hwpx`. Unique dir per session avoids `.hwpx_work/` and `./unpacked/` collisions when two sessions run concurrently in the same CWD. All later stages cumulatively modify `$HWPX_WORK/unpacked/Contents/section0.xml`.
2. **Per-stage scripts**: write each stage as small `.py`, put **`assert s.count(old) == expected`** on every `str.replace()`. Count off → aborts before corrupted file produced (`references/editing-gotchas.md` §3).
3. **Each stage: pack → validate → confirm opens in Hancom**, then proceed. Package per-stage output as `$HWPX_WORK/step_N.hwpx` to avoid file-lock conflicts.
4. After all stages pass, apply final version to real file. Clean up: `rm -rf "$HWPX_WORK"`. On failure, the dir is preserved for artifact inspection — clean manually when done.

**Multi-cell dir-mode**: when replacing many cells in one file, use `table.py replace` directly on the unpacked dir — reads/writes section0.xml in-place, no zip overhead per call:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
HWPX_WORK=$(mktemp -d .hwpx_work_XXXXXX)  # or reuse the dir from step 1 (mktemp -d .hwpx_work_XXXXXX + office.py unpack)
python3 "$SKILL_DIR/scripts/office.py" unpack document.hwpx "$HWPX_WORK/unpacked/"  # skip if reusing an already-unpacked dir from step 1
python3 "$SKILL_DIR/scripts/table.py" replace "$HWPX_WORK/unpacked/" --table-id TABLE_ID --cell 2,1 --para 0 0 "값1"
python3 "$SKILL_DIR/scripts/table.py" replace "$HWPX_WORK/unpacked/" --table-id TABLE_ID --cell 3,1 --para 0 0 "값2"
python3 "$SKILL_DIR/scripts/office.py" pack "$HWPX_WORK/unpacked/" result.hwpx
```

> ⚠️ `--para 0 0 ""` resets charPrIDRef to 0 (default style) — original run styling is lost. To replace cell text while preserving the original character style, prefer `--preserve-style --text "새내용"` — it reads the existing paraPrIDRef and charPrIDRef from the cell automatically. For clearing a single contiguous text run, `--set-text OLD ""` also works (requires text to be contiguous in a single `<hp:t>` node).

## Bulk File Edit — N files simultaneously

Pattern for editing N template-based files simultaneously:

```python
import sys
sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 guard
import shutil
import subprocess
from pathlib import Path

SKILL_DIR = Path("/path/to/skills/hwpx")  # set to absolute path of this skill
UNPACK_PY = str(SKILL_DIR / "scripts/office.py")
PACK_PY = str(SKILL_DIR / "scripts/office.py")
VALIDATE_PY = str(SKILL_DIR / "scripts/validate.py")

# 파일별 데이터를 설정으로 분리
FILES = [
    {"src": "template_A.hwpx", "out": "result_A.hwpx", "name": "홍길동", "dept": "총무과"},
    {"src": "template_B.hwpx", "out": "result_B.hwpx", "name": "이순신", "dept": "인사과"},
]

try:
    for cfg in FILES:
        slug = Path(cfg["out"]).stem
        unpack_dir = Path(f".hwpx_work/unpack_{slug}/")  # slug 포함 필수 — 충돌 방지

        subprocess.run(["python3", UNPACK_PY, "unpack", cfg["src"], str(unpack_dir)], check=True)
        section_path = unpack_dir / "Contents/section0.xml"
        s = section_path.read_text(encoding="utf-8")

        # 파일별 값 치환
        assert s.count("<hp:t>이름</hp:t>") == 1
        s = s.replace("<hp:t>이름</hp:t>", f'<hp:t>{cfg["name"]}</hp:t>')

        section_path.write_text(s, encoding="utf-8")

        # 필수: 텍스트를 바꿨으면 줄바꿈 캐시를 버린다 (rule 19).
        # 생략하면 치환 텍스트가 원본보다 짧아 줄 수가 줄었을 때 한글이 로드에
        # 실패하고 빈 문서를 띄운다 — validate.py는 --baseline 없이는 못 잡는다.
        subprocess.run(
            ["python3", str(SKILL_DIR / "scripts/table.py"), "strip-lineseg", str(section_path), "--inplace"],
            check=True,
        )

        tmp_out = Path(f".hwpx_work/{slug}_tmp.hwpx")
        subprocess.run(["python3", PACK_PY, "pack", str(unpack_dir), str(tmp_out)], check=True)
        subprocess.run(["python3", VALIDATE_PY, "validate", str(tmp_out), "--baseline", cfg["src"]], check=True)  # do NOT add capture_output=True here — stderr must be visible for debugging
        shutil.copy(tmp_out, cfg["out"])
        print(f"[done] {cfg['out']}")
finally:
    # 성공/실패 모두 정리 — 실패 시 .hwpx_work/ 에서 아티팩트 디버그 가능
    shutil.rmtree(".hwpx_work", ignore_errors=True)
```

- Include slug in `unpack_dir` — prevents directory collision in N-file parallel runs
- `validate --baseline` first, overwrite second — maintain order (see SKILL.md Workflow 2 "Validate timing when overwriting original")
- `--baseline` is what makes the stale-linesegarray check run at all: it flags paragraphs whose text changed while the line-break cache was carried over unchanged. Without it that failure is invisible to `validate.py`
- After each stage, open at least one file in Hancom to verify — `validate.py` checks structure only
