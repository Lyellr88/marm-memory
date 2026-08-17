# Upstream issue draft: cross_service reaches the client route node and stops

**Repo**: DeusData/codebase-memory-mcp
**Versions**: fails identically on 0.9.0 and 0.10.5 (Windows 11, `moderate` index mode)
**Ready to file.** The dead end is visible in 0.10.5's own output. The minimal reproduction covers only the server half, and that limitation is stated below rather than hidden.

---

## Title

`trace_path --mode cross_service` reaches the client's `__route__ANY__` node and stops: client and server route nodes are keyed differently and never join

## Summary

A TypeScript client calling an HTTP endpoint and the Python handler that serves it are both indexed, and the graph never connects them. The trace is not failing to find the client side. It reaches a client route node at hop 1 and stops there, because that node is keyed with method `ANY` while the server's is keyed with the concrete verb.

`--include-evidence` in 0.10.5 makes this legible: the route node comes back with an empty strategy and an empty confidence, unlike every other hop in the same response.

## Evidence

`trace_path --function-name getMemory --mode cross_service --depth 4 --include-evidence true`, on a 4,100-node project containing a FastAPI server and a TypeScript client:

```
function: getMemory
direction: both
mode: cross_service
callees_total: 4
callees: 4  (rows: name hop strategy confidence; qn = group prefix + "." + name)
  __route__ANY__/memories/{} 1 - -
<project>.marm-console.src.lib.marm-api:
  MarmApiError 2 heuristic 0.90
  buildQuery  2 lsp       0.95
  request     1 heuristic 0.90
callers_total: 0
```

The route node is reached. Three sibling hops in the same trace resolve with a strategy and a confidence; the route node has neither. Traversal continues sideways into other client functions and never crosses to Python.

The expected continuation is `get_memory`, the FastAPI handler for `GET /api/memories/{memory_id}`, which is indexed in the same project and carries a `HANDLES` edge.

## The key difference

Both sides exist in the store under different qualified names:

| Side | Qualified name |
|---|---|
| Server declaration (FastAPI `@router.get`) | `__route__GET__/api/memories/{}` |
| Client call (TypeScript, via a `request()` wrapper) | `__route__ANY__/memories/{}` |

Two differences, in the order we think they matter:

1. **Method.** The client route records `ANY`. If traversal matches route keys exactly, `ANY` can never match a concrete `GET`/`POST`/`PUT`/`DELETE`. `/api/logs` appears three times in one store as `__route__GET__`, `__route__DELETE__` and `__route__ANY__`, with every `HANDLES` edge on the first two and every `HTTP_CALLS` edge on the third. The two sets do not intersect anywhere in the project: of 149 `Route` nodes, 73 carry `HANDLES` and 33 carry `HTTP_CALLS`, with zero overlap.
2. **Base path.** The client's configured baseURL strips the prefix, so it emits `/memories/{}` against the server's `/api/memories/{}`.

Parameter shape is not implicated. The client's `:id` and the server's `{memory_id}` both normalize to `{}`.

## Reproduction

The behaviour above is from a real project. It reproduces by indexing any repository that contains a FastAPI server and a TypeScript client which calls it through a shared request wrapper, then running the `trace_path` command above and inspecting `SELECT qualified_name FROM nodes WHERE label='Route'`.

A minimal reproduction is available as `scripts/benchmarking/accuracy/code-graph/repro_routes.py` in https://github.com/Lyellr88/marm-memory, but **it only reproduces half the problem, and we would rather say so than overstate it.** With nine lines of FastAPI and eight of TypeScript, only the server's route node is created:

```
## Route node keys
  __route__GET__/api/memories/{}
```

No client route node, no `HTTP_CALLS` edge, so there is nothing to mismatch. Tried with an interpolated template URL, with literal path strings, and with `package.json` plus `tsconfig.json` present. Same result each time.

In the real project the client nodes **are** created, 33 of them, and that client calls through a shared `request()` helper rather than `fetch` directly. So detection appears to require a narrower or different shape than a bare `fetch` call, which is a second question worth answering:

**What client call shape is recognised as an HTTP call?** A direct `fetch("/api/memories/:id", { method: "GET" })` in a `.ts` file inside a project with `tsconfig.json` produced no client route node at all.

## Impact

Silent and confidently wrong. `cross_service` is documented as following HTTP boundaries for impact analysis, and it returns an empty result rather than an error, so a consumer cannot distinguish "nothing calls this endpoint" from "the two halves were never joined". Anything asking "what breaks if I change this endpoint" gets an answer that looks complete and is empty.

0.10.5 improves this materially without fixing it: the empty strategy and confidence on the route node are now a signal a careful consumer can read. A consumer that only reads names still cannot tell.

## Suggested direction

Recover the HTTP method at the client call site wherever it is statically visible, a `method:` literal or the verb in an axios/fetch wrapper, and fall back to matching any method only when it genuinely is not determinable. Matching an `ANY` client key against concrete server verbs would also work and is probably cheaper than method recovery.

Base-path normalization is the harder half, since the prefix lives in configuration rather than at the call site, and matching on a path suffix may be more robust than trying to resolve the baseURL.

Independently of either: emitting a resolution strategy for route hops the way other hops already get one would let a consumer see that the join was attempted and failed.
