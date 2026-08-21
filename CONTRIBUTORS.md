# MARM Contributors

Thank you to everyone helping push local-first, persistent AI memory forward.

## Core Maintainers

- **Ryan Lyell** ([@lyellr88](https://github.com/lyellr88)) — Architecture & Core Development

## Code Contributors

- **OI-OS** ([@OI-OS](https://github.com/OI-OS)) — Added the first STDIO transport implementation so MARM could run in process-managed MCP clients without requiring an HTTP server. The PR introduced a separate STDIO entrypoint, transport-specific requirements, shared-core tool wiring, response-size handling, and setup documentation while keeping the existing HTTP path intact ([#20](https://github.com/Lyellr88/marm-memory/pull/20)).
- **sarvesh1327** ([@sarvesh1327](https://github.com/sarvesh1327)) — Fixed runtime preset handling so an explicit `COMPACTION_TRIGGER_COUNT` environment override is preserved instead of being clobbered by default/swarm/trusted presets. Added regression coverage for operator/Docker tuning paths around compaction trigger configuration ([#43](https://github.com/Lyellr88/marm-memory/pull/43)).
- **zza-830** ([@zza-830](https://github.com/zza-830)) — Hardened configuration parsing with bounds checks and clamping warnings across server ports, rate limits, queue sizes, recall limits, compaction settings, and search weights. Also added `MARM_RECALL_DEBUG` observability so recall lane selection, fallback behavior, and candidate breakdowns can be inspected safely through stderr without adding new MCP tools ([#54](https://github.com/Lyellr88/marm-memory/pull/54)).
- **Vaishnavi Desai** ([@vaishnavidesai09](https://github.com/vaishnavidesai09)) — Added the exact retrieval lane for code, config, command, and API-contract queries. The work introduced syntax-heavy query detection, the `exact_mode` control surface, deterministic FTS/BM25 recall with LIKE fallback, full HTTP/STDIO/service/core parameter wiring, project/platform scoping in exact recall, and regression coverage for routing, ranking, fallback behavior, and response compatibility ([#71](https://github.com/Lyellr88/marm-memory/pull/71)).
- **Muneeb Ahmad** ([@Mxneeb](https://github.com/Mxneeb)) — Proposed replacing min-max fusion with Reciprocal Rank Fusion on the hybrid recall path, with a complete implementation and a documented mathematical rationale ([#112](https://github.com/Lyellr88/marm-memory/pull/112)). The change was not merged, but the implementation became the reference for a controlled bake-off: a weighted RRF variant preserving MARM's shipped lexical weight, so fusion was the only variable. RRF measured 6.8-7.3pp below min-max across all five LoCoMo categories, which settled a question that had been open on reasoning alone and produced the fusion decision record in `docs/current/`. The experiment also corrected MARM's estimate of its own benchmark noise from ~0.1pp to 0.56pp, a methodology fix that outlives the experiment. Separately reported a real consolidation defect, fixed in v2.41.0 ([#113](https://github.com/Lyellr88/marm-memory/issues/113)): `CONSOLIDATION_THRESHOLD` is documented as a cosine threshold but was compared against a blended ranking score, which proved to be live under min-max as well, not introduced by the RRF proposal. Also surfaced the chunk-count bias in `_score_chunk_aware`'s max-over-chunks pooling, since measured and confirmed, and independently identified the recall risk the FTS candidate filter carries for low-token-overlap paraphrases.

## Test & Documentation Contributors

- **Aditya** ([@adity982](https://github.com/adity982)) — Made the zero-temporal-weight regression test verify what it claimed. The old assertion only compared the two candidates' positions when the second one happened to surface, so it could pass without ever exercising the ordering relationship it described. The test now stubs the lexical lane to return both candidates with fixed scores, pins `HYBRID_SEARCH_TEXT_WEIGHT`, and asserts the exact result order ([#124](https://github.com/Lyellr88/marm-memory/pull/124)). Test-only, with no change to production behavior.
- **tomatotomata** ([@tomatotomata](https://github.com/tomatotomata)) — Replaced a stale version-history and internal audit block in the compaction endpoint's module docstring with the lifecycle the code actually implements: pending candidates, staged review, then apply or discard, noting that final writes go through the single-writer queue while staging stays per-candidate ([#126](https://github.com/Lyellr88/marm-memory/pull/126)). Documentation only.

## Security Acknowledgments

- **Responsible security researcher** — Privately disclosed a network-exposed authentication boundary issue affecting earlier Docker/HTTP deployment guidance, helping improve MARM's safe deployment defaults and authentication posture. Public attribution can be updated if the reporter wants a specific name or profile listed.

---

Want to get your name on this list? See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.
