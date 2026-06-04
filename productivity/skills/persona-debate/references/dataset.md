# Dataset: nvidia/Nemotron-Personas-Korea

1,000,000 synthetic Korean adult personas. CC-BY-4.0 (attribution required;
fully synthetic, no real people, all 19+). Korean narrative text, English
column names. 9 parquet shards (~111k personas each) on HuggingFace, queried
over HTTP — never downloaded in full.

Attribution line to include when the panel is shown:
`personas: nvidia/Nemotron-Personas-Korea (CC-BY-4.0)`

## Fields

Narrative (Korean prose — feed these to debaters; rich idiosyncratic detail
is what keeps personas from collapsing into demographic stereotypes):
- `persona` — one-line summary identity
- `professional_persona` — work life
- `family_persona` — family/household life
- `cultural_background` — regional/cultural context
- `hobbies_and_interests`, `skills_and_expertise`, `career_goals_and_ambitions`
- (also exist: `sports_persona`, `arts_persona`, `travel_persona`, `culinary_persona`)

Structured demographics (use to *compose* a panel via WHERE filters and to
describe panel makeup — never to put words in a persona's mouth):
- `sex`, `age` (19–99 int), `marital_status`, `military_status`
- `occupation` (free-ish, ~hundreds of values), `education_level`, `bachelors_field`
- `district` (시·도-구/군, 252 values), `province` (17), `housing_type`, `family_type`, `country` (always 대한민국)

## Exact categorical literals

WHERE filters must use these exact strings. They are NOT guessable — note
`경상북`/`전라남` (not 경북/전남), `무학` for no schooling. To get values for
any other field, run `sample_personas.py distinct --field <name>`.

- `sex`: 남자, 여자
- `marital_status`: 미혼, 배우자있음, 사별, 이혼
- `military_status`: 현역, 비현역
- `education_level`: 무학, 초등학교, 중학교, 고등학교, 2~3년제 전문대학, 4년제 대학교, 대학원
- `bachelors_field`: 해당없음, 경영·행정·법, 공학·제조·건설, 교육, 농림어업·수의학, 보건·복지, 사회과학·언론, 서비스, 예술·인문, 자연과학·수학, 정보통신기술
- `province`: 서울, 부산, 대구, 인천, 광주, 대전, 울산, 세종, 경기, 강원, 충청북, 충청남, 전북, 전라남, 경상북, 경상남, 제주
- `housing_type`: 아파트, 단독주택, 다세대주택, 연립주택, 비주거용 건물 내 주택, 주택 이외의 거처

`district` uses `시·도-구/군`, e.g. `서울-은평구`, `부산-기장군`.

## Representativeness — be honest

One shard ≈ 111k personas, sampled in proportion to the dataset (which is
itself modeled on Korean census distributions). An **unfiltered** sample is
roughly population-representative. The moment you add a WHERE filter you are
building a *targeted* panel — it no longer represents the general public, and
narrowing to a single demographic raises caricature risk. Always say which
mode produced the panel in the final output.
