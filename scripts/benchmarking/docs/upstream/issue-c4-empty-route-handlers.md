# Upstream issue draft: get_architecture returns empty route handlers

**Repo**: DeusData/codebase-memory-mcp
**Versions**: fails identically on 0.9.0 and 0.10.5 (Windows 11, `moderate` index mode)
**Ready to file.** Output below is verbatim from a 24-node project built by `scripts/benchmarking/accuracy/code-graph/repro_routes.py`.

---

## Title

`get_architecture` returns `routes[].handler` empty for every route despite `HANDLES` edges existing in the store

## Summary

`get_architecture` returns a `routes` array shaped `{method, path, handler}`. The `handler` field is an empty string on every entry, including routes whose handler is recorded in the graph.

The information is present. In one repo the store holds **94 `HANDLES` edges** covering 92 distinct `Route` nodes, roughly 98% of the 94 routes declared in source. `get_architecture` reports **0 populated handlers out of the 20 routes it returns.**

## Reproduction

Any FastAPI project. Minimal:

```python
# server.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/memories/{memory_id}")
async def get_memory(memory_id: str):
    return {"id": memory_id}
```

```
codebase-memory-mcp cli index_repository --repo-path <repo> --mode moderate
codebase-memory-mcp cli get_architecture --project <project>
```

On 0.10.5 add `--aspects routes`, which prints the same routes as a `method path handler` table with `-` in the handler column.

**Observed**, on a project containing only the file above plus one TypeScript client:

```
# indexed: 24 nodes, 28 edges

## get_architecture routes[]
[
  {
    "method": "GET",
    "path": "/api/memories/{memory_id}",
    "handler": ""
  }
]

routes: 1   with non-empty handler: 0
```

**Expected**: `"handler": "get_memory"`, or the handler's qualified name.

The edge is in the store, queried from the same index:

```
## HANDLES edges actually in the store
  get_memory -> __route__GET__/api/memories/{}
HANDLES edges: 1
```

So one route, one `HANDLES` edge naming its handler, and `handler` returned empty.

## Impact

This is the only public way to ask which handler serves a route. `trace_path` has no mode that follows `HANDLES` (`calls` follows `CALLS`, `cross_service` follows `HTTP_CALLS` through routes), and symbol search returns routes and functions without any relation between them. So a consumer cannot answer "which code runs for this endpoint" through the tool surface, even though the graph knows.

Because the field is present and empty rather than absent, a consumer reading it concludes the handler is unknown rather than that the field is unimplemented.

## Secondary observation

`routes` appears to cap at 20 entries with no pagination or total count in the response, so a project with more routes cannot enumerate them. Still 20 on 0.10.5, where `trace_path` and `search_graph` gained `limit`/`cursor` pagination but `get_architecture` did not. Worth confirming whether the cap is intended; if so, a `total` field would at least let a caller detect truncation.
