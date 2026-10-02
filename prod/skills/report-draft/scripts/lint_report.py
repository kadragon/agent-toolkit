#!/usr/bin/env python3
"""Lint a Korean government-style report (개조식 보고서) for house-style rules.

Input: a .hwpx file or a UTF-8 text file (one paragraph per line).
Exit 0 = no FAIL. WARN lines never change the exit code.

Rules
  R1  numbered heading (`1.`, `2.`) in body — use `□` (skip with --allow-numbered for 기관 서식)
  R2  bullet level skip — `-` needs a `○` (or 서식 `◦`) parent in the same block (WARN: 1쪽 보고서가 □ 바로 아래 `-`를 쓰는 관행 있음)
  R3  remedy phrase inside 현황/문제점 — state facts only, remedies go to 추진 계획
  R4  polite ending (`~습니다`) — reports use 개조식 endings (`~함`, `~음`, `~임`)
  R5  date format — write `2026. 9. 21.` (not `2026-09-21`, `2026.9.21`, `2026년 9월`)
  R6  향후 계획 cites 실적/만족도/결과 without naming the base year (`2026학년도`, `2026년`)
  R7  weekday does not match the date — `2026. 8. 28.(금)` must be a real Friday
  R8  time not in 24-hour `HH:MM` form (`오후 2시`, `14시 30분` → `14:30`)
  R9  rhetoric — question/exclamation mark or `~것이다` ending in a report line
  R10 (WARN) item longer than 80 characters — about two lines at 15pt; split or move detail to `-`/`※`
  R11 (WARN) vague word (`적극`, `최대한`, `만전`, `가능한 한`, `등등`) — state the concrete action or number
  R12 (WARN) unfilled placeholder (`○○`, `△△`, `[확인 필요]`) — fill or report as open before handoff
  R13 unpaired `**` bold marker (text drafts)

Lines after an attachment heading (`[붙임 1]`, `붙임 2`, `[별첨]`) are not checked:
attachments are forms and quoted documents, not report body.

Usage
  python3 lint_report.py <file.hwpx|file.txt> [--allow-numbered]
  python3 lint_report.py --test
"""
import datetime
import re
import sys
import zipfile

import defusedxml.ElementTree as ET

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
ROMAN = re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]$")
NUMBERED = re.compile(r"^\s*\d{1,2}\.\s+\S")
REMEDY = re.compile(r"필요가 있음|필요함|필요성|해야 함|하여야 함|강화할|개선할|도입할|추진할|마련할|방안|시급")
POLITE = re.compile(r"(습니다|합니다|됩니다|입니다)\.?\s*$")
BAD_DATE = [
    (re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"), "ISO date"),
    (re.compile(r"\b\d{4}\.\d{1,2}\.(\d{1,2}\.)?"), "date without spaces"),
    (re.compile(r"\d{4}년\s*\d{1,2}월"), "년/월 date"),
]
EVIDENCE = re.compile(r"실적|만족도|결과|성과")
YEAR = re.compile(r"(19|20)\d{2}(학년도|년|\.\s*\d)|’\d{2}\.")
ATTACH = re.compile(r"^\s*(\[\s*(붙임|별첨)\s*\d*\s*\]|(붙임|별첨)\s*\d+\.?(\s|$)|(붙임|별첨)\s*$|(붙임|별첨)\s{2,})")
ROMAN_INLINE = re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.?\s+(\S.*)$")
LABEL_MAX = 12        # a ○ line this short is a label (`○ 향후 계획`), not a sentence
WEEKDAY_DATE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*\(([월화수목금토일])\)")
WEEKDAYS = "월화수목금토일"
BAD_TIME = re.compile(r"(오전|오후)\s*\d{1,2}\s*시|\b\d{1,2}\s*시\s*\d{1,2}\s*분|\b\d{1,2}시(?=\s*[~∼부까]|\s*$)")
RHETORIC = re.compile(r"[?!？！]|것이다\.?\s*$")
VAGUE = re.compile(r"적극(?!행정)|최대한|만전|가능한 한|등등")
PLACEHOLDER = re.compile(r"○○|△△|\[확인 필요\]")
ITEM_MAX = 80
BULLET = re.compile(r"^\s*(□|○|◦|-|※|\*+)\s*")
BOLD_PAIR = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
UNCLOSED_BOLD = re.compile(r"(?<!^)\*\*(?=[^\s,.)·])")


def paragraphs_from_hwpx(path):
    out = []
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n))
        for n in names:
            root = ET.fromstring(z.read(n))
            for p in root.iter(HP + "p"):
                text = "".join(t.text or "" for t in p.findall(HP + "run/" + HP + "t"))
                if text.strip():
                    out.append(text)
    return out


