# Changelog

<details>
<summary><strong>August 10th, 2026: Type-Safe Core and Unified Validation (v2.38.0)</strong></summary>

### Changed: MARM's Entire Server Package Is Now Type-Checked

- Mypy previously checked only `core/`, which left endpoint, transport, Console, service, and utility code free to accumulate errors unnoticed. It now checks all 110 server modules against a recorded error count, so a new type error raises that count and fails the local gate instead of becoming another item in a hidden backlog.
- The work tightened the contracts at the real boundaries: SQLite connections, memory ownership, serialized writes, recall return shapes, embeddings, compaction, graph gates, FastAPI middleware, CLI paths, and injected test doubles. These are internal contracts only; MCP tools, parameters, HTTP/STDIO behavior, and stored data are unchanged.
- The encoder adapter now states its two actual shapes: encoding one string returns one NumPy vector, while encoding a list returns one vector per input. Migration and rechunking use a structural encoder contract, so their test doubles remain supported without pretending every encoder is FastEmbed.
- The pass also exposed two latent type mismatches in real code, including a recall SQL parameter list that mixed text and a numeric limit. Both are corrected without changing the intended query or result behavior.

### Changed: One Formatter and Linter Own the Python Style Contract

- Ruff now owns formatting and linting. Black, isort, and Flake8 were removed from development and CI because their formatting and line-length rules conflicted with the project’s Ruff configuration. CI installs and checks the same tools developers run locally.
- The bundled `marm-init` installer skill was refreshed alongside its source copy, so installed agents receive the current setup flow and both copies remain identical.
- Ruff is pinned in CI. An unpinned install let a new Ruff release fail a pull request whose code had not changed: 0.16.2 promoted a rule out of preview and flagged four annotations that the previous version reported clean. Keep local Ruff on the pinned version so a local pass predicts CI.

### Fixed: A Doc Save No Longer Fails Or Duplicates Its Memory Mirror

- Saving a doc commits the docs row first, then links it to a memories mirror in a second write. If that link failed, the save reported an error even though the doc was already stored durably, and the mirror row was left behind pointing at nothing.
- The link failure is now reported as `mirror_status: "pending"` on an otherwise successful save, matching how a failed mirror write already behaved. The response's `memory_id` names the mirror row whenever one was written, including in that pending state; previously both pending causes reported the doc's stored link, which is null or points at a deleted row precisely when an unlinked mirror exists. It is null only when the mirror write itself failed and there is no row to name.
- A later save repairs the link rather than creating a second mirror. The mirror write resolves a doc's existing mirror by its `doc_id`, so a doc keeps exactly one mirror row however many times the link has to be retried. That resolve now runs whenever the linked id fails to match a row, not only when the caller has no id at all: on an install carrying duplicates from before this fix, deleting the linked mirror left the link dangling and the next save added a third row on top of the surviving duplicate.
- Installs that already accumulated duplicate mirrors keep them. Removing them means deleting memory rows, their chunks, and their concept provenance, which is a migration rather than a fix and is not done silently. Saves do now converge on a single one of them: the mirror is resolved by row id rather than by timestamp, because the save rewrites the timestamp it was ordering on and so kept picking whichever duplicate it had not just written, alternating between them indefinitely while a doc's link kept failing.

### Developer Note

- The typecheck gate ends at two deliberately visible graph-shutdown race findings. They are documented in `docs/current/graph-client-none-guard.md` rather than suppressed: resolving them requires a supervisor lifecycle change, not an annotation workaround.

</details>

<details>
<summary><strong>August 4th, 2026: Automatic Code Graph Indexing (v2.37.0)</strong></summary>

### Added: Indexed Repositories Refresh Themselves

- A code graph was only ever as fresh as the last time someone called `marm_graph_index`. This repo's own index was four days and a full release behind when the work started, and nothing surfaced that. A stale graph does not fail loudly, it answers confidently from deleted code. Indexed repositories are now re-indexed in the background on both transports, on by default, with nothing to click.
- Changes are detected with a git signature computed outside the engine, so an idle check costs no engine lock. A commit moves `HEAD` and triggers a re-index. While the working tree is dirty the repo is re-indexed every cycle instead, because `git status` reports which files changed and not what is in them: the second and every later edit to one file produce byte-identical output, so any cheaper fingerprint stops noticing after the first save. Indexing is incremental, so an unchanged dirty repo costs a few hundred milliseconds.
- Non-git directories have no cheap signature at all, so they get an unconditional re-index on a slower lane (`GRAPH_AUTO_INDEX_FULL_INTERVAL`, 300s) rather than the fast one.
- Every index call in MARM, automatic or manual, now passes through one leased row in the memory database. HTTP and STDIO are separate processes with separate engine children over one shared engine store, and the previous in-process lock could not see across that boundary. A manual index that arrives during an automatic one reports `index_in_progress` instead of running alongside it.
- Turn it off with `marm-mcp-server projects auto off`, or from an agent with `marm_graph_index(action="auto_off")`. `knowledge auto off` does the same for concept extraction. Both take effect on the next cycle with no restart, both survive one, and both work with the graph engine stopped. A saved switch beats the environment variable, so a `GRAPH_AUTO_INDEX=true` in a Dockerfile cannot silently re-enable something you turned off; `auto status` names which one won.
- Deleting a project records a durable suppression, so a poller holding a cached project list cannot recreate what you just deleted. An explicit manual index re-enrolls it.
- Pacing is `GRAPH_AUTO_INDEX_INTERVAL` (30s), `GRAPH_AUTO_INDEX_MODE` (`moderate`), `GRAPH_AUTO_INDEX_LEASE_SECONDS` (120), and `GRAPH_AUTO_INDEX_PROJECT_TTL` (300s). 30 seconds rather than the engine's own 5: a git signature measures ~52ms per project on Windows, which is close to pure process spawn, and a code graph does not need sub-minute freshness.
- Nothing is downloaded on your behalf. Auto-indexing is on by default, but the poller stays dormant until the graph engine binary is already on disk, so a fresh install does not pull ~269MB at first boot for a user who never calls a graph tool.

### Upgrade Note

No action required. Two tables are added to the memory database on first start. If you would rather index only on request, run:

```
marm-mcp-server projects auto off
```

</details>

<details>
<summary><strong>August 2nd, 2026: Automatic Concept Graph Indexing (v2.36.0)</strong></summary>

### Added: Memories Become Graph Nodes on Their Own

- The concept graph only grew when someone clicked Build Concept Graph, so it was stale until a human remembered to refresh it. Storing a memory now queues it for indexing, and a background worker turns it into a node about 30 seconds later on both transports. Nothing to click.
- The queue is a durable table in the memory database, written in the same transaction as the memory itself, so a memory cannot exist without its indexing task. A server killed mid-extraction loses nothing: the task is still there on the next start and shutdown never waits for extraction to finish.
- Extraction failures retry with a growing delay and record the reason. A memory that fails three times is parked with its error rather than blocking the queue behind it. A failure never affects the memory itself, which stores and recalls normally throughout.
- Turn it off with `CONCEPT_AUTO_INDEX=false` (or `0`, `no`, `off`). That stops the worker, not the queue: writes keep recording indexing tasks, so re-enabling it indexes everything written while it was off. Pacing is `CONCEPT_INDEX_DEBOUNCE_SECONDS` (30), `CONCEPT_INDEX_BATCH_SIZE` (20, capped at 500), `CONCEPT_INDEX_BATCH_PAUSE_MS` (250), `CONCEPT_INDEX_LEASE_SECONDS` (300), and `CONCEPT_INDEX_MAX_ATTEMPTS` (3).
- Clearing a backlog is not free, and the numbers are published rather than estimated. On a real 768-memory corpus, recall during a drain moves from ~8ms to ~16ms median (p95 ~12ms to ~31ms) while writes are unaffected; `scripts/benchmarking/performance/bench_concept_worker.py` reproduces it. Entity extraction is CPU-bound, so this is contention for cores, not lock waiting, and tuning the encoder would not help. The pause between batches exists for the tail: it cuts worst-case recall during indexing from roughly 270ms to 80ms in exchange for about 18% longer drains. Steady-state indexing of a few new memories is idle almost all the time and none of this applies.
- Running HTTP and STDIO at once is safe. Both take a leased lock in the memory database before touching the graph, so a rebuild in one cannot drop tables while the other is writing to them. A build that finds the graph busy reports `build_in_progress` and can be run again rather than colliding.
- The Console's Knowledge Explorer picks new nodes up while it is open. It polls a small change marker rather than the graph, so an idle Explorer costs a few counts per check, and it stops entirely when the tab is not showing.

### Fixed: Builds Silently Ignored Everything Past the Newest 500 Memories

- Every build ended with a hard limit of 500 rows. On a corpus larger than that, the older memories were not slow to reach, they were unreachable: no scope, no setting, and no number of rebuilds would ever index them.
- Builds now page through the whole scope. `CONCEPT_BUILD_ROW_CAP` still exists and still defaults to 500, but it is a page size now, not a ceiling. Anyone who lowered it to bound build cost gets more, smaller pages instead of a truncated graph, and a full build on a large corpus is genuinely long-running as a result.

### Changed: Compacted Sessions Index Their Sources, Not Their Summary

- When a session compacts, its original memories are kept as sources and a summary is written alongside them. Builds used to skip the sources and index the summary, which is backwards for a graph: the summary restates concepts the sources already stated, so every entity in a compacted session was attributed to a paraphrase rather than to where it was actually said.
- Sources are now indexed and generated summaries are not. This is also what lets a memory reach the graph the moment it is written instead of waiting for its session to compact.

### Upgrade Note

This release requires one graph rebuild. Existing graphs contain entities extracted from compaction summaries that the new rule would never produce, and there is no way to remove only those. MARM detects the old graph and reports `rebuild_required` until you run:

```
marm_concept_build(search_all=True)
```

The old graph is backed up next to the database first. The build clears the queue it just covered, so the background worker does not immediately re-extract the same corpus.

</details>

<details>
<summary><strong>July 31st, 2026: Chunk Durability and Repair (v2.35.0)</strong></summary>

### Fixed: Long Memories Could Silently Lose Their Chunks on Shutdown

- Memories longer than 500 words are additionally stored as smaller passages, so recall can match the relevant part of a long memory instead of judging it as one block. Those passages are written in the background, after the memory itself is saved, because encoding them takes about a second.
- Nothing tracked that background work. If the server exited between saving the memory and writing its passages, the passages were lost, permanently and with no error shown. The memory itself was never at risk and still recalls; it just gets scored as one block, less accurately.
- Shutdown now waits up to 5 seconds for pending passage writes on both transports, configurable with `CHUNK_DRAIN_TIMEOUT_SECONDS`. An expired wait gives up rather than blocking exit, and the repair command below recovers anything left unwritten. One limit worth stating plainly: an encode already running in a worker thread is still joined when the interpreter shuts down, so an encoder wedged mid-encode can delay exit independently of this timeout. That behavior is unchanged from before and is another reason the repair command exists.
- This was not hypothetical. On the developer's own install, two of the eight eligible memories had no passages at all.

### Added: `marm-mcp-server --rechunk` Repairs Passage Storage

- The passage size settings changed over time, and the existing `--migrate-embeddings` command re-encodes stored passages where they are without re-splitting them, so passages written under older settings kept their old boundaries through every upgrade. On the developer's install, every single one was wrong: memories carrying 11 to 16 passages should have had 5 to 7.
- Oversplitting is not cosmetic. A memory's score is the best score among its passages, so more passages means more independent chances at a high score. Measured on unrelated queries, average best-match similarity climbs from 0.028 at one passage to 0.120 at sixteen, meaning an oversplit memory carries an unearned advantage over a correctly split one.
- Run `marm-mcp-server --rechunk` (or `marm-memory maintenance chunks rechunk`) with all MARM processes stopped. It re-splits stale passages, fills in any that were lost, and removes passages from memories that are now under the threshold. Memories already correct are skipped without loading the encoder, so a second run does nothing and costs nothing.
- The command refuses to run if stored vectors do not match the configured embedding model, and names `--migrate-embeddings` as the fix. Proceeding in that state would write passages at a different vector size than their parent memories, which the scorer silently ignores, producing passages that exist in the database but cannot be matched.
- Verified on a real 769-memory database: 71 passage rows became 39 across 8 repaired memories, and the second run reported zero changes.

### Fixed: `--migrate-embeddings` Ran Out of Memory on Databases With Long Content

- The migration encoded 100 memories at a time. The encoder pads every text in a group to the length of the longest one, so a group containing one long memory costs as much as if all 100 were that long. On the developer's own database this asked the runtime for a 35 GB block and the migration crashed outright.
- Any install with long memories would have hit this, and the only workaround was an option the command does not expose. That put it directly in the way of the repair command above, which tells users to migrate first.
- Group size is now chosen from the content itself, capping each group by the number of texts times the longest one, which is what the encoder actually allocates. Databases of short memories still encode in large groups, so nothing gets slower. Verified on the database that crashed: the identical command now completes, 840 vectors in 45 seconds.

### Upgrade Note

Existing installs should run `marm-mcp-server --rechunk` once, with MARM stopped, to correct passages written under older settings. Recall works without it; results for long memories are just less accurate. If the command reports an embedding model mismatch, run `marm-mcp-server --migrate-embeddings` first: that sequence was verified end to end on a real 769-memory database.

</details>

<details>
<summary><strong>July 31st, 2026: Code Index Engine Updated (v2.34.0)</strong></summary>

### Changed: Bundled Code Index Engine Updated to 0.9.0

- MARM's code graph wraps a separate program, `codebase-memory-mcp`, which does the actual repository indexing. It moves from 0.8.1 to 0.9.0. The upgrade brings first-class Windows support, faster indexing, a supervisor that restarts the indexer if it crashes, and automatic pruning of projects whose folder is no longer on disk.
- MARM verifies the version it pins against the version the program reports about itself at startup. The 0.8.1 program misreported itself as `0.10.0`, so the version shown in logs and in `cbm_binary_version` was wrong for the version actually running. 0.9.0 reports correctly and the two now agree.

