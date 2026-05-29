# Queue Smoke Tests

These scripts are manual smoke/stress harnesses for MARM write behavior. They are not normal pytest tests.

## Scripts

| Script | What It Tests | Server Needed |
|--------|---------------|---------------|
| `write-queue-smoke.py` | Direct Python write queue + SQLite write integrity | No |
| `write-queue-http-smoke.py` | HTTP writes, rate limits, spawned-server presets, and queue behavior together | Optional; use `--spawn-server` for clean isolated runs |

Artifacts are written to `scripts/out/write-queue-http/` unless `--no-write-artifacts` is used.

## Direct Queue Smoke

Use this to test the write queue itself without HTTP rate limiting.

```powershell
python scripts\tests\write-queue-smoke.py --writes 10,25,50,100 --queue-size 100
```

Notes:

- Uses an isolated temp DB by default.
- Adds an overflow burst by default at `2x --queue-size`.
- Use `--no-overflow` when you only want the listed write steps.
- Use `--db-path path\to\marm_memory.db --cleanup` only if you intentionally want to test an existing DB.

## HTTP / RPM Smoke

Use this to test real HTTP behavior, spawned server presets, rate limiting, and DB write integrity.

With `--spawn-server`, each request step starts a fresh isolated server and temp DB. That prevents one step from burning rate-limit tokens for the next step.

The spawned server uses the production default write queue behavior, so the queue is enabled unless `--queue-disabled` is supplied for direct-write comparison.

### Custom High-RPM Queue Pressure

This mostly removes rate limiting so queue/write behavior is easier to see.

```powershell
python scripts\tests\write-queue-http-smoke.py --spawn-server --server-preset swarm --server-rate-limit-rpm 1000 --request-steps 300,600,900,1200 --concurrency 30
```

### Swarm-Max Preset

The 800 step should hit rate limiting because `--swarm-max` is 600 RPM. If 800 succeeds cleanly, investigate the limiter.

```powershell
python scripts\tests\write-queue-http-smoke.py --spawn-server --server-preset swarm-max --request-steps 200,400,600,800 --concurrency 20 --timeout-s 15 --warmup-writes 0
```

### Swarm Preset

The 300 step should hit rate limiting because `--swarm` is 200 RPM. If 300 succeeds cleanly, investigate the limiter.

```powershell
python scripts\tests\write-queue-http-smoke.py --spawn-server --server-preset swarm --request-steps 100,150,200,300 --concurrency 20 --timeout-s 15 --warmup-writes 0
```

### Trusted Preset

Trusted mode disables rate limiting. These should pass unless the queue, DB, or server starts failing under load.

```powershell
python scripts\tests\write-queue-http-smoke.py --spawn-server --server-preset trusted --request-steps 200,400,800,1000 --concurrency 20 --timeout-s 15 --warmup-writes 0
```

## Reading Results

- `status_counts`: expected HTTP distribution. `429` means rate limiting worked.
- `db_integrity=YES`: successful HTTP writes landed in SQLite.
- `errors > 0`: real failure, not expected rate limiting.
- `RESULT: PASS`: no hard errors. A step can still include expected `429` responses and pass.