def load(path):
    if path.lower().endswith(".hwpx"):
        return paragraphs_from_hwpx(path)
    with open(path, encoding="utf-8-sig") as f:
        return [line.rstrip("\n") for line in f]   # blank lines kept so L%d matches the file


def lint(lines, allow_numbered=False):
    """Return list of (level, rule, lineno, message, text)."""
    res = []
    chapter = ""          # current chapter title (after a roman numeral line)
    box = ""              # current □ heading
    has_circle = False    # a ○ seen since the last □ / chapter
    label = ""            # innermost short ○ label (`○ 성과`, `○ 향후 계획`)
    expect_title = False
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s:
            continue
        if ATTACH.match(s):
            break
        if ROMAN.match(s):
            expect_title = True
            continue
        m = ROMAN_INLINE.match(s)
        if m:
            chapter, box, label, has_circle, expect_title = m.group(1), "", "", False, False
            continue
        if expect_title:
            chapter, box, label, has_circle, expect_title = s, "", "", False, False
            continue
        if s.startswith("□"):
            box, label, has_circle = s, "", False
        elif s.startswith(("○", "◦")):  # ◦ = ○ in 본부 배포 서식
            has_circle = True
            label = s if len(BULLET.sub("", s)) <= LABEL_MAX else ""
        elif s.startswith("- ") and not has_circle:
            res.append(("WARN", "R2", i, "`-` without a `○` parent — add the ○ level or promote to ○", s))

        if not allow_numbered and NUMBERED.match(raw):
            res.append(("FAIL", "R1", i, "numbered heading — use `□`", s))

        scope = chapter + " " + box
        in_status = ("현황" in scope or "문제점" in scope) and not s.startswith("□")
        m = REMEDY.search(s) if in_status else None
        if m:
            res.append(("FAIL", "R3", i, "remedy in 현황/문제점 — keep facts only (%s)" % m.group(0), s))

        if POLITE.search(s):
            res.append(("FAIL", "R4", i, "polite ending — use 개조식 (~함/~음/~임)", s))

        for pat, name in BAD_DATE:
            if pat.search(s):
                res.append(("FAIL", "R5", i, "%s — write `YYYY. M. D.`" % name, s))
                break

        topic = label or box or chapter
        if "향후" in topic and EVIDENCE.search(s) and not YEAR.search(s) and s != topic:
            res.append(("FAIL", "R6", i, "향후 계획 cites 실적/만족도 without a base year", s))

        for m in WEEKDAY_DATE.finditer(s):
            y, mo, d, wd = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
            try:
                real = WEEKDAYS[datetime.date(y, mo, d).weekday()]
            except ValueError:
                res.append(("FAIL", "R7", i, "invalid date %s" % m.group(0), s))
                continue
            if real != wd:
                res.append(("FAIL", "R7", i, "%s is %s요일, not %s" % (m.group(0), real, wd), s))

        if BAD_TIME.search(s):
            res.append(("FAIL", "R8", i, "time — write 24-hour `HH:MM`", s))

        if RHETORIC.search(s):
            res.append(("FAIL", "R9", i, "rhetoric (?, !, ~것이다) — state the fact", s))

        body = BULLET.sub("", s)
        if BULLET.match(s) and len(body) > ITEM_MAX:
            res.append(("WARN", "R10", i, "item %d chars > %d — split or move detail down" % (len(body), ITEM_MAX), s))

        m = VAGUE.search(s)
        if m:
            res.append(("WARN", "R11", i, "vague word `%s` — state the action or number" % m.group(0), s))

        m = PLACEHOLDER.search(s)
        if m:
            res.append(("WARN", "R12", i, "unfilled `%s`" % m.group(0), s))

        # footnote marks (`Team**,` / `** 설명`) stay; an opening `**word` with no close is a broken bold
        if UNCLOSED_BOLD.search(BULLET.sub("", BOLD_PAIR.sub("", s))):
            res.append(("FAIL", "R13", i, "unpaired `**` bold marker", s))
    return res


