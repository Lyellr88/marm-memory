# MARM Smoke Scripts

Manual smoke/stress harnesses for write queue, RPM presets, Swarm behavior, and compaction. These are not normal pytest tests.

Use `--spawn-server` for clean runs. It starts an isolated local MARM server with a temp DB, then deletes it after the run.

Compaction smoke paths use the public `marm_compaction(action=...)` endpoint/tool. The older raw compaction routes are internal/debug only and are hidden from MCP discovery.

## Pick A Script

| Goal | Script | Start Here |
|------|--------|------------|
| Test direct Python write queue only | `write-queue-smoke.py` | Direct Queue |
| Test HTTP writes, RPM flags, and queue integrity | `write-queue-http-smoke.py` | HTTP/RPM |
| Test full compaction stage/apply/idempotency paths | `compaction-worker-smoke.py` | Compaction Worker |
| Simulate small local swarms writing to MARM | `swarm-smoke.py` | Swarm |
| Test natural compaction trigger from swarm writes | `swarm-smoke.py` | Swarm + Compaction |

## Quick Choice

| Load | Use When | Command Group |
|------|----------|---------------|
| Base | Fast sanity check before deeper work | Base Runs |
| Medium | Normal local verification | Medium Runs |
| Heavy | Stress queue/RPM behavior | Heavy Runs |
| Special | Specific compaction or Ollama checks | Special Runs |

## Base Runs

### Direct Queue

No HTTP server. Fastest queue-only check.

```powershell
python scripts\test-scripts\write-queue-smoke.py --writes 10,25,50,100 --queue-size 100
```

### HTTP/RPM

Basic spawned-server HTTP write check.

```powershell
python scripts\test-scripts\write-queue-http-smoke.py --spawn-server --server-preset swarm --request-steps 100,150,200,300 --concurrency 20 --timeout-s 15 --warmup-writes 0
```

### Compaction Worker

Skips HTTP load and verifies stage/apply/idempotency/stale guards.

```powershell
python scripts\test-scripts\compaction-worker-smoke.py --spawn-server --server-preset trusted --skip-http-load --cluster-size 3 --candidate-count 1
```

### Swarm

No Ollama needed. Good first swarm/queue sanity check.

```powershell
python scripts\test-scripts\swarm-smoke.py --spawn-server --server-preset trusted --mock-model --agents 10 --rounds 20 --write-mode burst --write-concurrency 30
```

## Medium Runs

### HTTP/RPM Swarm-Max

The `800` step should hit rate limiting because `--swarm-max` is 600 RPM. If it does not, investigate the limiter.

```powershell
python scripts\test-scripts\write-queue-http-smoke.py --spawn-server --server-preset swarm-max --request-steps 200,400,600,800 --concurrency 20 --timeout-s 15 --warmup-writes 0
```

### Compaction Worker Full Path

Runs HTTP writes first, then compaction stage/apply, stale check, and cross-session isolation check.

```powershell
python scripts\test-scripts\compaction-worker-smoke.py --spawn-server --server-preset swarm --server-rate-limit-rpm 1000 --http-writes 100 --concurrency 20 --candidate-count 3
```

### Swarm + Natural Compaction

Uses one shared session so the per-session compaction counter triggers. `--seed-compaction-embeddings` keeps the test reliable when the spawned server cannot generate embeddings.

```powershell
python scripts\test-scripts\swarm-smoke.py --spawn-server --server-preset swarm --mock-model --session-mode shared --agents 5 --rounds 4 --write-mode burst --write-concurrency 20 --enable-compaction-check --seed-compaction-embeddings --compaction-wait-s 20
```

## Heavy Runs

### HTTP/RPM Queue Pressure

Mostly removes rate limiting so queue/write throughput is easier to see.

```powershell
python scripts\test-scripts\write-queue-http-smoke.py --spawn-server --server-preset swarm --server-rate-limit-rpm 1000 --request-steps 300,600,900,1200 --concurrency 30
```

### Trusted No-RPM Pressure

Trusted mode disables rate limiting. These should pass unless the queue, DB, or server starts failing under load.

```powershell
python scripts\test-scripts\write-queue-http-smoke.py --spawn-server --server-preset trusted --request-steps 200,400,800,1000 --concurrency 20 --timeout-s 15 --warmup-writes 0
```

### Compaction Worker Pressure

Heavier write/load profile with multiple compaction candidates.

```powershell
python scripts\test-scripts\compaction-worker-smoke.py --spawn-server --server-preset swarm-max --http-writes 200 --concurrency 30 --candidate-count 5 --timeout-s 20
```

### Swarm Queue Pressure

Mock model, burst writes, no Ollama bottleneck.

```powershell
python scripts\test-scripts\swarm-smoke.py --spawn-server --server-preset swarm --server-rate-limit-rpm 1000 --mock-model --agents 50 --rounds 20 --write-mode burst --write-concurrency 50
```

## Special Runs

### Ollama CPU-Safe Starter

Use when you want real local model generation. Keep `--model-concurrency 1` on CPU-only systems.

```powershell
python scripts\test-scripts\swarm-smoke.py --spawn-server --server-preset swarm --model llama3.2 --agents 3 --rounds 5 --model-concurrency 1 --write-concurrency 6
```

### Ollama Shared-Session Compaction

Real Ollama generation plus natural compaction trigger. Still seeds embeddings to avoid local encoder issues.

```powershell
python scripts\test-scripts\swarm-smoke.py --spawn-server --server-preset swarm --model llama3.2 --session-mode shared --agents 4 --rounds 5 --model-concurrency 1 --write-mode burst --write-concurrency 10 --enable-compaction-check --seed-compaction-embeddings --compaction-wait-s 30
```

### Auto-Apply Scheduler

Slower by design. Enables the V4 scheduler and waits for one interval so the scheduled job can apply a staged candidate through the write queue.

```powershell
python scripts\test-scripts\compaction-worker-smoke.py --spawn-server --server-preset trusted --skip-http-load --skip-stale-check --skip-cross-session-check --enable-auto-apply --auto-apply-interval-minutes 1 --auto-apply-wait-s 75
```

## Artifacts

| Script | Output Directory |
|--------|------------------|
| `write-queue-http-smoke.py` | `scripts/out/write-queue-http/` |
| `compaction-worker-smoke.py` | `scripts/out/compaction-worker/` |
| `swarm-smoke.py` | `scripts/out/swarm/` |

Use `--no-write-artifacts` when you only want console output.

## Reading Results

- `RESULT: PASS`: no hard errors. Expected `429` rate limits can still pass.
- `status_counts`: HTTP status distribution. `429` means rate limiting worked.
- `db_integrity=YES`: successful HTTP writes landed in SQLite.
- `errors > 0` or `hard_write_errors > 0`: real failures, not expected rate limiting.
- `successful_writes_per_min`: actual MARM write throughput.
- `write_latency_ms`: successful `200` write latency only in Swarm.
- `all_write_attempt_latency_ms`: all write attempts, including `429` and hard errors.
- `applied_verifications`: compaction source rows and summary row were committed.
- `final_staging_status=stale`: stale/cross-session negative path was rejected.
- `compaction_check.status=found`: Swarm writes triggered a staged compaction candidate visible through `marm_compaction(action="candidates")`.
- `model_failed`: local model/Ollama failures in Swarm.
