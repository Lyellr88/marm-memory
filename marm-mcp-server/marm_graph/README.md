# MARM graph

`marm_graph` is MARM's boundary around the code graph engine. It starts and talks to the pinned `codebase-memory-mcp` process, translates its data into MARM's contracts, and keeps graph failures separate from core memory operations.

MARM has two related but separate graph systems:

- The concept graph extracts people, concepts, decisions, patterns, and relationships from stored memories. Its data lives in MARM's concept database.
- The code graph indexes a repository and maps files, symbols, imports, calls, and impact paths. The external engine owns its graph store.

They are intentionally separate. A concept can link to code when MARM has evidence for the link, but code indexing never writes into the concept database just to make a visual fuller.

## What this package owns

- The supervised code graph client in `core/cbm_client.py`.
- AI-facing routing and response shaping in `core/tool_router.py`.
- Console-only code graph endpoints in `endpoints/graph_ui.py`.
- HTTP and STDIO registration for the five code graph tools.

The public code graph tools are:

- `marm_graph_index` indexes a repository and controls automatic re-indexing.
- `marm_code_lookup` finds symbols and relevant source.
- `marm_graph_trace` follows call paths.
- `marm_graph_architecture` returns an architecture summary.
- `marm_graph_impact` estimates what a change may affect.

The engine starts lazily. If it is unavailable, graph operations return a bounded error response and memory storage and recall continue to work.

## Automatic indexing

After the first successful index, the code graph worker checks registered repositories in the background. It uses a git signature when one is available, re-indexes after a commit, and checks dirty repositories every cycle. The worker uses its own leased database lock so HTTP and STDIO cannot index the same repository at once.

This work must not block a memory write, recall, or server startup.

## Console graph surfaces

The Console presents the two graph systems together, but each page has a different job.

### Knowledge Graph: Explorer

Explorer is for navigating the concept graph. Choose all knowledge, one project, or one session; search for an entity; then inspect its neighborhood and source memories. The full atlas is useful for orientation, while a focused neighborhood is usually the better way to understand a decision or topic.

The atlas keeps relationship lines hidden until a node is hovered or selected. This avoids drawing an unreadable spiderweb for large graphs while keeping the graph's topology available for layout and tracing.

### Knowledge Graph: Potential Duplicates

Potential Duplicates finds similar concept names in the concept graph. Review the source memories before changing anything. You can merge two concepts, remove an unwanted concept, or mark the pair as distinct so future builds keep them separate.

### Indexed Projects

Indexed Projects is the code graph surface. It shows repositories known to the engine and provides the starting point for code lookup, architecture, tracing, and change impact work. An empty concept graph does not prevent a repository from being indexed or explored here.

### Build Concepts

Build Concepts is a concept extraction job, not a replacement for the graph. It reads stored memories, produces entities and relationships, and records progress in the Console. Rebuilding adds or refreshes concept-graph knowledge from memory content; it does not re-index source code.

## Working with the graphs

A useful sequence for a project is:

1. Index the repository once so code tools can locate files and symbols.
2. Let agents store decisions, findings, and implementation context as memories.
3. Build concepts from those memories.
4. Use Explorer to investigate a topic and check source provenance before treating a relationship as fact.
5. Use code lookup, tracing, and impact tools when the question becomes "where in the repository does this matter?"

## Current boundaries

The concept graph is evidence-backed but not an authoritative source of truth. Extraction can produce broad or overlapping concepts, which is why duplicate review and provenance exist.

The code graph can map a repository without any stored memories. Concept-to-code links only appear when MARM can support that connection. Do not fabricate cross-graph links for visual completeness.

## Roadmap

- Show why two concepts are related, including the specific relationship evidence and source memories.
- Select two nodes and show the shortest meaningful path between them.
- Add a time and change view for concepts and relationships created after a build or session.
- Add an audit trail from a compacted memory, through its summary, back to the original memories.
- Populate and expose code links so a decision or concept can point to the files and symbols it affects. This makes the graph useful for refactors rather than only for context discovery.

## Development notes

Keep the code graph fail-open from the perspective of core memory behavior. Do not share its database connections with the memory or concept databases. Changes to graph tools must preserve HTTP and STDIO parity and keep the public tool list in sync with the project-wide tool inventory.