def selftest():
    good = [
        "Ⅱ", "현황 및 문제점",
        "□ 현황",
        " ○ 2025학년도 지원 계정의 실사용과 만족도가 높게 확인됨",
        "       ※ 만족도 4.83",
        "□ 문제점",
        " ○ (미사용 계정) 지원 190명 중 19명(10.0%)이 활용하지 않음",
        "Ⅳ", "사업 추진 계획",
        "□ 향후 추진 계획",
        " ○ 2026학년도 이용 실적과 만족도를 근거로 2027학년도 본예산에 반영",
        "   - 일정: 2026. 10. 15. ~ 2027. 5. 14.",
        " ○ 평가일시: 2026. 8. 28.(금) 14:00~",
        " ○ 2026 하반기 적극행정 우수사례 제출",
        "□ 성과 및 향후 계획",
        " ○ 성과",
        "   - 누적 313,425건의 실사용과 만족도 4.83점을 확인",
        " ○ 향후 계획",
        "   - 2026학년도 실적을 근거로 도구 선택형 지원으로 전환",
        "   - 2026. 8. 정기점검 결과를 근거로 교체 계약 추진",
        "[붙임 1] 개인정보 수집·이용 동의서",
        "본인은 위 내용에 동의합니다.",
        "2026년 8월 28일",
    ]
    footnotes = [
        " ○ ChatGPT Team*, Claude Team** 중 1종 선택 지원",
        "       ** Anthropic의 기업용 요금제",
        " ○ 예산: **총 60,935,000원**(금육천구십삼만오천원)",
    ]
    assert lint(footnotes) == [], lint(footnotes)
    form = ["□ 성과지표 및 목푯값", " ◦ 지표 설정 근거", "   - 전년도 만족도 결과로 설정함"]
    assert lint(form) == [], lint(form)
    assert lint(good) == [], lint(good)
    bad = {
        "R1": ["1. 수요조사 기반 구독권 제공"],
        "R2": ["□ 개요", "   - 하위 항목"],
        "R3": ["Ⅱ", "현황 및 문제점", " ○ 회수 기준을 강화할 필요가 있음"],
        "R4": [" ○ 지원하였습니다."],
        "R5": [" ○ 기간: 2026-10-15"],
        "R6": ["□ 향후 추진 계획", " ○ 이용 실적과 만족도를 근거로 본예산에 반영"],
        "R7": [" ○ 평가일시: 2026. 8. 28.(목)"],
        "R8": [" ○ 일시: 2026. 8. 28.(금) 오후 2시"],
        "R9": [" ○ 이제는 도구 선택형 지원이 답이 될 것이다."],
        "R10": [" ○ " + "가" * 81],
        "R11": [" ○ 관계 부서와 적극 협조하여 추진"],
        "R12": [" ○ 예산: 총 ○○천원"],
        "R13": [" ○ 예산 **총 60,935천원 확보"],
    }
    for rule, lines in bad.items():
        got = {r[1] for r in lint(lines)}
        assert rule in got, (rule, got)
    assert lint(["1. 사업부서"], allow_numbered=True) == []
    # a line-leading bold pair is not an unpaired marker
    assert lint([" ○ **총 예산**은 60,935천원임", "**총 예산**은 60,935천원임"]) == []
    # body text that merely starts with 붙임/별첨 does not end the check
    assert "R4" in {r[1] for r in lint(["붙임 자료와 같이 진행함", " ○ 지원하였습니다."])}
    assert lint(["붙임  1. 참석자 명단 1부.", " ○ 지원하였습니다."]) == []
    # a one-line roman chapter heading still scopes R3
    assert "R3" in {r[1] for r in lint(["Ⅱ. 현황 및 문제점", " ○ 회수 기준을 강화할 필요가 있음"])}
    # line numbers count blank lines in a text draft
    import os
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as f:
        f.write("□ 개요\n\n ○ 지원하였습니다.\n")
    try:
        assert [r[2] for r in lint(load(f.name))] == [3], lint(load(f.name))
    finally:
        os.unlink(f.name)
    print("selftest ok")


def main(argv):
    if "--test" in argv:
        selftest()
        return 0
    paths = [a for a in argv if not a.startswith("--")]
    if len(paths) != 1:
        print(__doc__)
        return 2
    res = lint(load(paths[0]), allow_numbered="--allow-numbered" in argv)
    for level, rule, n, msg, text in res:
        print("[%s] %s L%d: %s\n      %s" % (level, rule, n, msg, text))
    fails = sum(1 for r in res if r[0] == "FAIL")
    print("%d FAIL" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    sys.exit(main(sys.argv[1:]))
