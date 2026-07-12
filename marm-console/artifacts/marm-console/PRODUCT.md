# Product

## Register

product

## Users

Developers running marm-memory locally: solo builders and small teams whose AI agents read/write the memory store. They open the Console in a browser next to their terminal or IDE, usually mid-task, to inspect what their agents have remembered, review extracted knowledge, and perform safe maintenance (builds, duplicate review, future guarded writes). Ryan (founder) is user zero and works in it daily.

## Product Purpose

MARM Console is the standalone local control plane for marm-memory. It reads the same local SQLite stores the MCP server uses and gives humans what agents don't need: overview health, scoped memory browsing, the knowledge graph, and code-project intelligence. Success = a user can answer "what does my agent know, and is it healthy?" in under a minute, locally, with zero cloud dependency. It is a key differentiator against Mem0's flat local dashboard (which has no graph view).

## Brand Personality

Precise, calm, technical. "Network telemetry" aesthetic: deep navy/black surfaces, cyan primary, JetBrains Mono for data, Inter for UI. Conversational labels over jargon (per the repo-wide UI philosophy: ruthlessly cut technical terms, progressive disclosure via tooltips/panels, consistency over novelty).

## Anti-references

- Mem0/OpenMemory's flat list-only local dashboard: the graph is the differentiator, so it must not look like an afterthought.
- Neo4j Browser's raw-database feel: no query languages or DB jargon surfaced to users.
- Generic admin-template SaaS look (identical stat-card grids, gradient heroes).
- Over-decorated dashboards where color is decoration rather than meaning.

## Design Principles

- **The graph is the product's proof.** The knowledge view must look alive and information-dense (InfraNodus/Gephi energy), not like a debug tool.
- **Facelift, not brain surgery.** Preserve behavior when restyling; all features behave as they did.
- **Progressive disclosure.** Simple surface, depth in panels and tooltips. Details on demand, never all at once.
- **Color carries meaning only.** Entity type, state, selection. Never decorative.
- **Degrade cleanly.** Every view must be useful (and honest) when data hasn't been built yet or the MCP server is down.

## Accessibility & Inclusion

WCAG AA targets. Categorical graph colors are CVD-validated with labels and a legend as secondary encoding (never color alone). Reduced-motion users get static layouts (no forced physics animation dependence for meaning). Dark theme is the only theme for now (forced dark; matches ambient developer context).
