#!/usr/bin/env python3
"""Detect translationese and AI-tell patterns in Korean prose.

Reads a UTF-8 text file (or stdin with `-`) and reports pattern hits with line
numbers. Two severities:

  S1  always a defect regardless of frequency (double passive, `에 의해` passive,
      `가지고 있다`, comma after a connective ending)
  S2  a defect only past a density threshold (`를 통해`, sentence-initial
      conjunctions, `것이다` endings)

Exit 0 = clean, 1 = at least one S1 hit or one S2 threshold breach. That exit
code is the completion criterion for the `kr-style` skill: rewrite, re-run,
land on 0.

The checks here are the mechanically decidable subset only. Subject dropping,
double-subject constructions, `은/는` vs `이/가`, and head-final ordering carry
no reliable surface signal and stay on the skill's manual checklist.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    """One detector. `limit` None means every hit is a defect (S1)."""

    id: str
    name: str
    pattern: str
    fix: str
    limit: int | None = None

    @property
    def severity(self) -> str:
        return "S1" if self.limit is None else "S2"


# Ordered by the axis they come from: syntax transfer, inflection transfer,
# preposition transfer, then AI-tell surface habits.
RULES: tuple[Rule, ...] = (
    # --- 구문 형식 (syntax transfer) ---
    Rule("P1", "이중 피동", r"되어[지졌진]|지게 되[다었]|보여질", "단일 피동 또는 능동으로"),
    Rule("P2", "'에 의해' 피동", r"에 의하?[여해]", "행위자를 주어로 — '팀에 의해 개발' → '팀이 개발'"),
    Rule("P3", "have 구문 직역", r"[가갖][지고]고 있", "'X가 있다' 또는 형용사로 — '성능을 가지고 있다' → '성능이 우수하다'"),
    Rule("P4", "무생물 주어 + 만능 동사", r"[은는이가] (?:[가-힣]+을|[가-힣]+를) (?:제공한|가져온|보여준|일으킨)", "구체 주어로 환원하거나 부사절로"),
    # --- 굴절 형식 (inflection transfer) ---
    Rule("P5", "수량어 + '-들' 중복", r"(?:여러|많은|다양한|모든|\d+\s*(?:개|가지)의?)\s+[가-힣]+들", "'-들'은 의미를 바꾸는 요소 — 수량어가 있으면 뺀다"),
    Rule("P6", "영어식 대명사", r"그녀|그것들|그들의", "영형(생략)이나 호칭-명사구로", limit=1),
    # --- 전치사구 (preposition transfer) ---
    Rule("P7", "'에 있어(서)'", r"에 있어서?[,\s]", "'~에서' 또는 '~을 볼 때'"),
    Rule("P8", "'~로부터'", r"[으]?로부터", "'~에게서', '~에서'", limit=1),
    Rule("P9", "'~를 통해'", r"[을를] 통[해하][여\s]", "'~로', '~해서'", limit=2),
    Rule("P10", "'~에 대해/대한'", r"에 대[해한][\s,]", "목적격 조사로 직결 — 'X에 대해 논의' → 'X를 논의'", limit=1),
    Rule("P11", "'~와 관련하여'", r"[와과] 관련[하되][여어]|[와과] 관련된", "'~에', '~의'", limit=1),
    Rule("P12", "'~에 기반하여/바탕으로'", r"에 기반[하한]|을 바탕으로|를 바탕으로", "'~로', '~을 보고'", limit=1),
    Rule("P13", "이중 조사", r"에서의|으로의|에의|로의\s", "절로 풀어쓰기"),
    # --- AI-tell 표면 습관 ---
    Rule("P14", "연결어미 뒤 쉼표", r"(?:하고|되고|이며|하며|지만|면서|아서|어서|으며),", "영어식 쉼표 — 쉼표를 뺀다"),
    Rule("P15", "문두 접속사", r"(?m)^\s*(?:또한|따라서|즉|게다가|나아가|아울러|더욱이|그러므로|결론적으로|이를 통해)[\s,]", "문장 순서로 흐름을 만든다", limit=2),
    Rule("P16", "이중 완곡", r"수 있을 것|가능성이 있을 수|로 보여질 수|것으로 보인다", "완곡은 한 겹만"),
    Rule("P17", "'~것이다' 남발", r"것이다|것입니다", "'~다'로 직접 종결", limit=2),
    Rule("P18", "형식명사 강조", r"라는 점에서|다는 것이다|라는 점이다|주목할 점은", "'X는 ~다' 직설로", limit=1),
    Rule("P19", "'~을 위해' 목적절", r"[을를] 위하?[여해]\s", "'~려고', '~도록'", limit=2),
    Rule("P20", "지시관형사 과다", r"이러한|그러한|해당\s", "생략하거나 구체 명사로", limit=2),
    Rule("P21", "명사화 '-적 N'", r"[가-힣]{2,}적\s+[가-힣]{2,}", "'전략적 함의' → '전략 함의'", limit=1),
    Rule("P22", "hype 어휘", r"혁신적|획기적|압도적|전례 없는|파격적", "구체 수치·사실로", limit=1),
)

SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
# A run of identical sentence endings — the rhythm tell no single regex catches.
ENDING = re.compile(r"(습니다|입니다|합니다|된다|한다|이다)[.!?]?\s*$")
MAX_SAME_ENDING_RUN = 3
MAX_COMMA_RATIO = 0.40


@dataclass
class Hit:
    rule: Rule
    line: int
    text: str


@dataclass
class Report:
    hits: list[Hit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        counts: dict[str, int] = {}
        for hit in self.hits:
            counts[hit.rule.id] = counts.get(hit.rule.id, 0) + 1
        for rule_id, count in counts.items():
            rule = next(r for r in RULES if r.id == rule_id)
            if rule.limit is None or count > rule.limit:
                return True
        return bool(self.notes)


def scan(text: str) -> Report:
    report = Report()
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            for match in re.finditer(rule.pattern, line):
                report.hits.append(Hit(rule, lineno, match.group(0).strip()))

    sentences = [s.strip() for s in SENTENCE_SPLIT.split(text) if s.strip()]
    if sentences:
        run, prev = 1, None
        for sentence in sentences:
            match = ENDING.search(sentence)
            current = match.group(1) if match else None
            if current is not None and current == prev:
                run += 1
                if run > MAX_SAME_ENDING_RUN:
                    report.notes.append(
                        f"동일 종결어미 '{current}' {run}문장 연속 — 종결어미를 변주한다"
                    )
                    run = 1
            else:
                run = 1
            prev = current

        with_comma = sum(1 for s in sentences if "," in s)
        ratio = with_comma / len(sentences)
        if ratio > MAX_COMMA_RATIO:
            report.notes.append(
                f"쉼표가 문장의 {ratio:.0%}에 등장 (사람 글 평균 26%) — 영어식 쉼표를 뺀다"
            )
    return report


def render(report: Report, source: str) -> str:
    if not report.hits and not report.notes:
        return f"{source}: clean"

    counts: dict[str, list[Hit]] = {}
    for hit in report.hits:
        counts.setdefault(hit.rule.id, []).append(hit)

    lines = [f"{source}:"]
    for rule in RULES:
        found = counts.get(rule.id)
        if not found:
            continue
        over = rule.limit is None or len(found) > rule.limit
        allowance = "" if rule.limit is None else f" (허용 {rule.limit})"
        mark = "FAIL" if over else "ok"
        lines.append(
            f"  [{mark}] {rule.severity} {rule.id} {rule.name} ×{len(found)}{allowance} — {rule.fix}"
        )
        if over:
            for hit in found[:5]:
                lines.append(f"        L{hit.line}: {hit.text}")
    for note in report.notes:
        lines.append(f"  [FAIL] S2 리듬 — {note}")
    return "\n".join(lines)


def selftest() -> int:
    cases: list[tuple[str, str]] = [
        ("이 기능은 팀에 의해 개발되어졌다.", "P1"),
        ("이 기능은 팀에 의해 개발했다.", "P2"),
        ("우수한 성능을 가지고 있습니다.", "P3"),
        ("여러 파일들을 확인한다.", "P5"),
        ("현대 사회에 있어서 데이터가 중요하다.", "P7"),
        ("API를 통해 데이터를 수집하고 모델을 통해 분석하고 결과를 통해 판단한다.", "P9"),
        ("설정을 확인하고, 서버를 재시작한다.", "P14"),
        ("전략적 함의를 검토한다. 실천적 기반을 다진다.", "P21"),
    ]
    failures: list[str] = []
    for text, expected in cases:
        found = {hit.rule.id for hit in scan(text).hits}
        if expected not in found:
            failures.append(f"{expected!r} not detected in {text!r} (got {sorted(found)})")

    clean = "설정을 확인한 뒤 서버를 재시작한다. 팀이 이 기능을 만들었다. 응답은 30% 빨라졌다."
    clean_hits = scan(clean)
    if clean_hits.failed:
        failures.append(f"clean sample flagged: {render(clean_hits, 'clean')}")

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"ok: {len(cases)} detections + 1 clean sample")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect translationese and AI-tell patterns in Korean prose."
    )
    parser.add_argument("paths", nargs="*", help="UTF-8 text files, or - for stdin")
    parser.add_argument("--test", action="store_true", help="run built-in self-test")
    args = parser.parse_args()

    if args.test:
        return selftest()
    if not args.paths:
        parser.error("give at least one path, or - for stdin")

    failed = False
    for path in args.paths:
        text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
        report = scan(text)
        print(render(report, path))
        failed = failed or report.failed
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
