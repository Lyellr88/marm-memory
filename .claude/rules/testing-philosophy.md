# Testing Philosophy Rules

**Every test exercises real functionality and real edge cases**  
**No synthetic tests, existence checks, or tests coded to pass**

Tests are a diagnostic tool. False positives hide real regressions.

## Mocks

**Mocks are not first instinct**  
**Only mock if BOTH conditions hold:**

- Meaningfully speeds up the test
- Achieves ≥95% fidelity to the real thing (behavior, output shape, edge cases)

If a mock can't hit 95%, hit the actual FastAPI endpoint or SQLite DB directly. Do not weaken a test for convenience.

## Test Depth

**Shallow coverage (50 tests checking type/existence)**  
**Deep tests that exercise real code paths**

10 comprehensive tests beat 50 shallow ones. Tier 1 (field exists) only acceptable as precursor to Tier 2 (value correct / logic exercised).

## Data-Driven Tests

**Read actual DB state, call real endpoints, assert match**  
**Hardcoded assertions on live data**

Exercises real code paths without faking inputs.

## Skip Guards

**`pytest.mark.skip` only when a dependency is genuinely unavailable** (e.g. no embedding model loaded, no DB connection)  
**Never permanent skips because writing the test requires effort**

Dependency absence = acceptable. Laziness = not acceptable.

Tests are a safety net. Skipping them is like driving without a seatbelt.
