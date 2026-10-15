# Smells, grep seeds, and keep rules

Reference for `test-prune` Step 2. A smell makes a test a **candidate**; only the Step 3 kill-set
measurement decides its fate. Sources: obra/superpowers `writing-good-tests.md`, the tsDetect /
xUnit Test Patterns smell names, Kent Beck's Test Desiderata, computerphilosopher
`false-green-detector` — all paraphrased.

## Catalog

Each smell is phrased as the question that exposes it.

| Smell | Exposing question | Typical fate |
|---|---|---|
| **No assertion** | Can it fail other than by crashing? | DELETE + GAP |
| **Always-true assertion** | Would `toBeDefined`, `is not None`, `assertTrue(true)`, `len(x) >= 0` fail on any realistic bug? | DELETE + GAP |
| **Mirror / tautology** | Is the expected value computed by the code under test, its helpers, or a copy of its logic inside the test? Does setup share the object it asserts on? | DELETE + GAP |
| **Mocked subject** | Is the thing under test itself replaced by a double? Would the assertion pass with the real code deleted? | DELETE + GAP |
| **Mock-only assertion** | Does it assert only that a mock was called, when the spec names an outcome? | DELETE or MERGE into an outcome test |
| **Change detector** | Can only an intentional decision fail it — a constant, exact wording, private structure, a call count the spec never names? | DELETE |
| **Text grep** | Does it assert that a source, config or doc file contains a line? It proves only that the file is the file. | DELETE |
| **Framework test** | Does it exercise library or language mechanics rather than this code's own boundary? | DELETE |
| **Trivial code** | Does it test a getter, constructor, constant or plain forwarding that does not validate, default, derive, normalize, enforce, or cause a side effect? | DELETE |
| **Duplicate** | Does another test check the same behavior with an input of the same class? | MERGE or DELETE |
| **Parametrized explosion** | Do generated cases outnumber distinct input classes, e.g. every key × every locale for one lookup rule? | MERGE to one case per class |
| **Unreachable edge case** | Is the input ruled out upstream (type system, parser, validation, caller contract)? See *Unreachable inputs*. | DELETE once the guard is cited |
| **Conditional assertion** | Is an `expect`/`assert` inside an `if`, loop or `catch` that may not execute? | DELETE + GAP, or KEEP if it kills |
| **Missing await** | Is an async assertion not awaited, so the test ends before it runs? | DELETE + GAP, or KEEP if it kills |
| **Skipped / focused** | `.skip`, `xit`, `@pytest.mark.skip` with no linked reason; `.only` left in. | DELETE (skip) / report (`only`) |

Conditional assertions and missing awaits are often **false greens**, not redundancy — they may
be the only test of a behavior they never actually check. The kill set decides: a test that kills
nothing is DELETE + GAP; one that kills something stays.

## Grep seeds

Starting points only — read every hit. Adjust to the repo's runner and language.

```sh
# JS/TS (vitest, jest)
grep -rnE "toBeDefined\(\)|toBeTruthy\(\)|not\.toBeNull\(\)|expect\(true\)" <tests>
grep -rnE "\.(skip|only)\(|\bx(it|describe)\(" <tests>
grep -rnE "vi\.mock|jest\.mock" <tests>           # then check what is mocked
grep -rnE "(it|test)\.each" <tests>
grep -rnE "readFileSync\(.*\.(ts|js|md|json)" <tests>   # text-grep tests
# Python (pytest)
grep -rnE "assert .* is not None$|assert True$" <tests>
grep -rnE "@pytest\.mark\.(skip|xfail)|@mock\.patch|MagicMock" <tests>
grep -rnE "parametrize" <tests>
# Any language: tests with no assertion keyword at all
```

For "no assertion", list test functions and keep those whose body contains none of the runner's
assertion keywords; grep alone cannot do it across multi-line bodies.

## Unreachable inputs

"Too edge-case" is a judgment until the guard is named. Delete an edge-case test only when you can
cite, by file and line, what makes the input impossible at this unit's callers:

- a type that excludes it (non-nullable, enum, branded type) **and** no untyped entry point;
- a parser or validator every caller passes through first;
- a documented caller contract the callers are tested against.

If the guard exists, its own tests own that input. If no guard exists, the input is reachable and
the test is a KEEP candidate — measure it like any other. Inputs from outside the process (user
input, files, network, env) are reachable by default.

## Keep rules

A candidate matching any rule below leaves the list in Step 2, with the rule named in the report.

1. **Sole killer** — it is the only test that kills some mutant (decided in Step 4).
2. **Regression test** — its name, comment, or history links it to a fixed bug or incident.
3. **Spec-required interaction** — the spec names the exact interaction (a payment sent exactly
   once, an audit log written) and the test asserts that, not more.
4. **Public contract** — it pins an API, schema, CLI output or file format other code or users
   depend on.
5. **Characterization** — one narrow test documenting a surprising upstream assumption, named as
   such.
6. **Security boundary** — authorization, escaping, or input validation, even when the input looks
   unlikely.

Keep-rule matches skip measurement. When one is measured anyway and kills nothing — a
"regression test" no mutant of the fixed code fails — it is a false green: keep it, and log the
behavior under *Gaps* so someone strengthens it.
