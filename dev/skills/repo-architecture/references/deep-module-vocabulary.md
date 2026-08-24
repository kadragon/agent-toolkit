# Deep-Module Vocabulary

Condensed from [mattpocock/skills](https://github.com/mattpocock/skills)
`skills/engineering/codebase-design` (glossary, principles, rejected framings). Kept as a
reference rather than a skill: this repo needs the *language* for architecture proposals, not a
second design-discipline entry point.

Use these terms exactly. Do not substitute "component", "service", "API", or "boundary" —
consistent language is the whole point, and a proposal that drifts into generic nouns cannot be
compared against another one.

## Glossary

**Module** — anything with an interface and an implementation. Deliberately scale-agnostic: a
function, a class, a package, a tier-spanning slice. *Avoid*: unit, component, service.

**Interface** — everything a caller must know to use the module correctly. Not just the type
signature: invariants, ordering constraints, error modes, required configuration, performance
characteristics. *Avoid*: API, signature — both name only the type-level surface.

**Implementation** — what is inside the module. Distinct from **adapter**: a thing can be a small
adapter with a large implementation (a Postgres repository) or a large adapter with a small one
(an in-memory fake).

**Depth** — leverage at the interface: how much behavior a caller or a test can exercise per unit
of interface it has to learn. **Deep** = a lot of behavior behind a small interface. **Shallow** =
an interface nearly as complex as the implementation.

**Seam** *(Michael Feathers)* — a place where behavior can be altered without editing in that
place; the *location* at which a module's interface lives. Where the seam goes is a separate
decision from what sits behind it. *Avoid*: boundary — overloaded by DDD's bounded context.

**Adapter** — a concrete thing satisfying an interface at a seam. Names a *role* (which slot it
fills), not a substance (what is inside).

**Leverage** — what callers get from depth: more capability per unit of interface learned. One
implementation pays back across N call sites and M tests.

**Locality** — what maintainers get from depth: change, bugs, knowledge, and verification
concentrate in one place instead of spreading across callers. Fix once, fixed everywhere.

## Principles

- **Depth is a property of the interface, not the implementation.** A deep module may be built
  internally from small swappable parts; they are simply not part of its interface. A module can
  carry **internal seams** (private, used by its own tests) as well as the **external seam** at
  its interface.
- **The deletion test.** Imagine deleting the module. If complexity vanishes, it was a
  pass-through. If complexity reappears across N callers, it was earning its keep. A
  "concentrates" answer is the signal a deepening opportunity is real.
- **The interface is the test surface.** Callers and tests cross the same seam. Wanting to test
  *past* the interface means the module is the wrong shape.
- **One adapter is a hypothetical seam; two adapters is a real one.** Do not introduce a seam
  unless something actually varies across it.

## Designing for testability

- **Accept dependencies, do not construct them** — a function handed its gateway is testable; one
  that news up a client inside is not.
- **Return results, do not mutate in place** — a computed value is assertable; a side effect on a
  caller's object is not.
- **Small surface area** — fewer entry points means fewer tests; fewer parameters means simpler
  setup.

## Rejected framings

- **Depth as a ratio of implementation lines to interface lines** (Ousterhout) — rewards padding
  the implementation. Use depth-as-leverage instead.
- **"Interface" as a language `interface` keyword or a class's public methods** — too narrow;
  interface here includes every fact a caller must know.
- **"Boundary"** — overloaded with DDD's bounded context. Say *seam* or *interface*.
