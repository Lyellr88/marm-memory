# Benchmarking

Local, reproducible benchmarks for marm-memory. Nothing here calls an LLM —
performance scripts measure real SQLite + fastembed calls on local hardware,
and the accuracy script scores recall with pure evidence-ID matching, not
model judging.

```
scripts/benchmarking/
  performance/
    bench_hotpath.py           # encode/recall/write/hybrid-search latency
    bench_concept_worker.py    # store/recall latency under background indexing
    dump_tool_schema.py        # dumps the real MCP tool schema an agent sees
  accuracy/
    locomo/
      run_eval.py          # LoCoMo retrieval accuracy harness
```

All scripts run from the **repo root**.

## Performance (`performance/`)

### `bench_hotpath.py`

Measures, against the real `MARMMemory` + configured fastembed-backed semantic encoder, using a throwaway temp DB (never touches `~/.marm`):

1. `encode()` wall time
2. `recall_similar` latency vs. session size N (FTS filter + bounded embedding rerank)
3. Event-loop blocking: concurrent recalls via `asyncio.gather` vs. serial
4. Write latency with consolidation OFF vs. ON
5. Hybrid search: FTS5 filter→rerank vs. weighted fusion vs. pure semantic

```
python scripts/benchmarking/performance/bench_hotpath.py
```

The numbers in the root [README's Performance & Scaling Benchmarks section](../../README.md#performance--scaling-benchmarks) come from this script. Don't publish a performance claim this script can't reproduce.

### `bench_concept_worker.py`

Measures what the test suite structurally cannot: `conftest` disables the real
encoder for isolation, so no test exercises store and recall latency while the
v2.36.0 background indexer is running.

Times both paths twice, once with the worker stopped and once while it drains a
queue holding the whole corpus, which is the state an upgrade with an existing
corpus passes through. A fresh install has nothing to catch up on.

```
python scripts/benchmarking/performance/bench_concept_worker.py
python scripts/benchmarking/performance/bench_concept_worker.py --from-live
```

`--from-live` copies `~/.marm/marm_memory.db` (and its WAL sidecars) into a temp
directory and measures against a real corpus. It never writes to the original.

The code-graph engine is disabled unless `--with-code-graph` is passed: each
extracted entity otherwise costs a ~300ms round trip to that subprocess, which
swamps the in-process contention this script is for.

Also sweeps the inter-batch pause, reporting recall p95 against total drain
time so the throttle can be set from data:

```
python scripts/benchmarking/performance/bench_concept_worker.py --from-live --sweep 0,250,500
```

Interpreting it: the relative deltas look alarming and the absolute numbers
usually do not. Judge both. Check the "N of M indexed" line as well, since a
worker that finished early means part of the timed phase measured an idle
process; raise `--seed` if so.

Corpus shape changes the answer, so prefer `--from-live` before quoting a
number anywhere. Short synthetic memories produce many small extractions and
show a write regression that a real corpus does not, because entity-name
embeddings are generated far faster than real content generates them.

## Accuracy (`accuracy/locomo/`)

### `run_eval.py`

Measures marm-memory's recall accuracy against the [LoCoMo](https://github.com/snap-research/locomo) long-conversation benchmark. No LLM is called anywhere in this script — pure evidence-ID matching against the server's own JSON responses.

Each LoCoMo conversation is ingested turn-by-turn through `marm_log_entry`, the same tool an agent uses. Since v2.21.0 every log entry is also embedded into semantic memory, so recall is scored across both lanes of a single `marm_smart_recall` response:

- **semantic lane** (`results`): the hybrid embedding + FTS5 engine, matched by memory id
- **log lane** (`log_results`): substring matching over log topics/summaries, matched by entry id
- **union**: what an agent actually sees in one response — the headline metric

Answer generation and LoCoMo's category-5 false-premise abstention are downstream LLM behaviors, not a memory server's job, so they're out of scope here. This measures one thing: did the right memory come back.

**Methodology notes:**

- Each LoCoMo conversation gets its own isolated `session_name` (`locomo_<sample_id>`), and recall runs with `search_all=False`, so nothing leaks between conversations.
- Turns are ingested as `YYYY-MM-DD-<speaker>-<text>` using each LoCoMo session's real date, via the server's documented entry format. Without this, every turn would be auto-tagged with today's date and category 2 (temporal) questions would have no temporal signal to find.
- Photo-share turns fold in their `blip_caption` so evidence living in an image turn is actually ingested.
- Questions without evidence annotations are skipped and the skip count is reported. Questions with more evidence turns than the top-K are counted under `all_hit_impossible` — all-hit cannot be satisfied for them at that K.
- If any response hits the 1MB MCP response limit, the run prints a warning: truncated responses undercount recall, they never inflate it.

**Usage:**

Run against a fresh database so prior memories can't interfere and re-runs stay reproducible, with `--trusted` so the default 80-requests/min rate limit doesn't throttle the ~3,500-request ingest (the harness survives 429s by waiting out the block window, but it's slow):

```
MARM_DB_PATH=/tmp/marm-locomo/marm_memory.db python -m marm_mcp_server --trusted
```

Then (default `http://127.0.0.1:8001`, no API key needed for a local, non-`0.0.0.0` bind):

```
python scripts/benchmarking/accuracy/locomo/run_eval.py --ingest --recall --limit 5
```

The dataset (`locomo10.json`) is downloaded automatically on first run into `accuracy/locomo/out/`, which holds every file the script reads or writes and is gitignored as a whole. `--samples N` limits to the first N of the 10 LoCoMo conversations for a quick smoke test.

Re-run scoring only, against already-ingested data:

```
python scripts/benchmarking/accuracy/locomo/run_eval.py --recall --limit 5
```

Already-ingested conversations are skipped on `--ingest` re-runs (their ids live in `out/ingest_state.json`); for a clean slate, use a fresh DB and delete `out/ingest_state.json`.

**Metrics:**

Reported per LoCoMo category (single-hop, temporal, multi-hop, open-domain, adversarial) and overall, in `out/results.json` (per-question detail) plus a summary table on stdout:

- `any_hit_rate`: fraction of questions where at least one gold evidence turn was recalled (either lane).
- `all_hit_rate`: fraction where every gold evidence turn was recalled (matters for multi-hop questions with multiple evidence IDs).
- `evidence_recall`: mean fraction of gold evidence turns recalled per question — smoother than the all-or-nothing pair.
- `semantic_any_hit_rate` / `log_any_hit_rate`: per-lane breakdown of any-hit, showing how much each retrieval lane contributes.

**Latest full run (`jinaai/jina-embeddings-v2-small-en`, top-5):** 1,977 scored questions, 53.0% any-hit, 43.4% all-hit, and 47.6% mean evidence recall. The previous MiniLM baseline was 37.5% any-hit and 29.5% all-hit. This is a measured end-to-end comparison, not proof that context length alone caused the change.
