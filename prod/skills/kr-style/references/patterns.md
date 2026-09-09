# Pattern Table

Every rule `kr_audit.py` reports, with the before/after pair that shows what the fix looks
like. Rule IDs match the script's `RULES` table — that script is the enforcement point, this
file is the explanation. `S1` is a defect at any frequency; `S2` is a defect past the
allowance the report prints.

## 구문 형식 — English syntax transferred

English clause shapes that Korean builds differently.

| ID | Pattern | ✗ | ✓ |
|----|---------|---|---|
| P1 | 이중 피동 (S1) | 데이터는 분석되어집니다 | 데이터를 분석합니다 |
| P2 | `~에 의해` 피동 (S1) | 그 강도는 용감한 시민에 의하여 붙잡혔다 | 용감한 시민이 그 강도를 붙잡았다 |
| P3 | `have` 직역 (S1) | 그녀는 아름다운 목소리를 가지고 있다 | 그녀는 목소리가 아름답다 |
| P4 | 무생물 주어 + 만능 동사 (S1) | 이 변경은 성능 향상을 제공한다 | 이 변경으로 응답이 30% 빨라진다 |

**P2 has two branches.** With an agent named, promote the agent to subject. With no agent —
`A good deal of effort was put into…` — Korean uses an active or an intransitive instead:
`엄청난 노력을 기울였다` / `엄청난 노력이 들어갔다`, never `노력이 기울여졌다`.

**P4 is narrower than "no inanimate subjects."** `비가 온다`, `값이 올랐다` are ordinary
Korean. The defect is an inanimate subject driving a transitive verb of influence
(제공한다 / 가져온다 / 보여준다 / 일으킨다). Recast as a 부사절: `X 때문에`, `X 덕분에`, `X로`.

## 굴절 형식 — obligatory inflection transferred

English inflects number, gender, and case obligatorily; Korean does not, so a mechanical
mapping invents distinctions the writer never made.

| ID | Pattern | ✗ | ✓ |
|----|---------|---|---|
| P5 | 수량어 + `-들` (S1) | 새로운 아이디어들과 방법들이 있다 | 여러 가지 남다른 생각과 방법이 있다 |
| P6 | 영어식 대명사 (S2, 1) | 혜숙과 그녀의 어머니는 그들이 듣고 | 혜숙과 어머니는, 듣고 |

**`-들` is not a plural marker to be deleted on sight.** 김정우(1996): `도서관에 책이 많다`
and `도서관에 책들이 많다` differ in meaning — the second says the kinds are various. So
`-들` is a semantic choice, and translating every English `-s` into it either flattens that
distinction or asserts one the source never made. Express plurality with a quantifier or an
adverb, and keep `-들` only where the "various kinds" reading is what you mean.

**P6 is about frequency, not existence.** Korean drops the pronoun (영형) where context
carries it; one `그` in a paragraph is fine, one per sentence is English.

## 전치사구 — prepositions transferred

Each of these is a preposition that acquired a fixed Korean equivalent and then displaced the
native construction.

| ID | Pattern | ✗ | ✓ |
|----|---------|---|---|
| P7 | `~에 있어(서)` (S1) | 현대 사회에 있어서 데이터는 중요하다 | 현대 사회에서 데이터는 중요하다 |
| P8 | `~로부터` (S2, 1) | 그 사람으로부터 잘잘못을 들은 다음 | 그 사람에게서 잘잘못을 들은 다음 |
| P9 | `~를 통해` (S2, 2) | AI를 통해 수집하고 모델을 통해 분석한다 | AI로 수집하고 모델로 분석한다 |
| P10 | `~에 대해/대한` (S2, 1) | 이 문제에 대해 논의합니다 | 이 문제를 논의합니다 |
| P11 | `~와 관련하여` (S2, 1) | 기후 변화와 관련하여 논의합니다 | 기후 변화를 다룹니다 |
| P12 | `~에 기반하여/바탕으로` (S2, 1) | 데이터에 기반하여 결정합니다 | 데이터로 결정합니다 |
| P13 | 이중 조사 (S1) | 주점 2층에서의 살림을 그만두고 | 주점 2층에서 시작한 살림을 그만두고 |

Allowances above 0 are deliberate: each of these is grammatical Korean, and the defect is
density. One `~를 통해` in a document reads fine; four in a paragraph is the trace.

## AI-tell 표면 습관

Not translationese — habits of generated prose specifically, and the fastest tells for a
reader.

| ID | Pattern | ✗ | ✓ |
|----|---------|---|---|
| P14 | 연결어미 뒤 쉼표 (S1) | 설정을 확인하고, 서버를 재시작한다 | 설정을 확인하고 서버를 재시작한다 |
| P15 | 문두 접속사 (S2, 2) | 또한 … 따라서 … 즉 … | (삭제 — 문장 순서가 흐름을 만든다) |
| P16 | 이중 완곡 (S1) | 개선될 수 있을 것으로 보입니다 | 개선됩니다 / 개선될 수 있습니다 |
| P17 | `~것이다` 남발 (S2, 2) | 매출이 증가할 것입니다 | 매출이 증가합니다 |
| P18 | 형식명사 강조 (S2, 1) | 빠르다는 점에서 효율적입니다 | 빨라서 효율적입니다 |
| P19 | `~을 위해` (S2, 2) | 효율을 위해 도구를 도입했습니다 | 효율을 높이려고 도구를 도입했습니다 |
| P20 | 지시관형사 (S2, 2) | 이러한 문제는 그러한 경우에 | 이 문제는 그때 |
| P21 | `~적 N` (S2, 1) | 전략적 함의, 실천적 기반 | 전략 함의, 실천의 기반 |
| P22 | hype 어휘 (S2, 1) | 혁신적인 성능 개선 | 응답 시간이 40% 줄었다 |

Two checks have no rule ID because they read the document as a whole:

- **동일 종결어미 4연속** — vary the ending. A run of `~습니다. ~습니다. ~습니다. ~습니다.` is
  the rhythm signature.
- **쉼표 비율 40% 초과** — generated Korean puts a comma in about 61% of sentences against a
  human 26%, most of them English-placed (between subject and predicate, or after a
  connective ending). Cut the commas, not the sentences.
