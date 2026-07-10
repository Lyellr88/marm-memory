# MARM Contributors

Thank you to everyone helping push local-first, persistent AI memory forward.

## Core Maintainers

- **Ryan Lyell** ([@lyellr88](https://github.com/lyellr88)) — Architecture & Core Development

## Code Contributors

- **OI-OS** ([@OI-OS](https://github.com/OI-OS)) — Added the first STDIO transport implementation so MARM could run in process-managed MCP clients without requiring an HTTP server. The PR introduced a separate STDIO entrypoint, transport-specific requirements, shared-core tool wiring, response-size handling, and setup documentation while keeping the existing HTTP path intact ([#20](https://github.com/Lyellr88/marm-memory/pull/20)).
- **sarvesh1327** ([@sarvesh1327](https://github.com/sarvesh1327)) — Fixed runtime preset handling so an explicit `COMPACTION_TRIGGER_COUNT` environment override is preserved instead of being clobbered by default/swarm/trusted presets. Added regression coverage for operator/Docker tuning paths around compaction trigger configuration ([#43](https://github.com/Lyellr88/marm-memory/pull/43)).
- **zza-830** ([@zza-830](https://github.com/zza-830)) — Hardened configuration parsing with bounds checks and clamping warnings across server ports, rate limits, queue sizes, recall limits, compaction settings, and search weights. Also added `MARM_RECALL_DEBUG` observability so recall lane selection, fallback behavior, and candidate breakdowns can be inspected safely through stderr without adding new MCP tools ([#54](https://github.com/Lyellr88/marm-memory/pull/54)).
- **Vaishnavi Desai** ([@vaishnavidesai09](https://github.com/vaishnavidesai09)) — Added the exact retrieval lane for code, config, command, and API-contract queries. The work introduced syntax-heavy query detection, the `exact_mode` control surface, deterministic FTS/BM25 recall with LIKE fallback, full HTTP/STDIO/service/core parameter wiring, project/platform scoping in exact recall, and regression coverage for routing, ranking, fallback behavior, and response compatibility ([#71](https://github.com/Lyellr88/marm-memory/pull/71)).

## Security Acknowledgments

- **Responsible security researcher** — Privately disclosed a network-exposed authentication boundary issue affecting earlier Docker/HTTP deployment guidance, helping improve MARM's safe deployment defaults and authentication posture. Public attribution can be updated if the reporter wants a specific name or profile listed.

---

Want to get your name on this list? See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.
