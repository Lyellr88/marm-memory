# marm-graph Test Hygiene Notes

## Shared codebase-memory-mcp Store

Current integration tests use the real `codebase-memory-mcp` binary. That is intentional: the wrapper depends on upstream process behavior, stdio framing, and real tool schemas, so pure mocks are not enough.

One known hygiene issue remains: the upstream binary uses a shared project store/cache. Dogfood runs and test runs can see each other's indexed projects. When more than one project is present, tests that rely on single-project auto-resolution can fail with `ambiguous_project` even though the product behavior is correct.

This is not a v0.1 product blocker. It only affects repeatable local/CI tests.

Future fix before wider CI:

1. Confirm which upstream env/config controls the project store/cache path.
2. Point integration tests at a per-session temp store in `tests/conftest.py`.
3. Keep tests using the real binary, but isolate state from developer dogfood runs.
4. Add cleanup after the session fixture closes.

Until then, if integration tests fail unexpectedly with `ambiguous_project`, inspect the upstream project list and remove stale dogfood projects from the shared store.
