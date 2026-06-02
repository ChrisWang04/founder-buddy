# Testing Guide

How to run the test suites for Founder Buddy.

- Backend: 88 pytest tests, ~2s, ≥85% branch coverage gate
- Frontend: 29 Vitest tests, ~700ms

---

## Quick start (both suites in one go)

```bash
cd /Users/chriswang/ai_project/founder-buddy && \
  (cd backend && source venv/bin/activate && pytest tests/) && \
  (cd frontend && npm test -- --run)
```

Expected: `88 passed` (backend, 96% coverage) and `29 passed` (frontend).

---

## Backend (pytest)

### First-time setup

```bash
cd backend
source venv/bin/activate
pip install -r requirements-dev.txt
```

### Daily commands

> **Note on the coverage gate**: the 85% branch-coverage gate is configured
> in `pyproject.toml` and applies to whatever pytest collects. If you run
> only a *subset* of tests, coverage will look low and the gate will fail —
> that's expected. Always pass `--no-cov` for subset runs, and only run the
> full suite (`pytest tests/`) when you want the gate to be meaningful.

```bash
# Full suite + coverage report + 85% gate (this is what CI runs)
pytest tests/

# Unit tests only (fastest, skip coverage)
pytest tests/unit/ --no-cov

# Integration tests only
pytest tests/integration/ --no-cov

# One specific file
pytest tests/unit/test_agent_helpers.py --no-cov

# One specific test by name (fuzzy match)
pytest -k "test_edit_flow" --no-cov

# Verbose + show print() output
pytest -v -s --no-cov

# Stop at first failure
pytest -x --no-cov

# Re-run only the tests that failed last time
pytest --lf --no-cov
```

**When to drop `--no-cov`**: only when running the full suite (`pytest tests/`).
Running everything is fast (~2s) so you can use it as your default — the
subset commands are just for tighter iteration when you're debugging one
file.

### Why `--no-cov`?

`pyproject.toml` configures pytest to **always** measure coverage and fail
the run if total branch coverage drops below 85%:

```toml
addopts = "--cov=. --cov-branch --cov-report=term-missing --cov-fail-under=85"
```

That gate checks coverage of the **entire codebase**, regardless of which
tests you actually ran. Concretely:

| Command | Tests collected | Code exercised | Reported coverage | Gate |
|---|---|---|---|---|
| `pytest tests/` | all 88 | agent.py + server.py | **96%** | ✅ pass |
| `pytest tests/unit/` | 64 | agent.py (most) + server.py helpers | **59%** | ❌ fail |
| `pytest tests/integration/` | 22 | agent.py + server.py | ~88% | ✅ pass-ish |

The unit-only run looks "broken" because the HTTP routes in `server.py`
(`/chat/start`, `/chat/stream`, etc.) are exercised by **integration**
tests, not unit tests. So when you only run unit tests, half of `server.py`
sits there uncovered and drags the percentage below 85%.

`--no-cov` tells pytest to **skip coverage collection entirely** for that
run, which means:
1. No coverage report is printed
2. The 85% gate is not checked
3. Tests run slightly faster (no instrumentation overhead)

The gate's only meaningful purpose is on a full-suite run — that's the
number that tells you "the project as a whole is well-tested." Subset runs
are for fast iteration while debugging, so it's correct to skip the gate
there.

**Rule of thumb**: running a subset → add `--no-cov`. Running everything →
drop it.

### Coverage details

```bash
# HTML coverage report (opens htmlcov/index.html)
pytest --cov-report=html

# Show which lines are missing in each file
pytest --cov-report=term-missing
```

---

## Frontend (Vitest)

### First-time setup

```bash
cd frontend
npm install
```

### Daily commands

```bash
# Run once and exit
npm test -- --run

# Watch mode — re-runs on file changes (use while developing)
npm test

# With coverage report
npm run test:coverage

# One specific file
npx vitest run __tests__/lib/sse.test.ts

# One specific test by name
npx vitest run -t "parses multiple events"

# Run only one folder
npx vitest run __tests__/lib/
```

---

## Mutation testing (optional, slow)

Mutation testing checks whether your tests actually *catch* bugs, not just
whether they execute the code. Takes 5–15 minutes for the current backend.

```bash
cd backend
source venv/bin/activate

mutmut run              # Run the full mutation pass
mutmut results          # Summary of killed vs. survived mutants
mutmut show <id>        # Diff for a specific surviving mutant
```

Full guide: [`backend/tests/MUTATION_TESTING.md`](backend/tests/MUTATION_TESTING.md)

---

## Condition coverage

Branch coverage tracks which branches ran. Condition coverage tracks whether
each Boolean sub-expression has been observed both True and False. The audit
lives at [`backend/tests/CONDITION_COVERAGE.md`](backend/tests/CONDITION_COVERAGE.md) —
a truth table per compound expression with the test that exercises each case.

---

## CI

`.github/workflows/test.yml` runs both suites on every push and PR to `main`.
The backend job fails the build if coverage drops below 85%.

---

## What's where

| File / dir | What it is |
|---|---|
| `backend/tests/unit/` | Pure-logic unit tests (helpers, routers, response builders) |
| `backend/tests/integration/` | Full HTTP roundtrips via FastAPI TestClient |
| `backend/tests/conftest.py` | Shared fixtures: `stub_llm`, `memory_graph`, `mock_supabase`, `test_app`, `fake_jwt` |
| `backend/pyproject.toml` | pytest + coverage + mutmut config (and the 85% gate) |
| `backend/tests/CONDITION_COVERAGE.md` | Compound-Boolean audit |
| `backend/tests/MUTATION_TESTING.md` | How to run mutmut |
| `frontend/__tests__/lib/` | Pure-function tests (SSE parser, label derivation) |
| `frontend/__tests__/components/` | React component tests with RTL |
| `frontend/vitest.config.ts` | Vitest + jsdom + path alias config |
| `frontend/vitest.setup.ts` | jest-dom matchers + `scrollTo` polyfill |
| `.github/workflows/test.yml` | CI workflow |

---

## Troubleshooting

**`pytest: command not found`** — you forgot to `source venv/bin/activate` first.

**`ModuleNotFoundError: No module named 'pytest'`** — same fix. The dev deps
live in the venv.

**`No test files found` (Vitest)** — you're probably in the wrong directory.
Vitest must run from `frontend/`.

**Tests fail because Supabase / Anthropic connection errors** — the fixtures
should prevent this. If you see real network calls, check that `conftest.py`
sets the env vars *before* importing backend modules.

**Coverage gate fails (`Required test coverage of 85% not reached`)** — most
common cause: you ran a subset of tests (e.g. `pytest tests/unit/`) which
doesn't exercise the HTTP routes in `server.py`. Add `--no-cov` for subset
runs, or run the full suite with `pytest tests/`. If the gate fails on the
full suite, you either removed tests or added uncovered code — run
`pytest tests/ --cov-report=term-missing` to see which lines aren't hit.