### Fixed: The Code Graph Would Not Have Started Against the New Engine

- 0.9.0 changed how it reports the operations it supports. Instead of returning all 14 in one response, it returns them in pages of 8 with a marker pointing at the next page. MARM asked once, saw 8, and concluded the remaining 6 had been removed upstream.
- A missing operation means one of MARM's internal mappings is silently broken, so MARM deliberately refuses to start the code graph rather than run a half-wired feature. The practical effect of upgrading without this fix would have been the code graph failing to come up at all, on every start.
- MARM now follows the pages to the end. Nothing about the 14 operations actually changed: none were added or removed, and no required argument changed, so no other adjustment was needed. Four regression tests cover the paged response, the unpaged one, and two ways a page marker can be misread, so a future change to page size cannot quietly shrink the verified list again.
- This was caught and fixed before the upgrade shipped, so no released version was affected. Memory, recall, logging, and the notebook do not use this component and were never involved. The code graph is on by default (`GRAPH_ENABLED=true`) and degrades to memory-only if it cannot start, so an install that hit this would have kept working minus code-graph features.

### Evaluated: Rank-Based Fusion (RRF), Not Adopted

- MARM ranks hybrid recall by blending scores: it keeps how strong each match was and mixes meaning-similarity with keyword relevance and a recency boost. An outside contribution ([#112](https://github.com/Lyellr88/marm-memory/pull/112)) proposed replacing that with Reciprocal Rank Fusion, which discards the scores and combines the two lists by rank position instead. The argument for it is sound in principle: a keyword score is normalized per query, so one outlier can stretch the scale and distort the blend, and rank positions are immune to that.
- It could not be measured as submitted, because it also removed `HYBRID_SEARCH_TEXT_WEIGHT` and gave both retrievers equal say. That is a 10x change in how much keyword matching counts (0.05 to 0.5) arriving in the same change as the fusion swap, so any difference in accuracy could not be attributed to either one. A weighted variant of RRF was derived that preserves the shipped keyword weight and produces the same `[0, 1]` output range, so both arms received identical candidates and identical weighting and the only variable was score magnitude versus rank position.
- RRF lost. On LoCoMo (1,977 questions, 5,882 memories, top-5), any-hit fell from 63.5% to 56.2%, and the same 6.8 to 7.3 point gap appeared on all-hit and evidence recall. It was worse in all five question categories, and worst where precision matters most: adversarial dropped 13.0 points and open-domain 8.0. It found 48 questions min-max missed and lost 192 that min-max found. Latency was measured separately and was the same either way, so there was no speed gain to trade against the accuracy loss.
- Two control runs of the identical existing configuration differed by 0.56 points, which sets the noise floor for this corpus. The gap is roughly 12 times that, and it held against both control runs and in both directions of a two-way cross-fold. Min-max is kept and the experiment branch was discarded unmerged. The scope is one corpus at one keyword weight, so this says RRF did not win here, not that rank-based fusion is worse in general.
- The exercise corrected something about MARM's own measurement, which is the part that outlives it. Run-to-run noise on this benchmark had been assumed to sit near 0.1 points; it is 0.56. A controlled diagnostic traced the difference to recency scores shifting as the wall clock advances between runs, which reshuffles near-ties. Benchmark differences smaller than about half a point should not be read as real.

</details>

<details>
<summary><strong>July 30th, 2026: Recall and Consolidation Correctness Fixes (v2.33.1)</strong></summary>

### Fixed: Semantic Duplicate Detection Compared the Wrong Score

- Consolidation has two layers. Layer 1 merges content that is byte-for-byte identical after normalization, using a content hash. Layer 2 merges near-duplicates that are worded differently but mean the same thing. Only Layer 2 changed here; exact deduplication is untouched and still catches identical content, including syntax-heavy content.
- `CONSOLIDATION_THRESHOLD` (default `0.92`) is documented as the meaning-similarity a memory needs before Layer 2 merges it into an existing one. The check was comparing it against the final ranking score instead, which also folds in keyword relevance and a recency boost. A memory could therefore be merged away when its actual meaning-similarity was below the threshold, because keyword overlap and freshness had pushed its ranking score above it.
- Layer 2 now compares the raw meaning-similarity, as documented. It also asks for the meaning-based search lane explicitly: syntax-heavy content such as config keys, file paths and commands is normally routed to exact keyword lookup, which produces no meaning-similarity at all, so semantic merging could not have worked for it either way. And it looks at a handful of candidates rather than only the top-ranked one, because the closest memory by meaning is not always the one that ranks first. When no meaning-similarity is available, semantic merging is skipped and the write proceeds; Layer 1 still applies.
- This only affects installs that have turned consolidation on; it is off by default (`CONSOLIDATION_ENABLED=0`), so no existing default behavior changes. Fixes #113.

### Fixed: Recency Scoring Was Not Reproducible Within a Single Recall

- The recency boost read the clock separately for every candidate in a recall, so memories saved at the same moment received slightly different recency scores. Whenever two memories were otherwise equally relevant, which one ranked higher came down to which was processed first rather than anything about the memories.
- All candidates in a recall are now scored against a single reference time, so identical timestamps produce identical recency scores. Applies to meaning-based search and to the keyword-only fallback; exact keyword lookup does not use recency scoring and is unchanged.
- Note this addresses ordering *within* one recall. Recency scores still move as time passes between separate recalls, which is what the feature is for.

</details>

<details>
<summary><strong>July 29th, 2026: Recall Keeps Working When the Embedding Model Does Not (v2.33.0)</strong></summary>

### Fixed: Recall Returned Nothing When the Embedding Model Was Unavailable

- MARM falls back to keyword-only search when the embedding model cannot load or errors during a recall. That fallback was building its keyword query with strict AND, so it only matched a memory containing *every* word of the question, including words like "what" and "the". Natural-language questions matched nothing, and the last-resort search then looked for the entire question as one literal substring, which also matched nothing.
- The practical effect: if the model failed to load, recall returned an empty result for effectively every question asked. Measured on LoCoMo (1,977 questions, 5,882 memories, top-5, model disabled): 0.1% of questions returned any correct memory. Two questions out of 1,977.
- The fallback now uses the same broader keyword matching the main search lane has used since v2.31.0. Same benchmark: **any-hit 0.1% to 55.4%, all-hit 0.1% to 46.7%, evidence recall 0.1% to 50.5%**. Every question category improved, and adversarial questions went from 0.0% to 51.8%. For reference, recall with the model loaded scores 62.5% on this corpus, so the degraded path now reaches about 89% of full accuracy instead of being unusable.
- The exact-lookup lane is deliberately unchanged and still requires all terms. Its results are returned in raw keyword-score order with nothing reranking them, so broadening it would cost precision on the config-key and file-path lookups it exists for. `FTS_QUERY_MODE=and` still forces strict matching everywhere for anyone who wants it.

### Fixed: FTS_LONE_HIT_SCORE Did Not Apply to the Fallback Lane

- `FTS_LONE_HIT_SCORE` sets the keyword score reported when only one memory matches, or when every match ties. The keyword-only fallback lane shares its row fetcher with the exact-lookup lane, so it always reported `1.0` there and ignored the setting. Now that the fallback lane matches on a broad keyword query, a single match can mean one memory happened to share one word, which is exactly the case the setting exists to let you score lower.
- The fallback lane now honors it; the exact-lookup lane still always uses `1.0`, because its strict all-terms match means a single hit contained every word of the query. No change at the default of `1.0`.

### New Settings

- `SEMANTIC_SEARCH_ENABLED` (default `1`). Set it to `0` to run exactly as though the embedding model were not installed: no model load, no embeddings written, recall served by keyword matching. It was added because the degraded path above could not be measured any other way, and it also lets a low-memory host skip loading the model. `marm-memory doctor` reports "Meaning-based search: off (keyword matching only)" when it is disabled.

</details>

<details>
<summary><strong>July 28th, 2026: Keyword Ranking Weight Set From Benchmark Data (v2.32.0)</strong></summary>

### Keyword Relevance Now Contributes to Ranking

- v2.31.0 made the keyword index find candidates for natural-language questions but deliberately left keyword scores out of ranking, because the old 35% weight had been chosen while that path never ran and so had never been validated. The weight has now been swept against the benchmark and is on.
- `HYBRID_SEARCH_TEXT_WEIGHT` defaults to `0.05`. Swept over `0.00, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.15, 0.20, 0.35, 0.50` on LoCoMo (1,977 questions, 5,882 ingested memories, top-5 recall), any-hit peaks across a broad `0.04`-`0.08` plateau at 62.0-62.5%, against 57.4% with keyword scoring off and 57.6% at the old 0.35. `0.05` is the middle of that plateau rather than the single best run, so the default is not fitted to one corpus. Large weights are actively harmful: single-hop accuracy falls from 56.9% at `0.05` to 47.3% at `0.35`.
- `FTS_CANDIDATE_LIMIT` default raised from `50` to `200`. This was the lever on the multi-hop regression v2.31.0 introduced, and raising it recovers multi-hop any-hit from 34.8% to 39.3%, matching the pre-v2.31.0 baseline, while lifting single-hop 1.1 points and leaving adversarial precision unchanged. Recall costs roughly 3ms more per query. `500` recovers a further 1.1 points of multi-hop but starts giving back the adversarial gain, because a pool that large no longer narrows anything.
- Combined result versus v2.31.0 measured on the same corpus: any-hit 57.4% to 62.5%, all-hit 47.6% to 52.6%, evidence recall 51.9% to 56.9%. Every question category improves, and multi-hop, the one category v2.31.0 set back, is fully recovered.

### Fixed: Keyword Candidate Selection Was Not Reproducible

- When several memories tied on keyword score at the candidate cutoff, which ones entered the pool depended on the order SQLite happened to return rows, and that order varied between server processes. Ties at the cutoff are the normal case, not an edge case: 53.7% of benchmark queries had one. Two identical benchmark runs disagreed on 18 questions and scored 0.5 points apart, and the same recall could return different results across restarts.
- Candidate selection now breaks ties on memory ID, so the pool is stable for a given database. Accuracy is unchanged within measurement error; what changes is that results are now reproducible. This also means benchmark differences smaller than roughly 0.1 points are now meaningful, where previously anything under 0.5 points was indistinguishable from noise.

### New Settings

- `FTS_LONE_HIT_SCORE` (default `1.0`) sets the keyword score used when a candidate set is too degenerate to rank, meaning a single match or every match tied. It defaults to no change in behavior: swept over `0.0/0.3/0.5/1.0` with no measurable effect. The offline diagnostic found one degenerate set across 1,982 FTS calls, a count distinct from the benchmark's 1,977 scored-question result set. It is exposed for small stores, where a query matching exactly one memory is common and treating that as a perfect keyword match may not be wanted.
- `marm-memory doctor` reports the new value in its existing "Recall tuning" section.

</details>

<details>
<summary><strong>July 26th, 2026: Natural-Language Keyword Retrieval Activated (v2.31.0)</strong></summary>

### Natural-Language Recall Now Uses the Keyword Index

- Semantic recall now finds keyword candidates for natural-language questions. Previously every word in a query had to appear in the same memory before the keyword index would return anything, so questions like "What pet does the speaker have?" matched nothing and recall fell back to scanning embeddings alone. Queries now drop filler words and match on any remaining term, so the keyword index contributes on ordinary questions instead of only on exact lookups.
- Measured on the LoCoMo benchmark (1,977 questions, 5,882 ingested memories, top-5 recall): any-hit 53.0% to 57.8%, all-hit 43.4% to 47.8%, evidence recall 47.6% to 52.1%. Keyword candidate coverage went from 0% of questions to 99.9%. The gain is largest on adversarial questions (39.7% to 49.8% any-hit) and open-domain (57.2% to 61.1%).
- Multi-hop questions regressed (39.3% to 33.7% any-hit, 89 questions). Those answers need evidence spread across several memories, and a keyword-filtered candidate pool can drop a memory that shares no words with the question. `FTS_CANDIDATE_LIMIT` (default 50) is the lever, and it is now a live tuning knob: 99.4% of benchmark queries filled the pool to that cap.
- The exact/lexical lane is unchanged. Config keys, CLI flags, file paths, and other syntax-heavy lookups still require every term to match and are still returned in keyword-rank order without semantic reranking, so their precision is unaffected.

### Fixed: Protocol Was Not Delivered on pip Installs

- `marm_start`, the protocol-injection middleware, and the STDIO tool lifecycle all read `PROTOCOL.md` and `PROTOCOL-LITE.md` from a path outside the installed package. That path is not included in the wheel, so on every pip install the protocol read returned "PROTOCOL.md file not found" and the lite protocol returned empty. Docker images and development checkouts were unaffected, which is why it went unnoticed. Agents installing from PyPI received no MARM protocol at all.
- Root cause was two copies of the documentation with nothing enforcing which one shipped. The copy at `marm-mcp-server/marm-docs/` has been removed; `marm_mcp_server/resources/marm-docs/` is now the single location, and it is inside the package so one path resolves correctly for pip, Docker, and source checkouts alike. The protocol readers and the document indexer now share one resolver rather than each computing their own path.
- Added tests that read both protocol files through the packaged path, assert the indexer and the protocol readers agree on that location, and fail if a second copy is reintroduced outside the package.

### New Settings

- `FTS_QUERY_MODE` (`or_nostop` default, `or`, `and`) selects how the semantic lane builds its keyword query. `and` restores the pre-2.31.0 behavior.
- `FTS_EXTRA_STOPWORDS` appends comma-separated words to the built-in ignore list, for domain terms so common in a store that they carry no signal.
- `HYBRID_SEARCH_TEXT_WEIGHT` now defaults to `0.0` instead of `0.35`. Keyword matching narrows which memories are considered but does not influence their ranking. The previous 0.35 default was chosen while the keyword lane never ran on natural-language queries, so it was never validated against real candidates; it will be set from benchmark data in a following release. Setting the variable explicitly still applies the given weight.
- `marm-memory doctor` now prints a "Recall tuning" section showing the effective values.

</details>

<details>
<summary><strong>July 26th, 2026: One-Command Skill Install, fast-start-http Guided Setup, and CLI/Console Module Splits (v2.30.0)</strong></summary>

### `marm-memory init`

- Added `marm-memory init`, a standalone command that installs the MARM skill into agent skill folders with no server, database, or network access required. By default it scans the current project for supported agents (Claude, Codex, Gemini, Qwen, Kiro) and installs to each one found, overwriting any existing copy so re-running refreshes the skill after an upgrade. If no agent directory is present, it falls back to creating a `.agents/skills/marm-init/` folder in the project.
- Per-agent global flags (`--g-claude`, `--g-codex`, `--g-gemini`, `--g-qwen`, `--g-kiro`) install into the matching home-folder directory instead. Global and project are separate modes; a run does one or the other, never both.
- The skill is now bundled inside the package (`marm_mcp_server/resources/skills/marm-init/`) and read at install time, so installs work offline and always match the running version. A test asserts the bundled copy stays byte-identical to the source skill.

### marm-init Skill Refresh

- The guided setup skill now leads with `marm-memory fast-start-http` as the one-shot local path (starts the HTTP server, launches Console, and opens the browser with loopback-only auth), and uses the managed `marm-memory docker run` / `docker stdio-command` commands for the Docker paths in place of raw `docker run` blocks. The seven-step guided flow and the rule that key values never enter the setup conversation are preserved.

### Internal

- Split `cli.py`'s remaining output-formatting and argparse-construction concerns into `services/cli_output.py` and `services/cli_parser.py`, continuing the v2.28.0 CLI service-module split. No behavior change; `_dispatch_product`, `main`, and runtime-preset application stay in `cli.py` as the orchestration owner. `cli.py` drops from 786 to 509 lines.
- Split MARM Console's `concept_store.py` graph-atlas and single-entity-neighborhood queries into their own modules: `console/concept_graph_overview.py` (`graph_overview`, the full-vs-sampled visual atlas with its degree-ranked BFS tree-sampling) and `console/concept_neighborhood.py` (`neighborhood`, the bounded single-entity BFS traversal). No behavior change; shared low-level helpers (`_connect`, `_schema_status`, `_entity`) and the smaller query functions (`summary`, `search`, `get_entity`, `build_runs`, `get_build_run`, `duplicates`) stay in `concept_store.py`. `concept_store.py` drops from 676 to 334 lines.

</details>

<details>
<summary><strong>July 24th, 2026: Hybrid Recall Fusion, Windows Key Fix, and Command Smoke Suite (v2.29.0)</strong></summary>

### Hybrid Recall Now Fuses Lexical Relevance

- Semantic recall now blends the FTS5 BM25 keyword score into ranking instead of using it only as a candidate pre-filter and then discarding it. On the hybrid path, relevance combines semantic similarity (65%) with the normalized BM25 score (35%) before temporal weighting, so exact-term matches such as identifiers, config keys, and error strings surface more reliably. This changes recall ordering; it is backward compatible and needs no migration.
- The chunk-aware scorer was vectorized into a single matrix operation. Results are identical to the previous per-chunk loop, with less per-query work on large scans.
- Temporal decay is now applied consistently on the text-search fallback lane, so newer results are preferred when the semantic model is unavailable. The deterministic exact/lexical lane still returns matches in BM25 order, unaffected by age.

### Windows Managed-Key Reliability

- The managed API-key file (`~/.marm/.env`) is now locked to the executing Windows identity via the native Windows security API (process-token SID), setting both the owner and a protected owner-only DACL rather than shelling out to external tools or trusting an environment-derived username. This fixes a case where a key created under one resolved identity could not be read back by the same process, and prevents a prior owner from reopening the permissions. Both `key init` and automatic HTTP key creation use the same tested helper.

### Local Command Smoke Suite

- Added `scripts/test-scripts/smoke-commands.py` and a pytest module that exercise the entire `marm-memory` command surface: every help route, safe read-only dispatches, an isolated HTTP start/health/stop lifecycle, and a managed-key round trip. A real Docker lifecycle (`--docker`) and an uninstall/reinstall inside a disposable virtual environment (`--destructive`) are explicit opt-ins that never touch the active install. A static inventory check fails if a newly added command has no smoke coverage.

### Benchmark Integrity

- The recall-scaling benchmark now times only shipped code paths (`recall_similar` and `_fetch_and_score_embedding_rows`); the previous benchmark-local reimplementations were removed so published numbers reflect what a caller actually runs. Both compared paths use the same async dispatch and exclude the constant query-encode cost. The README performance tables were refreshed from a single run.

</details>

<details>
<summary><strong>July 24th, 2026: Restored PyPI And Registry Publishing (v2.28.2)</strong></summary>

- Restored the PyPI trusted-publisher workflow after account recovery and re-enabled MCP Registry publishing, which depends on the published PyPI version.
- Added a release-time installed-wheel smoke test that verifies the bundled MARM Console entry point and static frontend before upload.
- Updated the README status notices to confirm that MARM Console is ready and PyPI publishing is current again.

</details>

<details>
<summary><strong>July 23rd, 2026: Focused Docker Commands and Full Command Surface (v2.28.0)</strong></summary>

### Focused Docker Convenience Commands

- Added `marm-memory docker` for pip-installed users: `status`, `pull`, `run`, `command` (paste-ready preview), `compose`, `stdio-command`, `logs`, `stop`, and `maintenance embeddings migrate`. Generated containers default to loopback binding, a persistent `~/.marm` mount via explicit `--mount`, managed env-file auth (the key never enters shell history), and `--restart unless-stopped`; network exposure requires `--expose-network`.
- `docker run` refuses to replace an existing container and prints the exact inspect/stop choices instead; `docker pull` only downloads. Embedding migration refuses while the managed HTTP container is running and returns Docker's real exit code. `docker upgrade` is reported as a manual step rather than silently recreating a container. Compose previews by default and only writes on `--yes`, never overwriting an existing file. The raw Docker and Compose instructions remain for Docker-only users.

### Complete Command and Usability Pass

- Added transport aliases `http` (foreground HTTP) and `stdio` (in-process MCP STDIO), plus `fast-start-http`, which starts or reuses the runtime, launches Console, and prints a single status report. The existing `start`, `marm-mcp-server`, and `marm-mcp-stdio` entry points are unchanged.
- Expanded key management: `key init` creates or reuses the managed `~/.marm/.env` without ever rotating an existing key, `key path` prints only the path, and `key reveal` prints the key on stdout with its capture warning on stderr. `key generate` is unchanged.
- Added `upgrade`/`update` and `uninstall`. Both preserve all user data under `~/.marm`, detect editable, pipx, and Windows-launcher installs, and print the exact manual command when self-replacement is not safe. `upgrade --check` reports installed versus latest without installing.
- Replaced the default argparse root help with a grouped, terminal-width-aware layout (Daily Use, Setup and Updates, Knowledge and Projects, Docker, Maintenance), added root `-V`/`--version` and a `help <command>` alias, and gave every command a visible one-line description.

### Authenticated Console Handoff

- Added `marm-memory console --import-key`, which hands the managed runtime key to a local Console browser session without exposing it in the frontend, URL, browser storage, or logs. A short-lived, single-use bootstrap token is exchanged for an HttpOnly, SameSite=strict session cookie, and the runtime key stays server-side. Normal Console launch stays keyless, and manual key entry remains available for remote or separately managed runtimes.

### Internal

- `cli.py` was split into focused service modules (Docker, key, package, workflow, help, logs, and project commands) as the command surface grew, with no behavior change to existing commands.

</details>

<details>
<summary><strong>July 22nd, 2026: Bundled Concept Extraction (v2.27.0)</strong></summary>

### Concept Extraction Is Bundled, No Separate Setup

- The spaCy runtime and the English `en_core_web_sm` pipeline now ship inside the wheel. Concept extraction works after a normal `pip install marm-mcp-server` with no separate model download and no `knowledge setup` step; that command and the two-step `[concepts]` extra plus `spacy download` flow are removed. The `[concepts]` extra is kept empty so existing install commands stay valid.
- The model loads lazily on the first concept build. If the runtime cannot initialize, core memory and both concept tools keep working and return empty results rather than erroring. `doctor` and `--check-deps` now treat the model as a required dependency; repair a damaged install with `python -m pip install -U --force-reinstall marm-mcp-server`.
- The 15 MB model is not committed to source. It is fetched, SHA-256 verified, and unpacked into package data at build time (CI, both Docker images, and source setup) by `scripts/bundle-concept-model.py`, which downloads with a bounded timeout and retries so a stalled release download cannot hang a build.

### Code Graph Reliability

- Errors from the code-graph binary no longer lose their remediation hint when a large local project list overflows the binary's error-payload size cap. The client now recovers the error and hint fields from a truncated payload, so tool errors stay actionable regardless of how many projects are indexed. Test indexing is isolated from the developer's real project store.

</details>

<details>
<summary><strong>July 21st, 2026: Managed Runtime CLI and Bundled Console (v2.26.0)</strong></summary>

### Managed Runtime CLI and Bundled Console

- The existing `marm-mcp-server` package now installs a canonical `marm-memory` command while preserving the `marm-mcp-server` and `marm-mcp-stdio` compatibility entry points. `start`, `stop`, `restart`, `status`, `logs`, and `doctor` manage one verified local HTTP runtime without requiring users to track process IDs or ports manually.
- Added named `standard`, `swarm`, `swarm-max`, and `trusted` profiles, plus passive status and maintenance inspection that do not load the embedding model, start the code graph, or create an absent concept database.
- MARM Console is now bundled into the main wheel and launched with `marm-memory console`; users no longer need a separate Python server checkout or Node installation. Console reuses the managed runtime and shuts down with it when both were launched through MARM.
- Added discoverable CLI workflows for optional concept setup/builds, code-project indexing and removal, embedding migration, key generation, and runtime diagnostics. `marm-memory knowledge setup` installs through MARM's active Python interpreter only after confirmation and reports when a restart is required.
- Hardened the managed CLI after independent review: project-job polling now retries transport failures without reporting false success, runtime request errors preserve HTTP status/detail, lifecycle routes cannot be blocked by the shared loopback rate-limit bucket, and product-command failures exit cleanly without Python tracebacks.
- Human `status`, `doctor`, and maintenance output now summarizes the runtime instead of printing raw machine JSON; `--json` remains stable for automation. Managed runtime and Console logs are capped at 5 MB and tailed incrementally, restart leaves an active Console available, and start no longer advertises a Console URL before the Console is launched.
- Docker and Glama release jobs now build the same Console frontend as the wheel job, preventing package formats from shipping different UI bundles from one release tag.

</details>

<details>
<summary><strong>July 20th, 2026: Notebook Scratch Pad, Permanent Docs Store, and Chunking Rework (v2.25.0)</strong></summary>

### Notebook Is Now a Real Per-Session Scratch Pad

- `notebook_entries` gains `session_name` as part of its identity (was `name`+`project`+`platform` only). Legacy rows migrate to `session_name='main'` on upgrade so nothing already saved becomes unreachable. `add`, `use`, `show`, and `marm_delete(type="notebook")` all now scope by session — a scratch note saved under one session is no longer visible from a different one.
- Scratch entries stop writing embeddings entirely; they're retrieved by exact name, not semantic search. `--migrate-embeddings` and the embedding-compatibility inspector both stop touching `notebook_entries.embedding`.

### New: `marm_notebook(action="save")` and the Permanent Docs Store

- `marm_notebook` gains a `save` action that promotes a scratch entry — or new inline content passed directly — into a new, separate SQLite database (`marm_docs.db`, `~/.marm/docs/` by default, override with `MARM_DOCS_DB_PATH`). `save` is a copy, not a move: the original scratch entry is left untouched, and saving again under the same name updates the existing doc rather than duplicating it.
- Saved docs reach `marm_smart_recall` and `marm_concept_build` by being mirrored into `memories` under their own original session/project/platform, through a new queue-backed, non-consolidating mirror path (`memory.store_doc_mirror`) that keeps one stable row per doc across resaves. The mirror is best-effort: a sync failure never loses the durable doc save, it just reports `mirror_status="pending"` so a later save can repair it. The mirror always excludes the `marm_system` session so it can never disappear into `marm_concept_build`'s reserved-session exclusion filter.
- No new tool, no new endpoint — same `marm_notebook` operation, one more action.

### Memory and Doc Chunking Reworked for the Larger Embedding Window

- Replaced the fixed-window chunker (150-word chunks, tuned for the old 256-token model) with an even-split algorithm sized for the current `jina-embeddings-v2-small-en` model's 8,192-token window: a memory profile (500-word threshold / 250-word target / 50-word overlap) and a larger doc profile (1,000 / 800 / 100). The old algorithm could leave a tiny, low-value trailing fragment (e.g. a 280-word memory splitting into 250+30 words); the new one distributes remainder words evenly across the leading chunks instead.
- Applies to new writes only — `--migrate-embeddings` is unchanged (it re-embeds existing text, it never re-derives chunk boundaries), so pre-upgrade memories keep their old chunk sizing until naturally rewritten. Old and new chunk sizes coexist safely in recall since each chunk is scored independently.

### Console

- Notebook list/create/update/delete now carry `session_name` end to end (server and UI), so same-named scratch entries from different sessions are no longer conflated in the Console.

### Fixes From Independent Review

- `marm_delete(type="notebook")` without `project`/`platform` now refuses (rather than silently deleting all of them) when more than one entry shares a name within a session across different project/platform scopes — the new four-part identity made that collision newly possible. A single unscoped match still deletes cleanly as before.
- `memory_chunks` gains a `(memory_id, chunk_index)` unique index, and chunk writes use `INSERT OR REPLACE`: two resaves of identical content share the same `content_hash`, so the existing staleness guard couldn't tell them apart, and back-to-back saves of an unchanged doc could each insert a full duplicate set of chunk rows.
- `server.json`'s published tool metadata and version strings were out of sync with the actual `2.25.0` release (still advertised the old 5-action notebook description); READMEs and the CHANGELOG's own embedding-migration notes still claimed `notebook` embeddings were re-embedded after that path was retired above. All corrected.
- Fixed a Windows-only test bug (`test_docs_db.py` used the POSIX-only `HOME` env var to redirect `Path.home()`, which Windows ignores) and a Console test fixture that predated the `session_name` schema change (a hand-rolled `notebook_entries` table missing the column, plus stale `marm_notebook`/`marm_delete` call assertions).
- The new `memory_chunks` unique index above would fail to create on any database that already had duplicate `(memory_id, chunk_index)` rows from the pre-fix race — an upgrade could no longer start the server at all. `init_database()` now collapses existing duplicates (keeping the most recent row) before creating the index, guarded to run only once.
- `_store_doc_mirror` (the `marm_notebook(action="save")` mirror path) overwrote an existing memory row in place on resave without marking any active `compaction_staging` rows referencing it as stale, unlike `_replace_memory`'s established handling of the same in-place-overwrite case — a staged summary could later be applied against a doc whose content had since changed. Now mirrors `_replace_memory`'s stale-marking update.
- The two packaged READMEs (`marm-mcp-server/README.md`, `marm-mcp-server/marm-docs/README.md`) were hand-edited alongside the root README's version bump instead of being regenerated via `scripts/make-readme-mirrors.py`, violating the project's generated-mirror convention. Regenerated from the (already-correct) root README — no content changed.

### Concept Context Joins Normal Recall

- `marm_smart_recall` now preserves its existing memory ranking while attaching bounded concept relationships and linked code symbols as an additive `graph_context` sidecar. Missing, empty, incompatible, or unavailable graph data fails open and never blocks core recall.
- Concept entities and relationships now retain platform provenance alongside session and project scope. Existing concept graphs require one explicit `marm_concept_build(search_all=True)` rebuild; MARM backs up and resets only the derived concept database and never modifies primary memories.
- `marm_concept_recall` accepts optional platform scope over both HTTP and STDIO while retaining its explicit bounded traversal role.
- MARM Console's graph explorer now uses a full-atlas mode through 750 entities and 6,000 stored relationships. Oversized graphs use a deterministic connected sample capped at 600 entities and 4,000 aggregated visual edges, with honest full/sampled metadata in the API and UI.
- Replaced permanently pinned graph coordinates with adaptive force simulation, weighted repeated relationships, focused labels, and reheating when filters or graph membership change.

</details>

<details>
<summary><strong>July 19th, 2026: Jina v2 Small Embedding Migration (v2.24.0)</strong></summary>

### Default Embedding Model Changed

- Switched the default semantic encoder from `all-MiniLM-L6-v2` (384 dimensions, 256-token context) to fastembed-backed `jinaai/jina-embeddings-v2-small-en` (512 dimensions, 8,192-token context). Jina v2 Small has 33M parameters, is Apache-2.0 licensed, and does not require separate query/document text prefixes.
- **Upgrade required for existing data:** stop every MARM HTTP and STDIO process, then run `marm-mcp-server --migrate-embeddings` before restarting MARM. The command refuses when it detects a live HTTP server, but cannot reliably detect STDIO processes, so those must be stopped manually.
- The migration re-embeds memory, chunk, and any existing concept-graph embeddings (notebook scratch entries no longer carry embeddings as of v2.25.0, below). It reports batch progress, verifies both database files before recording completion, and can be rerun safely after interruption.
- Existing installations still start before migration, but mixed-dimension embeddings degrade semantic recall; startup and affected recall lanes now log actionable dimension-mismatch warnings.
- Re-ran both benchmark suites with Jina v2 Small. The hot-path benchmark now publishes the measured latency/write profile; a fresh 10-conversation LoCoMo run reached 53.0% any-hit and 43.4% all-hit at top-5 across 1,977 questions, compared with the prior MiniLM baseline of 37.5% and 29.5%. This is an end-to-end result, not a claim that context length alone caused the change.

</details>

<details>
<summary><strong>July 18th, 2026: Focused Console and Memory Module Refactors (v2.23.1)</strong></summary>

### Clearer Module Boundaries

- Split MARM Console's large Memory and Knowledge workspace components into focused tab, graph, and dialog modules without changing the Console API or user-facing behavior.
- Split the Console FastAPI application into endpoint, model, and core modules while preserving the standalone Console entry point and route contract.
- Split MARM's memory operations into focused internal modules while retaining the existing core-memory compatibility surface, serialized write queue, and public MCP behavior.
- Added regression coverage around the extracted Console and memory-operation boundaries. No schema, endpoint, or MCP tool-surface changes.

</details>

<details>
<summary><strong>July 16th, 2026: SQLite Write Atomicity Hardening (v2.23.0)</strong></summary>

### Multi-Statement Writes Are Now Real Transactions

- MARM's pooled SQLite connections run in full autocommit mode (`isolation_level=None`), so a multi-statement write sequence followed by `conn.commit()` was never actually atomic — each statement committed immediately on its own, and a failure partway through left the earlier statements permanently applied with nothing to roll back. Hardened every meaningful multi-statement mutation path with the project's existing `BEGIN IMMEDIATE` / explicit `COMMIT` / `ROLLBACK`-on-exception pattern (already used by `_store_memory` and `apply_compaction_write`): log-entry creation, session-switch, and whole-session delete (`services/log_entry.py`); session activation (`endpoints/session.py`); notebook add (`services/notebook.py`); the legacy system-notebook cleanup pass (`services/documentation.py`).
- Fixed a real, independently-discovered bug while auditing `_update_memory` (the consolidation merge path): it used to hold `BEGIN IMMEDIATE`'s write lock open across an `await` for embedding generation, which could stall the whole event loop for any other writer waiting on the same database. Restructured to compute the merge and its embedding before acquiring the lock, then re-verify under the lock (matching content *and* metadata, not just content) that nothing changed concurrently before writing — and folded the memory-chunks cleanup into the same transaction as the content update, so the two can no longer disagree after a partial failure.
- Fixed a second bug found in independent review: `_update_memory` can legitimately no-op (return without writing) when its target row was deleted or changed concurrently between the duplicate check and the write-lock re-verification, but `_store_memory` still reported the stale `existing_id` as a successful merge — silently dropping the caller's content with no trace. `_update_memory` now returns a bool signaling whether it actually wrote; `_store_memory` falls through and stores the content as a new memory instead of reporting success on a merge that never happened.
- Every new transaction boundary has a mutation-tested regression test (`tests/test_sqlite_write_atomicity.py`): each one forces a specific SQL statement to fail and asserts the earlier statement(s) in the same block did not durably apply — a happy-path-only test doesn't prove rollback. Coverage now also includes the session-switch, dated-fallback, targeted log-delete, and notebook-delete transaction boundaries.
- No schema changes, no new endpoints, no tool-surface changes. Pure reliability hardening.

### MARM Console Memory Tab Reaches Dashboard Parity

- Filled the remaining Memory workspace gaps from the legacy `marm-dashboard`: Console can now create sessions, delete one session, delete all sessions, delete individual log rows, bulk-delete logs, add/delete notebook entries, and stage/apply/discard compaction candidates from the same Memory tab surface.
- The new Console routes call existing MARM MCP tool paths for mutations instead of writing directly to SQLite, preserving the queue-backed memory write rules and transport behavior.
- Added visible success/error feedback for session, log, notebook, and compaction actions so failed queue/MCP operations no longer disappear silently in the UI.
- Notebook add/delete now preserves optional `project`/`platform` scope across Console and the existing MCP tool paths, so same-name notebook entries in different scopes are not collapsed by UI mutations.
- Added FastAPI response-contract tests for the new Console Memory routes with the MCP adapter stubbed, matching the rule that every new Console API route gets at least one real response-layer test.

### Legacy Dashboard Removed From MCP Server Runtime

- Removed the bundled `marm_dashboard` package from the shipped `marm-mcp-server` package and Docker image. The old source is archived locally under `docs/archived/` for reference while marm-console becomes the human-facing local app.
- Unmounted `/dashboard` from the FastAPI app and removed the parent-server auth exemption that existed only for that mounted sub-app. `/dashboard` is now an ordinary missing route.
- Removed dashboard-specific tests and replaced the HTTP app coverage with assertions that the route is no longer mounted or public. Maintenance scripts now scan only shipped packages and marm-console.

</details>

<details>
<summary><strong>July 15th, 2026: MARM Console Safe Memory Mutations (v2.22.0)</strong></summary>

### Console Can Now Create, Edit, and Delete Memories

- New internal-only HTTP routes on the MARM runtime — `POST /internal/memories`, `PUT /internal/memories/{id}`, `DELETE /internal/memories/{id}`, `POST /internal/memories/bulk-delete` — let Console mutate memory records through MARM's existing serialized write queue instead of a second SQLite writer. These are UI-only: absent from `MCP_TOOL_OPERATIONS`, `server.json`, and STDIO, so the public tool count stays at 14.
- Replace-edit is a genuinely separate code path from consolidation's merge/append `update_memory()` — Console edits never add `[merged]` markers or merge-history metadata.
- Deleting a memory now understands compaction lineage: it marks affected staging candidates stale, strips the deleted ID from any summary that referenced it, and restores orphaned sources if the summary itself gets deleted, instead of leaving dangling references.
- Concept-graph provenance cleanup runs as a best-effort step after a delete commits — it never rolls back a successful memory delete if cleanup fails, and Console now surfaces that failure/skip status to the user instead of discarding it.
- Bulk delete requires an explicit, bounded ID list (server-enforced max of 100) and now requires literally typing `DELETE` in the Console UI before the request fires, replacing a plain yes/no confirm dialog.
- Fixed a race in `test_stdio_transport.py` on slow CI runners: the STDIO subprocess test closed stdin immediately after writing, letting the server's EOF teardown race its own pending `tools/list` response. Switched to a `Popen` + watchdog pattern that keeps stdin open until the response arrives.

</details>

<details>
<summary><strong>July 15th, 2026: Log-Entry Cross-Transport Dedup (v2.21.3)</strong></summary>

### Shared Log-Entry Logic

- `endpoints/logging.py` (HTTP) and `services/stdio_entry_tools.py` (STDIO) each carried their own near-identical copy of `marm_log_entry`/`marm_log_show`/`marm_delete`'s session-switch detection, SQL, and dual-write-to-semantic-memory logic. Extracted into a shared `services/log_entry.py`; both transports now call the same functions through thin, transport-specific wrappers.
- Fixed an information-disclosure gap: STDIO's error responses used to return raw exception text (e.g. SQLite paths/schema) to the client on failure. Now returns the same fixed generic messages HTTP already used, logging the real exception server-side instead.
- Fixed a latent bug: HTTP's whole-session `marm_delete` deleted from `session_summary_cache` without a `try/except` guard, unlike every other cache-invalidation touch in both files (including STDIO's equivalent). Unified on the guarded behavior for both transports.

</details>

<details>
<summary><strong>July 14th, 2026: HTTP and STDIO Server Module Refactors (v2.21.2)</strong></summary>

### Server Module Boundaries

- Split the HTTP server's supporting concerns into focused modules while preserving the existing FastAPI app, route registration, MCP whitelist, CLI entry points, and lifespan behavior. The new boundaries cover CLI/bootstrap, compaction scheduling, protocol-delivery state and middleware, analytics, dependency checks, multiprocess warnings, and logging filters.
- Split STDIO support into dedicated logging, tool-lifecycle, log-entry, and graph/concept tool modules. The public `marm_mcp_server.server_stdio` entry point remains the compatibility surface for existing users and scripts.
- STDIO graph and concept tool registration is now explicit after the seven core tools, preserving the public `tools/list` order regardless of import order. HTTP and STDIO continue to expose the same 14 tools.
- Added regression coverage for the real STDIO `marm_log_show` path, graph/concept wrapper boundaries, and the ordered `tools/list` response. Docker STDIO tool discovery now keeps stdin open until the response is received, matching real MCP client behavior and avoiding an EOF race on slow CI runners.

</details>

<details>
<summary><strong>July 12th, 2026: CI Docker Test Fix, PyPI Publishing Paused (v2.21.1)</strong></summary>

### Docker Tests Fixed on Linux CI Runners

- The docker-marked tests bind-mount pytest's `tmp_path` into `/home/marm/.marm`, but on Linux hosts that directory is created mode 700 and owned by the host user, so the container's non-root `marm` user couldn't write it — the server died at DB init and every mount-dependent test failed. A new `marm_data_dir` fixture makes the mounted dir world-writable first. Windows Docker Desktop was never affected, which is why the failure only surfaced in CI.

### PyPI Publishing Paused

- The v2.20.0 repo rename (`MARM-Systems` → `marm-memory`) broke PyPI trusted publishing: the publisher config on PyPI still expects the old repo name, and account access is being recovered, so `publish-pypi` is temporarily disabled in the release workflow. `publish-mcp-registry` pauses with it since the registry validates the PyPI version. Docker Hub images and GitHub releases stay current; `pip install marm-mcp-server` serves 2.18.0 until access is restored.

</details>

<details>
<summary><strong>July 11th, 2026: Log Entries Join Semantic Memory, LoCoMo Benchmark (v2.21.0)</strong></summary>

### Log Entries Are Now Semantically Recallable

- `marm_log_entry` dual-writes: every entry is stored in `log_entries` as before AND embedded into the `memories` table through the serialized write queue, so `marm_smart_recall`'s hybrid semantic + FTS5 engine can actually find logged content. Previously nothing agent-facing wrote to `memories` — the semantic engine was only reachable through the dashboard's manual Add Memory form.
- The response gains a `memory_id` field alongside `entry_id`. A semantic-store failure never fails the log write itself (`memory_id: null`).
- Dual-written memories carry `metadata.source = "log_entry"` and `metadata.log_entry_id` for provenance, and flow into compaction like any other memory.
- `marm_delete` (type="log") cascades: deleting a log entry or a whole log session also removes the dual-written semantic memories (matched by `metadata.log_entry_id` / `metadata.source`), so deleted logs stop surfacing in recall. Response gains a `memories_deleted` count.
- Tradeoff to know: each `marm_log_entry` call now waits on the serialized write queue for an embedding before returning, instead of a single cheap INSERT. Fine for normal agent logging; heavy concurrent writers share one queue.
- HTTP and STDIO parity maintained; existing pre-2.21 log rows are untouched and still surface via `include_logs`.

### Recall Log Results Carry IDs

- `marm_smart_recall`'s `log_results` entries (with `include_logs=True`) now include the log entry `id`, so a recalled log row can be tied back to the exact entry that produced it (both transports).

### Knowledge Graph Console

- Concept builds now persist durable scoped run records in the isolated concept database, including queued/running/terminal state, extraction counts, duration, and stable error codes.
- MARM Console starts concept builds asynchronously, polls durable run status, surfaces stale local runs as errors, and preserves HTTP/STDIO concept-build behavior through one shared endpoint path.
- The Console Knowledge workspace now supports entity provenance (source memories and linked code), bounded directional/predicate neighborhood queries, and read-only same-scope duplicate candidates from entity embeddings.

### LoCoMo Retrieval Benchmark

- Added `scripts/benchmarking/accuracy/locomo/` — a deterministic, LLM-free retrieval benchmark against the LoCoMo long-conversation dataset. Ingests each conversation through `marm_log_entry`, then checks whether `marm_smart_recall` surfaces the gold evidence turns for every annotated question. Pure evidence-ID matching, per-category and per-lane (semantic vs log) hit rates, no judge model anywhere.

</details>

<details>
<summary><strong>July 10th, 2026: Project Rename to marm-memory, Doc Overhaul (v2.20.0)</strong></summary>

### Project Rename

- GitHub repository renamed from `MARM-Systems` to `marm-memory`. The PyPI package (`marm-mcp-server`), Docker image (`lyellr88/marm-mcp-server`), and MCP Registry listing are unchanged — this is a repo/branding rename only, no installed artifact names moved, no tool schema changed, nothing breaks for existing consumers.
- All GitHub URLs, clone instructions, and badge links updated across `README.md`, `CONTRIBUTING.md`, `CONTRIBUTORS.md`, the install guides, issue templates, and the `marm-init` skill.
- New hero image and wordmark reflecting the `marm-memory` name; the old logo's baked-in project name text is gone in favor of an icon + separately-editable text lockup, so future name changes don't require regenerating artwork.

### Documentation Consolidation

- `MCP-HANDBOOK.md` merged into `README.md` and removed as a standalone file (mirrored across `marm-mcp-server/README.md` and `marm-mcp-server/marm-docs/README.md`).
- Added an architecture-only competitor comparison table (Mem0, Letta, Zep/Graphiti, agentmemory) under Performance & Scaling Benchmarks.
- Fixed stale tool-count references (12 tools/v2.18) left over from the v2.19.0 concept-graph launch in `docs/PROTOCOL.md`, `docs/PROTOCOL-LITE.md`, `marm-mcp-server/server.json`, and their `marm-docs` mirrors — all now correctly reflect 14 tools.
- Added `AGENTS.md` with an architecture summary and a consistency checklist for future tool/version changes.
- Added a root `NOTICE` file with the Apache 2.0 copyright statement. Root `LICENSE` text is unmodified, per Apache convention (attribution belongs in `NOTICE`, not the license terms).

### `marm-init` Skill

- API keys are no longer generated or handled by the connecting agent for setups that require one (Docker HTTP, or local HTTP exposed via `SERVER_HOST=0.0.0.0`). The skill now hands the user copy-paste instructions to run in their own terminal, so key values never enter the conversation.
- Fixed the Docker HTTP command block: missing `-e SERVER_HOST=0.0.0.0` and an incorrect data volume mount (`-v marm-data:/app/data` instead of `-v ~/.marm:/home/marm/.marm`).
- Added the code-graph Docker mount pattern (mounting a host repo into the container for `marm_graph_index`) and a Windows/Codex `--bearer-token-env-var` connection path.
- Fixed the dashboard address, which pointed at a nonexistent `localhost:8002`; the dashboard actually mounts at `localhost:8001/dashboard`.

</details>

<details>
<summary><strong>July 7th, 2026: Concept Graph (v2.19.0)</strong></summary>

### New Tools

- Added `marm_concept_build` and `marm_concept_recall` — extracts entities (concept/decision/pattern/error/tool, plus person/org/gpe/product/event from spaCy's NER) and relationships out of stored memory content, and lets an agent query them by name or as a "related to X" traversal. Optionally cross-links extracted entities to marm-graph code symbols when marm-graph is available and indexed for the project.
- Runs entirely in-process — its own SQLite file (`~/.marm/index/marm_index.db`, own connection pool, never shares `memory.py`'s pool) and its own extraction pass, reading memory content directly (never through `marm_smart_recall`'s ranked/limited recall path). `marm_concept_build` is explicit/on-demand, not a live hook into the memory write path.
- Optional dependency: base installs carry no spaCy. `pip install marm-mcp-server[concepts]` plus a separate `python -m spacy download en_core_web_sm` enables real extraction; without it, both tools stay registered and return `entities_extracted: 0` cleanly (same fail-open pattern as `SEMANTIC_SEARCH_AVAILABLE`).
- Marm-mcp's discoverable tool count moves from 12 to 14 (HTTP and STDIO parity).

### Typed Relationships, Multi-Hop Recall, Entity Resolution

- Relationships now carry real predicates (`fixes`/`implements`/`depends_on`/`uses`/`causes`/`replaces`/`extends`, plus `related_to`/`co_occurs_with` fallbacks) derived from spaCy's dependency parse, instead of a single generic `co_occurs_with` label on every edge. No LLM call involved.
- `marm_concept_recall` gains `depth` (1-5, default 1) and `direction` (`outgoing`/`incoming`/`both`, default `both`) for multi-hop traversal — defaults reproduce the original one-hop behavior exactly. Backed by a bounded, cycle-safe in-process BFS over the concept graph's own tables.
- `marm_concept_build` now flags fuzzy-candidate near-duplicate entities (via cosine similarity on the existing fastembed encoder — no new dependency) as a `possible_duplicates` field, without ever auto-merging them. Exact-match dedup is unchanged.

</details>

<details>
<summary><strong>July 7th, 2026: Fastembed Embedding Backend (v2.18.0)</strong></summary>

### Semantic Search

- Replaced `sentence-transformers` + `torch` with `fastembed` (ONNX Runtime-based) as the encoder backend. Same model (`sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions), same recall behavior, same DB schema — verified numerically equivalent before the swap (1.0000 cosine similarity across a real-sentence test corpus, identical top-5 retrieval ranking against both backends).
- Cuts the main Docker image's dependency footprint substantially: `torch`'s CPU wheel alone was 200MB+, plus the `scipy`/`scikit-learn` `sentence-transformers` also required — `fastembed` needs none of that.
- The lean `glama-latest` image (`requirements-glama.txt`) gains real semantic search for the first time. It previously shipped with neither `torch` nor `sentence-transformers`, so semantic recall was fully disabled there (text-search fallback only); `fastembed` is light enough to include in that build too.
- Failure behavior is unchanged: if the encoder fails to load (no network, disk full, etc.), memory falls back to text-only search without affecting core memory, logging, notebook, or startup — same as before.

</details>

<details>
<summary><strong>July 6th, 2026: STDIO Graph Tool Parity (v2.17.1)</strong></summary>

### STDIO Transport

- Added the 5 bundled marm-graph tools (`marm_graph_index`, `marm_code_lookup`, `marm_graph_trace`, `marm_graph_architecture`, `marm_graph_impact`) to `marm_mcp_server.server_stdio`, bringing STDIO's discoverable tool count from 7 to 12 and matching the HTTP surface.
- STDIO graph tools reuse the same `graph_supervisor` and `marm_graph.core.tool_router` path HTTP uses; no second graph process, no new install step, no port or API key added to STDIO.
- Graph startup stays lazy (triggered by the first graph tool call) and degrades cleanly (`{"status": "error", "message": "graph backend unavailable"}`) if the graph engine is disabled or fails to start, without affecting the 7 core memory tools.
- `graph_supervisor.stop()` now runs during STDIO shutdown so a started graph child process is not left running after the STDIO process exits.

</details>

<details>
<summary><strong>July 6th, 2026: Unified Graph & Dashboard Package Layout (v2.17.0)</strong></summary>

### Packaging Cleanup

- Folded the first-party graph and dashboard packages into `marm-mcp-server` so pip and Docker installs ship one unified MARM system instead of separate root packages.
- Removed the standalone root `marm-graph/` and `marm-dashboard/` package trees after preserving the active graph/dashboard source inside `marm-mcp-server/`.
- Bundled `marm_graph*` and `marm_dashboard*` through `marm-mcp-server` package discovery, including dashboard static assets.
- Updated the Docker build to copy `marm_graph` and `marm_dashboard` before `pip install`, so both modules are installed into the wheel instead of relying on raw `PYTHONPATH` imports from the final image layer.
- Removed the local-only `marm-dashboard==1.2.0` Docker extra dependency that could not resolve from PyPI during image builds.
- Hardened `.dockerignore` and disabled pytest's repo-local cache provider to keep generated pytest/cache folders out of Docker build contexts on Windows.

### Tests

- Migrated dashboard auth, database, MCP status, and compaction tests into `marm-mcp-server/tests`.
- Migrated graph client/router tests into `marm-mcp-server/tests` and kept graph test hygiene notes with the unified test suite.
- Verified focused graph + dashboard coverage after the move (`86 passed`, one Pydantic deprecation warning).

</details>

<details>
<summary><strong>July 6th, 2026: Official MCP SDK for STDIO Transport (v2.16.2)</strong></summary>

### Dependency Fix

- Replaced the external `fastmcp` package with the official `mcp` Python SDK's compatibility class (`mcp.server.fastmcp.FastMCP`) for all STDIO transports, including the embedded graph package. `@mcp.tool()` / `mcp.run()` usage is unchanged.
- `fastmcp` is no longer a runtime dependency anywhere in the release packaging (`pyproject.toml`, `requirements.txt`, `requirements_stdio.txt`, `requirements-glama.txt`), removing a `python-dotenv>=1.1.0` requirement that conflicted with common AI tooling (e.g. `litellm==1.83.7` pins `python-dotenv==1.0.1`).
- HTTP transport is untouched: `fastapi-mcp` already depends on the official `mcp` SDK and was never the source of the conflict.
- Existing STDIO tool surface, response shapes, and decorator/logging order are unchanged.

</details>

<details>
<summary><strong>July 5th, 2026: Pip & Docker Packaging Unification (v2.16.1)</strong></summary>

### Unified Packaging

- `pip install marm-mcp-server` now includes the embedded graph/index package path instead of requiring users to install or publish a separate `marm-graph` package.
- `lyellr88/marm-mcp-server:latest` is now an all-in-one image: memory, the embedded graph engine, and the dashboard all run in one process on one port (8001). Dashboard is reachable at `http://host:8001/dashboard` instead of its own image/port.
- **Breaking tag semantics**: `:latest`'s meaning has changed. Anyone pinning `:latest` in scripts, cron jobs, or compose files gets the new all-in-one behavior automatically. Pin `:memory-only` (or a pre-v2.16.0 version tag) to keep the previous memory-only image shape.
- Docker builds now install from `pyproject.toml` (`pip install ".[docker-image]"`) instead of `requirements.txt`, closing a pre-existing drift between the two files. The CPU-only Torch pin from the v2.15.2 fix is preserved through a build-time constraints file plus the same PyTorch CPU wheel index.
- The pinned `codebase-memory-mcp` engine binary is now baked into the unified `marm-mcp-server` image at build time through an independently verified download plus SHA256 checksum.
- Image size increases meaningfully versus the previous `marm-mcp-server:latest` (baked ~269MB engine binary + dashboard's dependencies) — expect a larger pull/storage footprint.

</details>

<details>
<summary><strong>July 4th, 2026: Embedded Code Graph & Project Indexing (v2.16.0)</strong></summary>

### marm-graph

- Added the `marm-graph` integration layer for project indexing, code lookup, graph tracing, architecture inspection, and change-impact analysis.
- Wrapped the pinned `codebase-memory-mcp` engine behind a safer MARM-facing API so agents can query code structure without talking to the upstream binary directly.
- Added five graph tools to the HTTP MCP surface: `marm_graph_index`, `marm_code_lookup`, `marm_graph_trace`, `marm_graph_architecture`, and `marm_graph_impact`.
- Kept graph startup lazy so the normal memory/logging server remains light until a graph command is actually used.
- Added backend hardening for protocol framing, update-notice handling, timeout behavior, neutral child-process working directory, response limits, and loopback/API-key access boundaries.
- Documented the graph/index packaging direction so MARM can move toward one unified memory system with graph/indexing bundled into the main server package.

### Tests & Docs

- Added focused graph tests for tool routing, backend supervision, HTTP endpoint behavior, MCP tool visibility, response limiting, and authentication boundaries.
- Added graph/index planning docs covering protocol proof, packaging integration, auto-indexing follow-up work, and future test isolation cleanup.

</details>

<details>
<summary><strong>July 2nd, 2026: Docker & CI Dependency Fixes (v2.15.2)</strong></summary>

### Docker & CI

- Forced CI validation installs through `requirements.txt` before installing the editable package with `--no-deps`, preventing unconstrained `pyproject.toml` resolution from pulling the CUDA Torch stack into GitHub Actions.
- Pinned Docker/runtime installs to the CPU Torch wheel path so image builds avoid `nvidia-*`, `cuda-toolkit`, and `triton` dependency bloat.
- Simplified Docker ignore patterns for BuildKit compatibility and kept local pytest/cache/temp folders out of MCP server image build contexts.

</details>

<details>
<summary><strong>July 2nd, 2026: Exact Retrieval Lane (v2.15.1)</strong></summary>

### Exact Recall for Code, Config & Commands

- Added an exact/lexical retrieval lane for syntax-heavy recall queries such as config constants, CLI flags, file paths, function calls, API/tool names, dotted namespaces, HTTP routes, URLs, and quoted command strings.
- Added automatic query detection through `exact_mode="auto"` so normal users and agents get deterministic exact recall without changing their prompts or tool calls.
- Added explicit `exact_mode` controls across HTTP, STDIO, service, and core recall paths: `"auto"` for automatic routing, `"exact"` to force deterministic FTS/BM25 with LIKE fallback, and `"semantic"` to force vector recall.
- Preserved project/platform filtering and session scoping in the exact lane so exact lookups respect the same attribution boundaries as semantic recall.

### Tests

- Added focused coverage for exact-query detection, exact/auto/semantic routing, lexical fallback behavior, response shape, scan metadata compatibility, session scoping, project/platform scoping, and exact-match ranking precedence.

</details>

---

<details>
<summary><strong>June 24th, 2026: Guided Setup (v2.15.0)</strong></summary>

### marm-init Guided Setup

- Added the `marm-init` skill as the recommended setup path so agents can guide users through MARM installation instead of leaving them to manually piece together MCP config files.
- The skill detects or installs the MARM engine, loads the current protocol, chooses between Python/Docker and HTTP/STDIO, handles local or remote server setup, wires client connection commands, and can link multiple agents to the same memory server.
- Added dashboard startup guidance and handoff behavior so setup ends with a live MARM connection and clear next steps.

### Tests & Docs

- Updated README setup flow to feature `marm-init` first, collapse manual install paths into targeted dropdowns, and make contribution/license language more welcoming.

</details>

<details>
<summary><strong>June 20th, 2026: Project & Platform Attribution (v2.14.2)</strong></summary>

### Project & Platform Metadata

- Added nullable `project` and `platform` attribution columns to memories, log entries, and notebook entries so MARM can distinguish work from different repositories, clients, and agent surfaces without splitting the local SQLite database.
- Added `MARM_PROJECT` and `MARM_PLATFORM` settings with safe auto-detection plus explicit environment overrides for Docker, servers, and custom client setups.
- Tagged new memory, log, and notebook writes with detected attribution metadata while preserving existing untagged rows as global/unscoped history.

### Scoped Recall & Consolidation Safety

- Extended `marm_smart_recall` with optional `project` and `platform` filters across HTTP and STDIO, including memory recall and `include_logs=True` log search.
- Applied attribution filters through FTS candidate fetches, FTS scoring, semantic fallback scoring, and LIKE fallback so scoped recall stays consistent across retrieval lanes.
- Scoped exact duplicate detection and semantic write-time merge checks to the current project/platform pair to prevent accidental cross-project or cross-client consolidation.

### Tests & Docs

- Added focused coverage for project/platform schema migrations, write tagging, scoped recall, HTTP request handling, log filtering, notebook attribution, scoring filters, and consolidation isolation.
- Updated README, MCP handbook, FAQ, contributing guidance, packaged docs, and project architecture references with the new attribution behavior.

</details>

<details>
<summary><strong>June 17th, 2026: Docs, Assets & Community (v2.14.1)</strong></summary>

### Documentation & README

- Renamed "What MARM Is Now" section to "How It Works" for clearer first-impression framing.
- Added token layer row to the architecture table covering the lightweight 7-tool surface, semantic re-rank before retrieval, and write-time deduplication.
- Expanded the intro paragraph to surface token cost efficiency alongside the tool surface and consolidation story.
- Rewrote the contribution blurb to lead with non-code paths: testing, reporting, Discussions, and Discord.
- Added unsupported-client CTA after the Connect Your Client Fast section directing users to open an issue for new client adapters.
- Replaced static pip install badge with a live PyPI version badge.
- Added Discord community badge to the badge row.
- Added inline Discussions comment to the Local pip HTTP Quick Start install block.

### Community & GitHub

- Added YAML issue form templates: `bug_report.yml`, `feature_request.yml`, and `config.yml` with blank issue filing disabled and contact links to Discussions, Discord, and FAQ.
- Added `CONTRIBUTORS.md` listing all merged PR contributors with profile links and PR references.
- Added community startup print line to server on launch pointing to Discord and Discussions.

### Assets & Demo

- Updated `mcp-tools.png` asset.
- Added `marm-bench.png` benchmark asset.
- Updated demo video to v2.14.0 reflecting the current 7-tool surface, chunked embeddings, write-time consolidation, and token cost scene; extended runtime from 30s to 35s.

</details>

<details>
<summary><strong>June 16th, 2026: Memory Core Modularization (v2.14.0)</strong></summary>

### Memory Core Refactor

- Split the growing memory core into focused modules while preserving the public `MARMMemory` facade and existing MCP tool behavior.
- Moved shared helpers, SQLite schema/connection routines, chunk-aware scoring, and high-level memory operations into dedicated files so future recall, compaction, and write-path changes can be reviewed in smaller units.
- Added parity validation against the pre-refactor memory implementation to guard method signatures, database behavior, recall behavior, stale chunk handling, and core operational contracts during the extraction.

### Logging, Protocol & Summary Flow

- Removed `marm_context_log` and the old explicit session-log tool from the public MCP surface; session routing now goes through structured `marm_log_entry` entries such as `Session: ...` and `Topic: ...`.
- Reworked session summaries around a server-managed `session_summary_cache` table so `marm_summary` rebuilds only when logs change, validates cached entry counts before reuse, prunes cache rows on session deletion, and trims oversized responses to stay within MCP limits.
- Consolidated HTTP and STDIO summary generation through a shared summary service so both transports use the same cache, truncation, and empty-session behavior.
- Expanded the protocol docs with domain-specific "when to act" guidance for coding, research, game development, writing/journalism, and everyday workflows while keeping the public tool set lean.
- Documented the planned `marm-init` skill path for future full-protocol bootstrap, while current runtime protocol delivery continues to use first-tool full protocol injection plus periodic `PROTOCOL-LITE` refresh.

### Maintainer Notes

- This release line started as an internal maintainability refactor, then expanded to remove legacy logging/context tools from the user-facing MCP surface while preserving the underlying logging and summary workflows.
- The public MCP surface is now 7 tools after removing legacy user-facing context/session helpers; behavior moved behind `marm_log_entry`, `marm_summary`, and server-managed automation instead of being exposed as separate tools.
- Additional refactor work may land under this version before release.

</details>

<details>
<summary><strong>June 15th, 2026: Filter→Re-rank Recall Refactor (v2.13.0)</strong></summary>

### Recall Performance & Search Strategy

- Replaced weighted-fusion hybrid recall with an FTS-first filter→semantic re-rank path in `recall_similar()`: FTS5 BM25 now narrows recall to a bounded candidate set first, then semantic cosine scoring reranks only those candidates instead of scanning the full embedding lane on every keyword-rich query.
- Added `FTS_CANDIDATE_LIMIT` (default `50`) as the new cap controlling how many FTS candidates are fetched before semantic reranking; bounded semantic fallback remains in place for abstract queries, malformed/weak FTS coverage, and unscoreable candidate sets.
- Preserved temporal weighting, response shape, and bounded-recall metadata while changing `recall_scan_truncated` semantics so it only reflects the semantic fallback lane rather than the primary filter→rerank path.

### Long-Memory Embedding Coverage

- Added chunked embeddings for long memories through a `memory_chunks` sidecar table so content beyond the base encoder window is still searchable instead of being truncated to one parent embedding.
- Kept short memories on the existing single-vector `memories.embedding` path while long memories are split into overlapping chunks, scored chunk-aware in both rerank and fallback recall lanes, and collapsed back to one parent result using the best chunk similarity.
- Moved long-memory chunk writes off the agent-visible return path with background scheduling, enabled SQLite foreign-key enforcement for cascade cleanup, and added dedicated chunking coverage plus a smoke script for end-to-end validation.

### Test Coverage

- Reworked hybrid recall tests around the new architecture: filter→rerank success, semantic fallback on empty FTS, fallback on missing/unscoreable candidates, wrong-dimension candidate handling, candidate-cap enforcement, and scan-metadata behavior.
- Added chunking tests covering boundary splitting, parent-level dedup by best chunk score, schema creation, cascade delete, stale-chunk cleanup on merge, and parent-content recall behavior for long memories.

</details>

<details>
<summary><strong>June 9th, 2026: Discord Community Ops & Webhook Automation (v2.12.1)</strong></summary>

### Discord Community Operations

- Added `marm-bot-discord/` operations workspace with focused scripts for bootstrap, forum migration, permission sync, message sync, and webhook sync; managed server layout for Information, Community, MARM Support, and Technical categories with forum-channel support.

### GitHub -> Discord Automation

- Added release-only Discord announcements workflow and contributor-activity workflow for `#get-involved` covering PR opened/merged, issue opened/labeled events; webhook management helpers for provisioning and refreshing channel webhooks.

</details>

<details>
<summary><strong>June 7th, 2026: Hybrid Recall with FTS5 (v2.12.0)</strong></summary>

### Recall & Search

- Added SQLite FTS5 indexing for memory content with automatic insert/update/delete triggers; `marm_smart_recall` merges semantic similarity with FTS BM25 keyword scoring via `HYBRID_SEARCH_TEXT_WEIGHT`, improving recall for commands, config keys, filenames, and error strings.
- Added conservative temporal weighting via `TEMPORAL_WEIGHT` and `TEMPORAL_HALF_LIFE_DAYS` for modest recency boost when matches are close; FTS backfill on DB init for existing stores; LIKE fallback for unsanitizable queries.
- Added 3-layer retrieval depth control (`detail=1/2/3`) with read-time truncation: Layer 1 ~200 chars, Layer 2 ~500 chars, Layer 3 full content; `detail_level` surfaced in recall responses.

</details>

<details>
<summary><strong>June 7th, 2026: Deterministic Compaction Fallback & Vectorized Recall (v2.11.0)</strong></summary>

### Compaction Reliability

- Added server-side extractive compaction summarization for `nudge_exhausted` candidates so compaction no longer depends only on connected agent obeying prompt nudges; centroid-based summarizer ranks source memories by embedding centrality, skips near-duplicates, falls back to source text when embeddings unavailable.
- Compaction maintenance scheduler starts whenever `COMPACTION_ENABLED=1`; auto-apply remains optional via `COMPACTION_AUTO_APPLY_ENABLED=1`; nudge-exhausted candidates with missing sources are marked `stale` instead of stuck forever.

### Recall Hot-Path Completion

- Replaced per-row Python cosine scoring with batched NumPy matrix scoring; moved SQLite embedding fetches and vector scoring into worker thread so large scans no longer block event loop.
- Raised default `RECALL_SCAN_LIMIT` from 1000 to 10000; preserved bounded-recall metadata and wrong-dimension embedding safeguards.

### Swarm & Runtime Guardrails

- Persisted compaction write counters in SQLite so trigger progress survives process restarts; added startup detection for unsupported multi-worker HTTP deployments with clear warning to run one MARM process per SQLite database.

</details>

<details>
<summary><strong>June 6th, 2026: Recall Visibility, Protocol Scope & Service Refactor (v2.10.0)</strong></summary>

### Recall & Search Reliability

- Added `RECALL_SCAN_LIMIT` so semantic recall's bounded DB scan is configurable; `recall_similar()` scans `limit+1` rows to detect truncation and returns `recall_scan_truncated`/`recall_scan_limit` metadata on both success and no-result paths.
- Standardized MCP tool failures to return structured `{"status":"error"}` payloads instead of opaque HTTP 500 exceptions.

### Protocol & Agent Session Handling

- Changed HTTP protocol injection from server-global to per-session tracking so multiple agents/sessions each receive the MARM protocol once, with compaction nudges prevented from co-injecting with protocol initialization.

### Consolidation Safety

- Capped write-time merge growth at 10,000 characters so hot near-duplicate memories cannot grow into unbounded blobs; preserves newest content while trimming older when merge would exceed cap.

</details>

<details>
<summary><strong>June 6th, 2026: Comment Cleanup, Ruff Lint Pass & Doc Updates (v2.9.2)</strong></summary>

### Code Quality

- Removed ~500 lines of stale inline comments and large Dockerfile comment block; stripped shebang lines
- Resolved all Ruff E402 violations; replaced bare try/except with importlib.util.find_spec(); fixed F841/F722/E722; guarded ExceptionGroup for Python 3.10 compat

### Documentation

- Added Docker STDIO JSON config to INSTALL-DOCKER.md; Discord link to README; contact section to CONTRIBUTING.md

</details>

<details>
<summary><strong>June 4th, 2026: Opus Review Hot-Path & Compaction Hardening (v2.9.1)</strong></summary>

### Hot-Path Performance Hardening

- Offloaded sentence-transformer encoding via `asyncio.to_thread()` so CPU-heavy embedding work no longer blocks the event loop; added serialized encoder helper to avoid unsafe concurrent encoder use.
- Reused precomputed write embedding for write-time semantic consolidation, removing double-encode path; extended `recall_similar()` and `find_semantic_duplicate()` with optional `query_vec` path to avoid redundant embedding work.

### Compaction Tool Reliability

- Made `source_memory_ids` optional when staging compaction summaries; server uses staged candidate's source IDs when omitted.
- Rewrote `marm_compaction` tool descriptions as agent-facing workflow: `status/candidates -> stage -> review -> apply/discard`; offloaded compaction summary embedding to non-blocking encoder path.

### HTTP Injection & Middleware Hardening

- Added HTTP MCP middleware fast path that skips response buffering/parsing after protocol delivery when compaction injection is disabled, with defensive non-JSON response guard.
- Aligned HTTP compaction injection with STDIO behavior so protocol delivery and compaction nudges do not co-inject on same first tool call.

### Embedding Compatibility Guard

- Added runtime dimension check before cosine scoring stored embeddings; wrong-dimension vectors are now skipped with diagnostic signal instead of silently crashing recall after embedding-model dimension change.

</details>

<details>
<summary><strong>June 1st, 2026: Consolidation Worker, Compaction Pipeline & Swarm Smoke Harness (v2.9.0)</strong></summary>

### Memory Consolidation

- Added exact deduplication via SHA-256 content hashes and write-time semantic consolidation for near-duplicate memories with merge history tracking; memory updates recompute content_hash and refresh embeddings when encoder available; hash-collision safety requires normalized content equality before deduping.

### Compaction Worker

- Added background compaction with agent-driven staged workflow (detect -> stage -> review -> apply/discard) behind `marm_compaction` tool, including candidate expiry, source validation, cross-session isolation, and idempotent apply; existing stored embeddings can be compacted even when local encoder is unavailable.

### Write Queue & Scheduler Integration

- Extended write queue with `put_callable()` so non-memory-write mutations (compaction apply) run through the same serialized queue; added optional compaction auto-apply scheduler behind `COMPACTION_AUTO_APPLY_ENABLED` with runtime presets per deployment mode.

### Swarm & Compaction Smoke Testing

- Added `compaction-worker-smoke.py` and `swarm-smoke.py` for HTTP load, staged compaction, apply idempotency, stale guards, cross-session isolation, and scheduler testing with seeded embedding fallback for deterministic runs.

### Documentation

- Consolidated duplicated FAQ content into `docs/FAQ.md`.

</details>

---

<details>
<summary><strong>May 29th, 2026: Write Queue & Swarm Rate Presets (v2.8.0)</strong></summary>

### Write Queue & Swarm Runtime Modes

- HTTP server runtime presets: `--swarm` (write queue + 200 RPM), `--swarm-max` (write queue + 600 RPM), `--trusted` (write queue + no rate limiting), `--rate-limit-rpm N` (explicit custom RPM, `0` disables); raised default shared HTTP rate-limit to 80 RPM; aligned `/mcp` requests to shared default bucket

### Docker & Dependencies

- Switched to `ENTRYPOINT` so flags like `--swarm` append naturally; updated Docker STDIO examples to override entrypoint; added `packaging` as explicit dependency (FastMCP imports it during STDIO startup); removed unfinished MCP client command generator prototype from tracking

### Testing

- Direct write-queue smoke testing for concurrent SQLite writes; HTTP write/RPM smoke testing with isolated servers, custom RPM, and preset coverage; regression tests for runtime presets, disabled rate limiting, Docker STDIO entrypoint, and STDIO transport stability

</details>

<details>
<summary><strong>May 26th, 2026: Notebook Session Scoping & CI Hardening (v2.7.0)</strong></summary>

### Notebook Session Scoping

- `marm_notebook` accepts optional `session_name` (default `"main"`); active instruction lists isolated per session — fixes multi-client HTTP, shared Docker, and swarm workflows where `use`/`clear` previously overwrote single global active list; `marm_delete(type="notebook")` removes entries from all active session scopes; whitespace-only `session_name` rejected
- Saved notebook entries remain global and reusable; existing clients without `session_name` continue working unchanged via `"main"` default

### STDIO Teardown Hardening

- Replaced string/substring matching in `_is_graceful_teardown()` with concrete AnyIO `isinstance` checks (`ClosedResourceError`, `EndOfStream`, `BrokenResourceError`); recursive `ExceptionGroup` unwrapping — every sub-exception must be known teardown type before group is swallowed; widened to `BaseException`

### CI Hardening

- Unified dependency install to `pip install -e './marm-mcp-server[dev]'`; fixed `publish-mcp.yml` test working directory; aligned `fastmcp` pin across all dep files; updated pip cache keys to hash `pyproject.toml`; added `persist-credentials: false`; bumped `setup-python` to `@v5`

### Tests

- Service-level isolation and clear-scoping tests; HTTP and STDIO regression for multi-session isolation; whitespace validation; mixed `ExceptionGroup` regression

</details>

<details>
<summary><strong>May 21st, 2026: Protocol Delivery & Notebook Tool Consolidation (v2.6.1)</strong></summary>

### Protocol Delivery

- MARM delivers protocol context through first successful MCP tool response (HTTP middleware injects `[MARM SESSION INIT]`; STDIO injects `marm_protocol`); delivery tracked separately from documentation indexing so failed calls don't consume one-time delivery

### Protocol Refactor

- Refactored from chatbot-era copy/paste prompt into MCP runtime contract: MARM positioned as memory layer beneath MCP session; clarified operating rules for memory capture, recall, notebook use, and trust boundaries

### Notebook Tool Consolidation

- Five notebook tools consolidated into `marm_notebook(action="add"|"use"|"show"|"status"|"clear", ...)`; reduces MCP tool discovery from 12 to 8 tools; `marm_delete` kept separate for destructive operations; `marm_contextual_log` renamed to `marm_context_log` across all surfaces

### Tests

- Added regression coverage for protocol injection (HTTP and STDIO), notebook consolidation, tool discovery, and rename

</details>

<details>
<summary><strong>May 20th, 2026: STDIO File Logging & Rate Limiter Tuning (v2.6.0) </strong></summary>

### STDIO File Logging

- STDIO writes diagnostics to `~/.marm/logs/marm-stdio.log`; `_log_tool_call` decorator on all 18 tools logs name/status/exception only (no memory content, notebook data, or raw payloads); `stderr` stream handler outputs `[MARM]`-tagged lines alongside FastMCP
- `MARM_STDIO_LOG_LEVEL=DEBUG` adds session name, query length, and result counts; `MARM_STDIO_LOG_DIR` env var overrides log path; log file persists across restarts; file handler failure silently skipped

### Rate Limiter Tuning

- All tiers raised to 60 req/min; block duration reduced from 5-10 min to 30s — resolves AI clients hitting blocks during burst tool calls at session start

### IP Spoofing Fix

- `X-Forwarded-For` and `X-Real-IP` only trusted when TCP connection originates from local proxy (`127.0.0.1`/`::1`); remote callers cannot spoof loopback IP to bypass rate limiter or auth

### Active Session Routing

- `marm_log_session` sets `active_log_session`; `marm_log_entry` routes to that session automatically when no `session_name` passed; works across HTTP and STDIO

### Performance

- Lazy documentation loading: MARM protocol docs load on first `marm_start` instead of at server startup, reducing cold-start time; `marm_reload_docs` endpoint fixed (was stub since v2.0)

### Fixes

- Windows Proactor noise suppression: benign `WinError 10054`/`ConnectionResetError` from `asyncio` no longer pollute logs; Windows-safe print in `memory.py` via `_safe_print()` fallback to `sys.stderr.buffer`

### Tests

- 56 total passing: 4 new STDIO logging regression tests, new HTTP server logging tests

</details>

<details>
<summary><strong>May 18th, 2026: CodeQL Security Hardening & Release Cleanup (v2.5.5)</strong></summary>

### Security

- CodeQL clear-text key alert handled as intentional design; auto-generated exposed-server key output hardened (points to `~/.marm/.env` instead of printing raw key)
- Script tag sanitizer moved off regex backtracking: deterministic string scanning replaces polynomial regex; improved malformed script close handling (`</script foo>` no longer triggers destructive trailing-content loss); unterminated script fragments handled conservatively
- Added targeted sanitizer regression tests for MCP and dashboard: script blocks, malformed close tags, event handlers, JavaScript URLs, and SQL/session-scope paths

### Release Alignment

- README media references refreshed from missing SVG refs; project file layout cleaned up (`CHANGELOG.md`/`ACKNOWLEDGMENTS.md` at root, `PROTOCOL.md` in `docs/`); version sync script updated for new paths

</details>

<details>
<summary><strong>May 18th, 2026: CI/CD Pipeline, Registry Alignment & Security Fixes (v2.5.1–v2.5.4)</strong></summary>

### CI/CD & Publishing

- Rewrote MCP registry publish job using official publisher CLI; restored validate-and-test job; re-enabled Docker and PyPI publishing; fixed registry job dependency ordering

### Registry & Version Alignment

- Corrected GitHub username case in `server.json`; moved OCI version into identifier tag; bumped schema URL to `2025-12-11`; fixed MCP server name annotation case; aligned all version surfaces (pyproject.toml, Dockerfile, server.json) across v2.5.2–v2.5.4

### Security

- Resolved 7 CodeQL alerts across MCP server and dashboard; replaced regex-based script-tag stripper with pure string implementation; patched wheel CVE at v2.5.4

### Repo Hygiene

- Untracked agent config folders (`.claude`, `.codex`, `.gemini`, `.qwen`) and `docs/archived`/`docs/current`/`docs/future`; cleaned up dashboard test artifacts; moved visuals from `docs/Visuals/` to root `media/`; added CI/CD and CodeQL badges to README

</details>

<details>
<summary><strong>May 17th, 2026: MARM Dashboard Launch v2.5.0</strong></summary>

### MARM Dashboard (v1.0.0)

- Standalone FastAPI app on `:8002` reading `~/.marm/marm_memory.db` — direct SQLite admin UI for browsing, editing, and managing all MARM data without the MCP server
- Full CRUD across memories, sessions, protocol logs, and notebook; session chip to filter memories by session; inline edit with form reuse; confirm dialogs with counts; relative timestamps; loading screen; Overview tab with live stats grid, DB path, MCP status pill
- Auth via `MARM_API_KEY` (loopback-only when unset, bearer when set); key kept in browser memory only; MCP status probe via server-side `urllib` to avoid CORS
- Docker support with safe run pattern mapping `127.0.0.1:8002`; 24 tests covering all CRUD paths, search, pagination, sanitization, and auth

### Architecture

- Direct SQLite admin UI — edits bypass MCP tool events but use same tables and sanitization rules; SQLite WAL mode + `busy_timeout` allow MCP and dashboard concurrent access; static assets from `marm_dashboard/static/` with cache-busting

</details>

<details>
<summary><strong>May 17th, 2026: Docker Dual-Transport Alignment & WebSocket Purge Start (v2.4.0)</strong></summary>

### Added

- Docker dual-transport docs: one image, two modes — HTTP (long-running/shared, requires `MARM_API_KEY`) and STDIO (local/private, no HTTP key)
- Client auth troubleshooting: key formatting, duplicate MCP entries, process/env mismatch, and 401 interpretation
- Qwen quick-install HTTP transport commands for both local no-key and Docker/exposed key mode

### Changed

- README Quick Start reorganized around practical first-use paths: local pip HTTP/STDIO, Docker HTTP/STDIO; install docs aligned to current client behavior

### Removed

- WebSocket-first language and stale WebSocket test callouts from active install docs

</details>

<details>
<summary><strong>May 16th, 2026: MCP Client Compatibility & Mock OAuth Removal (v2.3.0)</strong></summary>

### Removed

- Deleted mock OAuth endpoint module and production route wiring; `/oauth/*` no longer mounted or bypassed; stale OAuth setup guidance removed from active install docs

### Verified MCP Clients

- Confirmed HTTP MCP setup for Claude Code, Codex, Gemini CLI, Qwen Code, VS Code MCP/Copilot Agent, and Cursor MCP; updated docs for xAI/Grok Remote MCP (local Grok CLI unverified)
- Added direct README client links and IDE setup examples (VS Code `.vscode/mcp.json`, Cursor `.cursor/mcp.json`)

### Impact

- Simpler auth surface: localhost pip zero-config; Docker/exposed/remote use bearer API keys; active docs match tested client behavior; updated Pro planning docs to position real OAuth 2.0/2.1 as hosted/team/cloud feature

</details>

<details>
<summary><strong>May 15th, 2026: Security Hardening, Auto-Key Generation & Doc Consistency Pass (v2.2.9)</strong></summary>

### Security Fixes

- Dockerfile: added `SERVER_HOST=0.0.0.0` so port mapping works in containers; documented Docker bridge false-401 root cause (loopback-only auth incompatible with Docker bridge gateway)
- OAuth open redirect: added `_is_loopback_uri()` validation gate rejecting non-loopback redirect URIs; moved OAuth client credentials to env vars; removed `/oauth/debug` endpoint
- Rate limiter middleware order fix: swapped auth/rate-limit registration so rate limiter runs first (Starlette LIFO order)
- Added reverse proxy note: behind nginx/Traefik/Docker bridge, `client.host` is proxy IP, not loopback — `MARM_API_KEY` required

### Auto-Key Generation

- New `utils/security.py`: `generate_api_key()` — 40 chars, ~244 bits entropy, 68 shell-safe chars guaranteeing at least one upper/lower/digit/symbol
- `--generate-key` CLI flag prints a key to stdout and exits (for Docker/manual deployments)
- Auto-generation on first exposed start: when `SERVER_HOST=0.0.0.0` and no `MARM_API_KEY`, auto-generates key, saves to `~/.marm/.env`, prints one-time banner; localhost stays zero-config; `--generate-key` guard prevents double-print when CLI flag and `SERVER_HOST=0.0.0.0` both active

### Documentation

- Standardized Docker key generation; rewrote README Security section with per-path config; corrected stale pip version in FAQ

### From v2.2.7 (March 20th)

- Absolute→relative imports across 16 files; added `__main__.py` for `python -m marm_mcp_server`; added `create_server()` and `main()` entry functions

</details>

---

<details>
<summary><strong>March 20th, 2026: Pip Install Fix & Docs Cleanup (v2.2.8)</strong></summary>

- Fixed broken pip install: converted absolute imports to relative imports across 16 files; added `__main__.py` for `python -m marm_mcp_server` and `create_server()`/`main()` entry functions
- Reorganized docs into archived/core/current/future folders; removed FAQ.md (merged into MARM-HANDBOOK.md) and DESCRIPTION.md (redundant with README)
- Created `docs/current/current-issues.md` tracking: session switching bug, planned token optimization (lazy doc loading), directory-based memory architecture

</details>

---

<details>
<summary><strong>September 25th, 2025: Security Hardening - 4 Critical Vulnerabilities Fixed (v2.2.7)</strong></summary>

- XSS: fixed malformed script tag bypass (spaces in closing tags like `</script >`, `< /script>`)
- ReDoS: added 10KB input length limit preventing exponential regex backtracking attacks
- Open redirect: restricted OAuth redirect_uri to localhost/relative paths only
- Stack trace exposure: replaced internal error details with generic messages across 19+ WebSocket handlers

</details>

<details>
<summary><strong>September 19th-23rd, 2025: WebSocket Production Launch & Alpha Tester Resolution (v2.2.6 Launch)</strong></summary>

- Resolved all 4 GitHub alpha tester issues: WebSocket MCP at ws://localhost:8001/mcp/ws with full HTTP parity (19 methods), parameter naming consistency, Docker persistence with volume mounts, health/readiness endpoints with DB connectivity testing
- Complete WebSocket production implementation: thread-safe connection manager, modular endpoint architecture, JSON-RPC 2.0 compliance, connection pooling with configurable limits
- Restored OAuth 2.0 implementation with authorization code flow (authorize, token, userinfo, revoke, debug endpoints); excluded from MCP tool discovery
- Graceful server shutdown: SIGTERM/SIGINT handlers, WebSocket connection cleanup during shutdown
- Modernized dependency management from exact pins to smart version ranges (>=X.Y.Z,<X+1.0.0)
- Fixed marm_log_entry date handling: sessions get automatic dates while entries preserve exact user input; synchronized package structure between root dev code and marm_mcp_server/
- Comprehensive test suite: bulletproof validation for all 19 MCP methods, sabotage-resistant error detection, WebSocket protocol validation

</details>

<details>
<summary><strong>September 15th – September 18th, 2025: Production Stabilization & Registry Preparation (v2.2.5)</strong></summary>

- Configured PyPI trusted publishing, Docker Hub support, and MCP Registry listing preparation; enabled `pip install marm-mcp-server` and `docker pull lyellr88/marm-mcp-server`
- Migrated docs from hardcoded lists to auto-loading modularized system with context-type classifier; essential-only loading (PROTOCOL.md + README.md) reduces token bloat
- Split large handbooks into 6 focused files (3 MCP, 3 main system)
- Eliminated legacy `MARMcp-beta` folder; validated all paths post-refactor
- Multi-AI validation (Claude, Qwen, Gemini, Comet) for change verification across transition

</details>

---

<details>
<summary><strong>August 20th – September 12th, 2025: Universal MCP Server Development (v2.2.4 Launch)</strong></summary>

- Production FastAPI server with 19 MCP tools: semantic search (sentence-transformers all-MiniLM-L6-v2), session/logging/notebook management, workflow tools
- Docker containerization with multi-stage builds; SQLite WAL mode and connection pooling; rate limiting and IP-based protection
- Multi-agent development workflow: Claude (architecture), Gemini (validation), Qwen (research), ChatGPT (testing)
- Claude Code, Qwen CLI, Gemini CLI integration; cross-AI memory sharing via unified knowledge base

</details>

<details>
<summary><strong>August 6-18, 2025: MARM Protocol Evolution to MCP Server (v2.0.0 MCP Launch) </strong></summary>

- 74-test suite across 4 modules (Voice, UI, State/Session, Commands, Security) with GitHub Actions CI and 42% coverage
- Migrated from Gemini to Llama 4 Maverick (400B params, 17B active × 128 experts): 95% cost reduction, 10M token context
- Protocol v1.5 → v2.0: "MARM IS memory incarnate" identity, 💭 Thinking Trail format, command modernization (/contextual reply→/deep dive, /compile→/summary, enhanced notebook commands)
- Complete UI modernization: glassmorphism effects, card-style messages, command menu redesign (sidebar→contextual popup), HTML/JS separation
- XSS protection system (3 sanitization levels), centralized storage.js, immutable state management with defensive copies
- New: file upload button (📎) supporting 15+ file types with auto language detection; MARM protocol toggle (🧠) for structured/free mode switching
- Fixed critical memory loss on mid-conversation activation; session persistence across toggle; eliminated 60+ duplicate code lines; TTS cancellation fix

</details>

---

## MARM Protocol Changelog — v1 (Archived)

<details>
<summary><strong>August 5th, 2025: Readme Restructure (v1.9.0)</strong></summary>

### Added

- README-2.md: complete restructure for professional presentation
- Enhanced PROTOCOL.md: complete copy-paste prompt with technical specs

### Changed

- Documentation hierarchy with clear separation of concerns
- Professional/research positioning (replacing chatbot-focused language)

### Removed

- Redundant content and overwhelming detail moved to dedicated files
- Chatbot-focused language replaced with framework positioning

</details>

---

<details>
<summary><strong>July 31st, 2025: Documentation Overhaul & Local Setup (v1.8.0)</strong></summary>

### Added

- SETUP.md: in-depth local download and installation guide
- config.js: AI provider configuration for universal API support
- universalAIHelper.js: universal AI provider support
- New screenshots of webchat interface in README

### Changed

- README updated for v1.5 with screenshots, removed "What's New with MARM", added local quick-setup section
- All documentation now reflects v1.5 feature set; clearer quick start, setup, and troubleshooting

</details>

<details>
<summary><strong>July 28th-30th, 2025: FAB System & UI Modernization (v1.6.0)</strong></summary>

### Added

- Floating Action Button (FAB) system: expandable circular button with staggered animations; four actions (Dark Mode, Saved Chats, New Chat, Token Counter); auto-close on outside click; mobile-first responsive
- ChatGPT-style code blocks with custom headers, copy buttons, dark mode, and language detection
- Dynamic chats menu with auto-close on delete-all
- Safety/performance: 30-entry/30KB notebook limit, 300ms rate limiting, 15s connection timeout, ActiveControllers tracking, page-unload cleanup

### Changed

- Mobile-first architecture: replaced individual floating buttons with unified FAB; improved spacing between Quick Commands, Chat, and FAB
- Extended chat window width, adjusted input field, balanced margins, improved header spacing
- Enhanced dark mode with better contrast, transparency, and readability across all components
- GitHub deployment sync: gh-index.html updated to match local dev

### Fixed

- FAB functionality on Render deployment, circular button styling, menu auto-close behavior, input/button overlap, visual balance

### Removed

- Individual floating buttons (token-counter, newChat, chats, darkMode), duplicate FAB structure, deprecated mobile hiding rules, old button setup functions

</details>

<details>
<summary><strong>July 22nd-24th, 2025: Chatbot Live Launch & UI Enhancements (v1.5.0)</strong></summary>

### Added

- Background images: light mode (`images-bg.png`) and dark mode (`images-dark-bg.png`) with dynamic theme switching
- Live MARM chatbot on Render with API proxying, full backend support, GitHub integration
- Improved Gemini API proxy error messages, clearer frontend error handling, user-friendly error feedback

### Changed

- Session management: UI logic moved to dedicated `sessionUI.js` module for better separation of concerns
- Codebase cleanup: replaced excessive inline comments with section headers, reduced bloat
- Deployment: switched from static site to Node.js web service with API proxying

### Fixed

- Session persistence across refreshes, error handling for missing docs, dark mode toggle, mobile responsive issues, background image loading

### Removed

- Excessive inline comments and code bloat, global function pollution, redundant session code, unused deployment configs

</details>

<details>
<summary><strong>July 17th-21st, 2025: Major Refactor & Feature Release (v1.4.0)</strong></summary>

### Added

- Session persistence: dual-storage strategy, survives refresh, automatic recovery, smart pruning at 5KB, 30-day expiry
- Save/Load Chat: save with custom title, saved chats browser with dropdown, delete with confirmation, timestamps
- New UI: "New Chat" and "Saved Chats" buttons, revamped help modal with gradient header and grid layout, Markdown doc viewer with loading states and error handling
- UI improvements: zoom-responsive `rem` positioning, dark mode across all new components, enhanced hover states and animations, icon-based nav, persistent collapsible command menu

### Changed

- Monolithic → modular: 900+ line `chatbot.js` split into 6 focused modules (`core.js`, `ui.js`, `voice.js`, `commands.js`, `state.js` + logic modules); barrel pattern imports; each <300 lines
- CSS: single `style.css` split into 6 modular files with custom properties, responsive patterns, accessibility
- State management: centralized with validation, persistence, safe immutable updates; response formatting instructions actively used
- Performance: ~30% less memory, no circular dependencies, no global functions, lazy-loading capability

### Fixed

- Voice synthesis scoping, command menu state persistence, input validation/sanitization, error handling, dark mode consistency, response formatting on all bot messages

### Removed

- 12 global `window.*` functions, circular dependencies, duplicate state code, inline event handlers

</details>

<details>
<summary><strong>July 11th-16th, 2025: Full System Refactor (Prototype to Beta) (v1.3.0)</strong></summary>

### Added

- New UI features: dynamic collapsible command menu, animated loading indicator, hover "Copy" buttons on every message, full dark mode
- Enhanced logic/context: full v1.4 command support (including `/start` and `/refresh`), `--fields` filter for `/compile`, full `/notebook` context on every turn, keyword-aware document searching

### Changed

- Hybrid command model: most commands trigger AI-generated natural language acknowledgments instead of static text
- Markdown rendering: bot responses now use `marked.js` for rich formatting
- Protocol alignment: replaced auto-activation with manual `/start marm` flow; rewrote `getSessionContext` for comprehensive per-turn context
- Command syntax: updated `/log` and `/notebook` parsing to v1.4 syntax

### Removed

- Old rigid command logic and hardcoded response strings, automatic activation flow, legacy `config.js`

</details>

<details>
<summary><strong>July 14th, 2025: Protocol Refinement & Handbook Restructure (v1.2.0)</strong></summary>

### Added

- `/refresh marm` command to recenter AI mid-session (recommended every 8-10 turns)
- `/notebook` subcommands: `key:[name]`, `get:[name]`, `show:` for enhanced data management
- "Your Objective" and "Safe Guard Check" sections for strict MARM identity and self-verification
- "What's New in v1.4 (Upgrading from v1.3)" section in README
- Star and fork badges at README top

### Changed

- `/log` split into `/log session:[name]` and `/log entry [Date | User | Intent | Outcome]` for precision
- Clarified manual-only processes; removed ambiguous automation references
- HANDBOOK.md restructured into concise 4-part professional format

### Removed

- Automated workflow references implying non-manual AI actions, redundant content from HANDBOOK.md

</details>

---

<details>
<summary><strong>June 21st-23rd, 2025: Protocol Expansion (v1.0.3)</strong></summary>

### Added

- `/notebook` command to save trusted user-provided data (AI prioritizes notebook over trained assumptions)
- Passive reentry prompts to resume, archive, or reset context on return
- Error handling for invalid `/log` entries with date autofill suggestions
- `/compile --fields=` filter for focused summaries
- "What's New in v1.3" section in HANDBOOK.md with usage guide
- Inline user guide for `/notebook` under collapsible alert block
- "Key Info and Limitations" dropdown (moved from protocol body)

### Changed

- "What MARM Solves" and "Why It Exists" sections updated for v1.3 behavior
- Activation response now includes summary and Quick Start command list
- Examples revised for clarity and real-world use
- README: reordered sections (What → Why → How), merged "Problem" and "Use Cases," simplified Quick Start, moved auxiliary content to CONTRIBUTING.md, added audio walkthrough link

### Removed

- Key info and limitations from static protocol body (now in dropdown), redundant phrasing in command definitions and legacy guardrail notes

</details>

<details>
<summary><strong>June 18th-20th, 2025: Externalization & Visibility (v1.0.2)</strong></summary>

### Added

- AI-narrated 15-minute audio walkthrough embedded in README
- User Feedback section (collapsible, with real screenshots)
- Featured on Google badge in README header
- CONTRIBUTING.md and Recognition Framework
- Multi-tier GitHub Discussions and onboarding entry points

### Changed

- README shifted to narrative onboarding: "What → Why → How → Proof" sequence; replaced "Use Cases" with community-backed examples; light marketing layer added

</details>

<details>
<summary><strong>June 14th-17th, 2025: Documentation Expansion & Restructuring (v1.0.1)</strong></summary>

### Added

- HANDBOOK.md: full command reference and usage guide with collapsible Beginner/Advanced/Examples/Quick Reference sections
- "Why Manual Steps Matter" rationale and expanded Limitations section
- Slash-style command formatting: `/start marm`, `/log [SessionName]`, `/guarded reply`, `/show reasoning`, `/compile [SessionName] --summary`

### Changed

- README clarified and reorganized to align with handbook; structured into Beginner/Intermediate/Advanced tiers; emphasis on manual workflows and session recap cadence

### Removed

- Embedded command list from README, "Back to top" anchors

</details>

<details>
<summary><strong>June 9th-13th, 2025: Initial Protocol Unification (Launch) (v1.0.0)</strong></summary>

### Added

- `/compile` command for one-line-per-entry summaries
- Automatic reseed block generation for restoring context in new threads
- Log schema enforcement: `[YYYY-MM-DD | User | Intent | Outcome]`
- Error handling for malformed log entries with date autofill
- `/show reasoning` command to reveal AI logic path
- Manual Steps Justification section in HANDBOOK.md
- Consolidated Examples section with real use cases for all major commands
- Session management guidance: recap every 8-10 turns using `/compile`

### Changed

- Unified session tools into default protocol behavior
- README restructured: Quick Start moved above initiation, Core Features moved to HANDBOOK.md, Acknowledgment behavior clarified
- Protocol one-liner updated to reflect unified design

### Removed

- Legacy modular language and optional tool references
- Confidence flag/scoring feature from all protocol outputs
- All mentions of auto-save or speculative memory behavior

</details>
