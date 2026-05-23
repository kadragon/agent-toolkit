# `.claudeignore` Template

Claude Code treats `.claudeignore` like `.gitignore` — listed paths are skipped when scanning or reading the repo. Without it, a single glob can pull in `node_modules/` (hundreds of MB of vendor code) and burn tokens on files the agent will never usefully read.

**Place at repo root.** Create once; rarely needs updating.

## How to pick patterns

1. Run `git ls-files --others --directory --no-empty-directory | head -50` and `ls -la` at repo root
2. Look for: build outputs, dependency caches, lock files, generated docs, coverage reports, binary assets
3. Match patterns to the language set detected in Step 1 (Analyze). Over-matching costs nothing; under-matching costs tokens.

## Language presets

Compose the final `.claudeignore` by concatenating relevant sections. Most repos need "Common" + one language section.

### Common (always include)

```
# Logs & temp
*.log
*.tmp
*.swp
.DS_Store
Thumbs.db

# Editor / OS
.vscode/
.fleet/
.idea/

# Maps & archives
*.map
*.zip
*.tar.gz
```

### Node / TypeScript / Next.js

```
node_modules/
.next/
.nuxt/
dist/
build/
out/
coverage/
.cache/
.parcel-cache/
.turbo/
*.lock
```

### Python

```
__pycache__/
.venv/
venv/
env/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/
.ruff_cache/
.tox/
htmlcov/
*.egg-info/
```

### Go

```
vendor/
bin/
```

### Rust

```
target/
```

### JVM (Java / Kotlin / Gradle / Maven)

```
.gradle/
build/
out/
target/
*.class
*.jar
```

### Generated docs

```
docs/_build/
site/
_site/
public/
```

## What NOT to ignore

- Source files (duh)
- Migration SQL, seed data
- Config files the agent might need context on (`tsconfig.json`, `pyproject.toml`, `Cargo.toml`)
- Fixture data under ~500 lines — the agent may need it to understand test setup

## Anti-pattern

```
# DON'T — too aggressive
*.json
*.yml
```

Ignoring all config files blocks the agent from reading `package.json` / `tsconfig.json` / CI workflows. Target generated artifacts, not source-of-truth config.
