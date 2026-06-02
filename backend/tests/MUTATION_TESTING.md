# Mutation Testing

Branch coverage tells you which lines/branches were executed. **Mutation
testing** tells you whether your tests would actually *catch* a bug in those
lines. It mutates the source (flips operators, removes statements, replaces
constants) and re-runs the test suite. If tests still pass on a mutated
version, your tests can't distinguish correct from broken behavior — that
surviving mutant marks a gap.

## Run

```bash
cd backend
source venv/bin/activate
pip install -r requirements-dev.txt   # installs mutmut

# Run the full mutation pass (slow — ~5–15 minutes for ~300 stmts of source)
mutmut run

# View the results
mutmut results

# Inspect a specific surviving mutant
mutmut show <id>

# Re-run only one file
mutmut run --paths-to-mutate agent.py
```

## Config

Set in `backend/pyproject.toml` under `[tool.mutmut]`:

```toml
paths_to_mutate = ["agent.py", "server.py"]
tests_dir = "tests/"
runner = "pytest -x --no-cov -q"
```

- `paths_to_mutate` excludes `db.py` (already excluded from the coverage gate;
  mutating thin Supabase wrappers is low signal).
- `runner` disables coverage (faster) and stops at first failure (faster).

## Interpreting results

mutmut classifies each mutant as:

| Status | Meaning |
|---|---|
| **killed** | A test failed → mutation was detected. Good. |
| **survived** | All tests passed → tests can't distinguish this mutation. **Gap.** |
| **timeout** | Tests hung (mutation caused infinite loop) → counts as killed. |
| **suspicious** | Tests passed but took unusually long. Worth inspecting. |
| **skipped** | mutmut couldn't mutate (e.g., empty function body). |

**Mutation score** = killed / (killed + survived). Aim for **≥ 70%** as a
baseline; higher is better but diminishing returns past ~85%.

## Investigating a surviving mutant

```bash
mutmut show 42
```

Shows the diff. Three possible follow-ups:

1. **The mutant changes observable behavior we care about** → add a test that
   would fail on the mutated version, re-run mutmut.
2. **The mutant is equivalent** (semantically identical to the original, e.g.
   `x + 0` → `x`) → no fix needed; record it as a known equivalent mutant.
3. **The mutated behavior is unreachable** (dead code) → consider removing
   the original code rather than testing the mutation.

## Baseline

Run the suite once and record the baseline mutation score here so future
contributors can detect regressions:

```
<run `mutmut run` and `mutmut results`, then paste the summary>
```

This was not run as part of the initial setup — pass a baseline once the
suite stabilizes. Re-running quarterly is a reasonable cadence.

## Why not in CI?

A full `mutmut run` takes several minutes and grows with codebase size.
Running it on every push is too slow. Treat it as an audit tool: run
locally before major refactors, or once a release cycle, to identify
weakly-tested code.
