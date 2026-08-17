# RETIRED, never filed: import-resolved call edges vanish above a project-size threshold

**Retired 2026-08-16.** Fixed upstream in engine 0.10.5 before this draft was sent. Kept as a record of the investigation and as the reproduction's specification, not as a pending action.

Verified fixed: the sweep in `scripts/benchmarking/accuracy/code-graph/repro_awaited.py` records the edge at every size and layout on 0.10.5, where 0.9.0 lost it from 565 nodes upward when nested. On MARM itself, `notebook_dispatch` resolves both production callers from the repository root with `strategy=lsp, confidence=0.97`.

Two things worth carrying forward:

The behaviour described below was also reported by someone else as upstream issue #1237 on 2026-07-23, against a 240k-node Django monorepo, labelled `priority/high`. Their report predates this draft by three weeks. Searching the tracker before building a reproduction would have cost minutes and saved the whole exercise.

The draft was written against a pin six minor versions behind the current release, and nothing in it was wrong except that it no longer applied. Check the dependency's latest version before writing down its behaviour.

---

**Repo**: DeusData/codebase-memory-mcp
**Version measured**: 0.9.0 (Windows 11, `moderate` index mode). Fixed in 0.10.5.

---

## Title

CALLS edges for imported functions are silently dropped above roughly 450 nodes, and a nested package root widens it to absolute imports

## Summary

A call to a function brought in by an import is recorded as a `CALLS` edge in a small project and silently dropped in a larger one. The call site is byte-identical between runs; only the number of unrelated modules changes.

There is one threshold, between 432 and 476 nodes, and two failure classes on the far side of it:

- Relative imports (`from .targets import target`) lose their call edges regardless of where the package sits.
- Absolute imports (`from pkg.targets import target`) lose theirs as well once the package root is one directory below the repository root, which is the layout of any project using `src/` or a packaging subdirectory.

Imports written inside a function body survive every configuration we tested.

## Reproduction

Generator: `scripts/benchmarking/accuracy/code-graph/repro_awaited.py` in https://github.com/Lyellr88/marm-memory. It writes a package, indexes it through the CLI, and reports which `CALLS` edges exist. `--filler N` adds N unrelated modules that never reference the probes. `--nest DIR` puts the package under `DIR` instead of at the repository root.

```
python repro_awaited.py --filler 40            # 432 nodes, flat
python repro_awaited.py --filler 45            # 476 nodes, flat
python repro_awaited.py --filler 45 --nest src # 477 nodes, nested
```

Minimal shape of one probe:

```python
# pkg/targets.py
async def target_absolute_top(*args, **kwargs):
    return 1


# pkg/imp_absolute_top.py
from pkg.targets import target_absolute_top


async def call_absolute_top():
    return await target_absolute_top(action=1)
```

Index, then query:

```
codebase-memory-mcp cli index_repository --repo-path <repo> --mode moderate
```

```sql
SELECT s.name, t.name FROM edges e
JOIN nodes s ON s.id = e.source_id
JOIN nodes t ON t.id = e.target_id
WHERE e.type = 'CALLS' AND s.name = 'call_absolute_top';
```

## Results

Eighteen call shapes were tested at each size: sync and awaited, assigned and returned, positional and keyword arguments, single-line and multi-line, inside `try`, under one and two decorators, and imported relatively, absolutely, after module-level code, and inside a function body.

| Nodes | Layout | Relative | Absolute | Function-body |
|---|---|---|---|---|
| 69 | flat | recorded | recorded | recorded |
| 70 | nested | recorded | recorded | recorded |
| 432 | nested | recorded | recorded | recorded |
| 476 | flat | **dropped** | recorded | recorded |
| 477 | nested | **dropped** | **dropped** | recorded |
| 3,671 | flat | **dropped** | recorded | recorded |
| 3,672 | nested | **dropped** | **dropped** | recorded |

A cliff, not a gradient. The 476-node flat run and the 477-node nested run differ only by one directory level, so the layout effect is isolated. Using a hyphenated nesting directory, which Python itself could not import as a package, changes nothing, so the trigger is the extra level rather than the name.

Call shape makes no difference at any size: sync and awaited probes fail together, which rules out `await` and coroutines.

## Impact

Silent, which is the part that matters. The edges are absent rather than wrong, so `trace_path --direction inbound` returns an empty caller list for a function that is genuinely called. A consumer cannot distinguish "nothing calls this" from "the import was not resolved", and an automated consumer will act on the first reading.

The threshold is low enough that most real repositories are past it, and the nested-root case means a conventional `src/` layout is affected from a few hundred nodes upward. We hit this on a 4,058-node Python project whose package lives at `<repo>/marm-mcp-server/marm_mcp_server/`: hand-verified callers of a function returned as zero callers.

## Guess at the cause

The small-project behaviour looks like a name-uniqueness fallback: with few symbols, an unresolved import can still be matched by target name. Past some candidate budget or symbol count that fallback stops applying, and whatever the import resolver could not resolve is then lost outright rather than degraded.

That would explain the pattern if the resolver never resolves `.`/`..` against the importing module's own package, and infers the source root for absolute imports only when it equals the repository root. Function-body imports surviving suggests they take a different path that does resolve. If that is right, resolving relative imports against the importing package, and inferring source roots from package markers rather than assuming the repository root, would fix both classes independently of size.

Independently of the cause, it would help a great deal if an unresolved import were recorded rather than discarded, so a consumer can tell a missing edge from a resolution failure.
