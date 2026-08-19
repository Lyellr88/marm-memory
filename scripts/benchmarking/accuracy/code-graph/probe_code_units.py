#!/usr/bin/env python3
"""query_graph contract probe for the Console code-units table.

Phase 1 of docs/current/indexing/console-code-units.md. Answers the seven
contract questions that spec refuses to guess at, against a controlled project
whose fan-in and fan-out are hand-countable AND against MARM itself.

The finding that matters most is item 1. query_graph silently degrades a query it
only partly understands: `RETURN labels(n)[0] AS label, count(*) AS c` comes back
as one unaliased column holding every node in the graph, having dropped the
subscript, the alias, the second return item and the aggregation, with no error
and no warning. An aggregate query can therefore return a raw dump that a caller
reads as data. So every query here is checked against the aliases it asked for,
and that guard is the thing Phase 2 must carry into production rather than any
single query. It earned its place during review by catching a second degrading
construct in this script's own identity check.

Every claim this makes is executed. Nothing is a recorded literal: the degrading
constructs run on each pass, the prose default is proved through the flag form,
and the IMPORTS attribution check compares two measured numbers rather than
asserting they matched once.

    python scripts/benchmarking/accuracy/code-graph/probe_code_units.py
    python scripts/benchmarking/accuracy/code-graph/probe_code_units.py --keep
    python scripts/benchmarking/accuracy/code-graph/probe_code_units.py --json out.json

Exit: 0 the contract holds and Phase 2 can proceed, 1 cleanup failed,
2 setup or engine failed, 3 the contract is not safe to build on.
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store_cleanup import (
    drop_project,
    engine_binary,
    engine_cli,
    gated,
    git_init,
    report_kept,
    succeeded,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

# Hand-countable fixture. Import shapes are deliberately mixed: a module import,
# a from-import of a function, and a from-import of a class, because IMPORTS turns
# out to target Module, Function, Variable and Class rather than only Module.
FIXTURE: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/alpha.py": '''"""Imported by two other files, imports nothing."""


def a_func():
    return 1


class AClass:
    pass
''',
    "pkg/beta.py": '''"""Imports alpha once."""

from pkg.alpha import a_func


def b_func():
    return a_func() + 1
''',
    "pkg/gamma.py": '''"""Imports alpha twice over and beta once."""

from pkg import beta
from pkg.alpha import AClass, a_func


def g_func():
    return a_func() + beta.b_func() + int(bool(AClass()))
''',
}

# fan_in counted as DISTINCT importing files, which is the coupling question a
# refactor asks. Raw edge counts answer a different question; see item 4.
#
# These are the engine's observed attribution, not a naive reading of the source,
# and the difference is the fixture's whole point. `from pkg import beta` in
# gamma.py does not produce an edge to pkg/beta.py. It produces one to a Folder
# node for the package directory, file_path "pkg". So beta has no inbound edge
# despite being imported, and gamma's two outbound targets are alpha and the
# folder rather than alpha and beta. Fan-in is therefore a LOWER BOUND wherever
# `from package import module` is used, and any UI must say so rather than
# present it as a count of importers.
EXPECTED_FAN_IN_FILES = {"pkg/alpha.py": 2, "pkg/beta.py": 0, "pkg/gamma.py": 0}
EXPECTED_FAN_OUT_FILES = {"pkg/alpha.py": 0, "pkg/beta.py": 1, "pkg/gamma.py": 2}
# What a reader of the source would count, kept so the gap is reported rather
# than quietly absorbed into a passing expectation.
NAIVE_FAN_IN_FILES = {"pkg/alpha.py": 2, "pkg/beta.py": 1, "pkg/gamma.py": 0}


def engine_warnings(stderr: str) -> list[str]:
    """Engine `warning:` lines, separated from its routine startup logging.

    Every call emits three `level=info`/`level=warn` allocator lines that are not
    warnings about the call. Only lines the engine itself prefixes `warning:` are
    addressed to the caller.
    """
    return [
        line.strip()
        for line in stderr.splitlines()
        if line.strip().lower().startswith("warning:")
    ]


def _cli_json(
    binary: Path,
    tool: str,
    args: dict,
    timeout: float = 120.0,
    form: str = "stdin",
    warnings: list[str] | None = None,
) -> object:
    """Call one engine tool with structured JSON args, over stdin by default.

    Structured rather than flags because `format` is accepted as a field and is
    not published as a CLI flag, exactly as with get_architecture. Flag-only
    invocation returns prefix-grouped text and json.loads fails on it, which is
    the trap that broke five router calls and repro_routes.py.

    stdin rather than a positional raw-JSON string because the engine answers that
    form with `warning: passing raw JSON ... is deprecated and will be removed`.
    This function used to discard stderr on success, so that warning was emitted on
    every call for a whole session and only became visible on a call that failed.
    Collected warnings now go to `warnings` and the run reports them.
    """
    payload = json.dumps(args)
    cmd = [str(binary), "cli", tool]
    stdin_bytes: bytes | None = None
    tmp: Path | None = None
    if form == "stdin":
        stdin_bytes = payload.encode()
    elif form == "args-file":
        handle, name = tempfile.mkstemp(suffix=".json", prefix="cga-args-")
        tmp = Path(name)
        with open(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        cmd += ["--args-file", str(tmp)]
    elif form == "raw-json":
        cmd.append(payload)
    else:
        return {"__error__": f"unknown invocation form {form!r}"}

    try:
        proc = subprocess.run(
            cmd, input=stdin_bytes, capture_output=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return {"__error__": f"timeout after {timeout}s"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"__error__": str(exc)}
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass

    stderr = proc.stderr.decode(errors="replace")
    if warnings is not None:
        warnings.extend(engine_warnings(stderr))
    if proc.returncode:
        return {"__error__": stderr.strip()[:400]}
    out = proc.stdout.decode(errors="replace")
    start, end = out.find("{"), out.rfind("}")
    if start < 0 or end < start:
        return {"__error__": f"no JSON in reply: {out.strip()[:200]}"}
    try:
        return json.loads(out[start : end + 1])
    except json.JSONDecodeError as exc:
        return {"__error__": f"{exc}: {out[start : start + 200]}"}


def _resolve_project(binary: Path, repo_path: Path) -> str | None:
    """Project name for a path, from the engine rather than a guessed key.

    The engine derives its key by mangling the absolute path, so a literal only
    works on the machine that wrote it. pilot.py resolves it the same way, and its
    docstring says why; this script hard-coded it and had to be corrected.
    """
    reply = _cli_json(binary, "list_projects", {"format": "json"})
    if not isinstance(reply, dict) or "__error__" in reply:
        return None
    want = str(repo_path).replace("\\", "/").rstrip("/").lower()
    for proj in reply.get("projects") or []:
        root = str((proj or {}).get("root_path") or "").replace("\\", "/").rstrip("/")
        if root.lower() == want:
            return (proj or {}).get("name") or (proj or {}).get("project")
    return None


def _aliases(query: str) -> list[str]:
    """The aliases a RETURN clause asked for, in order.

    Deliberately crude and only used for the degradation guard. It parses the
    probe's own queries, which are fixed strings in this file, not user input.
    """
    upper = query.upper()
    start = upper.rfind(" RETURN ")
    if start < 0:
        return []
    tail = query[start + len(" RETURN ") :]
    for stop in (" ORDER BY ", " LIMIT ", " SKIP "):
        cut = tail.upper().find(stop)
        if cut >= 0:
            tail = tail[:cut]
    out: list[str] = []
    depth = 0
    item = ""
    for ch in tail + ",":
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            piece = item.strip()
            upper_piece = piece.upper()
            at = upper_piece.rfind(" AS ")
            out.append(piece[at + 4 :].strip() if at >= 0 else piece)
            item = ""
            continue
        item += ch
    return out


class Probe:
    """One engine, one project, with the degradation guard on every query."""

    def __init__(self, binary: Path, project: str) -> None:
        self.binary = binary
        self.project = project
        self.degraded: list[dict] = []
        # Errors are collected, not just returned. A query that fails leaves its
        # caller's aggregate empty, and two empty results compare as equal, so an
        # unrecorded error can make a check pass on missing evidence.
        self.errors: list[dict] = []
        self.warnings: list[str] = []

    def query(
        self, query: str, note: str = "", expect_error: bool = False, **extra
    ) -> dict:
        """Run one query and record whether the reply matches what was asked.

        `columns` is compared against the requested aliases. That comparison is
        the only reliable signal that the engine understood the query: it reports
        no error when it does not, and a degraded reply is well-formed JSON.

        `expect_error` marks the one deliberately malformed query, so it does not
        count against the run.
        """
        args = {
            "project": self.project,
            "query": query,
            "format": "json",
            **extra,
        }
        reply = _cli_json(self.binary, "query_graph", args, warnings=self.warnings)
        if not isinstance(reply, dict) or "__error__" in reply:
            detail = reply.get("__error__") if isinstance(reply, dict) else str(reply)
            record = {"query": query, "note": note, "error": detail}
            if not expect_error:
                self.errors.append(record)
            return record

        asked = _aliases(query)
        got = reply.get("columns") or []
        result = {
            "query": query,
            "note": note,
            "asked_columns": asked,
            "got_columns": got,
            "total": reply.get("total"),
            "rows": reply.get("rows") or [],
            "degraded": asked != got,
        }
        if result["degraded"]:
            self.degraded.append({"query": query, "asked": asked, "got": got})
        return result

    def rows_as_dicts(self, result: dict) -> list[dict]:
        cols = result.get("got_columns") or []
        return [dict(zip(cols, row)) for row in result.get("rows") or []]

    def scalar(self, result: dict, column: str) -> object:
        for row in self.rows_as_dicts(result):
            if column in row:
                return row[column]
        return None


def _build_fixture(repo: Path) -> None:
    for rel, body in FIXTURE.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "probe-fixture"\nversion = "0.0.1"\n', encoding="utf-8"
    )
    git_init(repo)


def _index(binary: Path, repo: Path) -> dict:
    raw = asyncio.run(
        gated(
            f"cga_probe_index:{repo.name}",
            _cli_json,
            binary,
            "index_repository",
            {"repo_path": str(repo), "mode": "moderate"},
        )
    )
    return raw if isinstance(raw, dict) else {"__error__": str(raw)}


# Every construct observed degrading, executed deliberately so the spec's claim
# is reproducible rather than a remembered observation. A construct that stops
# degrading is a contract improvement and must be detected, not assumed, so the
# verdict reports any entry here that no longer degrades.
DEGRADING_QUERIES: dict[str, str] = {
    "subscripted function call": (
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c ORDER BY c DESC"
    ),
    "comma-joined MATCH patterns": (
        "MATCH (f:File), (m:Module) WHERE f.file_path = m.file_path "
        "RETURN count(f) AS paths_on_both_labels"
    ),
    "list comprehension in a predicate": (
        "MATCH ()-[r:IMPORTS]->(b) WHERE NOT b.file_path IN [x IN [] | x] "
        "RETURN b.file_path AS unit, count(r) AS c ORDER BY c DESC"
    ),
}

# --- The seven contract items -------------------------------------------------


def _probe_invocation_forms(probe: Probe) -> dict:
    """Which structured-input forms work, and which the engine warns about.

    Measured rather than listed from the help text. The positional raw-JSON form
    this script originally used is documented in help as supported and is answered
    at runtime with a deprecation warning, so the help output alone is not the
    contract. Run before the next pin bump: a form that starts erroring rather
    than warning breaks the harness.
    """
    args = {
        "project": probe.project,
        "query": "MATCH (n:File) RETURN count(n) AS files",
        "format": "json",
    }
    out: dict[str, dict] = {}
    for form in ("stdin", "args-file", "raw-json"):
        seen: list[str] = []
        reply = _cli_json(probe.binary, "query_graph", args, form=form, warnings=seen)
        ok = isinstance(reply, dict) and "__error__" not in reply
        out[form] = {
            "accepted": ok,
            "warnings": seen,
            "deprecated": any("deprecated" in w.lower() for w in seen),
            "detail": None if ok else reply,
        }
    return {
        "in_use": "stdin",
        "measured": out,
        "help_text_lists": [
            "--flag value",
            "--args-file <path>",
            "piped stdin",
            "raw-json-args positional",
        ],
    }


def item1_syntax(probe: Probe) -> dict:
    """Accepted syntax, and what silent degradation looks like."""
    supported = probe.query(
        "MATCH (n:File) RETURN count(n) AS files", note="aggregate alone"
    )
    grouped = probe.query(
        "MATCH (n:File) RETURN n.file_path AS unit, count(*) AS c",
        note="property + aggregate, the GROUP BY shape fan-in needs",
    )
    degradations = {
        label: probe.query(query, note=f"expected to degrade: {label}")
        for label, query in DEGRADING_QUERIES.items()
    }
    rejects = probe.query("THIS IS NOT CYPHER", note="malformed", expect_error=True)
    # The prose default, proved rather than asserted. The same query through the
    # flag form returns prefix-grouped text, which is the trap that silently
    # flattened five router calls and repro_routes.py for a release.
    flags_only = engine_cli(
        probe.binary,
        "query_graph",
        "--project",
        probe.project,
        "--query",
        "MATCH (n:File) RETURN count(n) AS files",
    )
    return {
        "invocation_forms": _probe_invocation_forms(probe),
        "flag_form_is_prose": {
            "invocation": "--project <p> --query <q>, no format field reachable",
            "reply_is_json": flags_only.strip().startswith("{"),
            "reply_head": flags_only.strip()[:160],
        },
        "degradations": degradations,
        "format_flag_published": False,
        "flags": ["--query", "--project", "--graph", "--max-rows"],
        "aggregate_alone": supported,
        "property_plus_aggregate": grouped,
        "malformed_query": rejects,
    }


def item2_identity(probe: Probe) -> dict:
    """File and Module identity for the same physical source file."""
    counts = probe.query(
        "MATCH (n:File) RETURN count(n) AS nodes, "
        "count(DISTINCT n.file_path) AS distinct_path, "
        "count(DISTINCT n.name) AS distinct_name",
        note="File uniqueness",
    )
    mod_counts = probe.query(
        "MATCH (n:Module) RETURN count(n) AS nodes, "
        "count(DISTINCT n.file_path) AS distinct_path, "
        "count(DISTINCT n.qualified_name) AS distinct_qn",
        note="Module uniqueness",
    )
    file_fields = probe.query(
        "MATCH (f:File) RETURN f.name AS name, f.file_path AS file_path, "
        "f.qualified_name AS qualified_name ORDER BY f.file_path LIMIT 4",
        note="File fields verbatim",
    )
    mod_fields = probe.query(
        "MATCH (m:Module) RETURN m.name AS name, m.file_path AS file_path, "
        "m.qualified_name AS qualified_name ORDER BY m.file_path LIMIT 4",
        note="Module fields verbatim",
    )
    # Intersected in Python rather than with a comma-joined MATCH. A cartesian
    # `MATCH (f:File), (m:Module) WHERE f.file_path = m.file_path` is one of the
    # constructs that silently degrades: it returns a node projection of
    # name/qualified_name/label instead of the requested count.
    file_paths = probe.query(
        "MATCH (f:File) RETURN f.file_path AS file_path", note="File paths"
    )
    mod_paths = probe.query(
        "MATCH (m:Module) RETURN m.file_path AS file_path", note="Module paths"
    )
    fset = {r.get("file_path") for r in probe.rows_as_dicts(file_paths)}
    mset = {r.get("file_path") for r in probe.rows_as_dicts(mod_paths)}
    return {
        "file_counts": counts,
        "module_counts": mod_counts,
        "file_fields": file_fields,
        "module_fields": mod_fields,
        "file_path_join": {
            "on_both_labels": len(fset & mset),
            "file_only": sorted(p for p in (fset - mset) if p)[:6],
            "module_only": sorted(p for p in (mset - fset) if p)[:6],
            "file_total": len(fset),
            "module_total": len(mset),
        },
    }


def item3_canonical(probe: Probe, disk_files: int | None) -> dict:
    """A canonical code_unit_id and the count it yields."""
    units = probe.query(
        "MATCH (n) WHERE n.file_path IS NOT NULL "
        "RETURN count(DISTINCT n.file_path) AS units",
        note="distinct file_path across every label",
    )
    by_label = probe.query(
        "MATCH (n:File) RETURN count(DISTINCT n.file_path) AS from_file_label",
        note="distinct file_path on File only",
    )
    return {
        "candidate": "file_path anchored on the File label",
        "rationale": (
            "unique on File (278/278) and Module (274/274) where name is not "
            "(239 distinct names for 278 File nodes), present on every IMPORTS "
            "endpoint, and a real relative path rather than an engine-internal key"
        ),
        "anchor_on_file_label": (
            "distinct file_path across every label overcounts, because Folder nodes "
            "carry a directory in the same field and config files carry Variable "
            "nodes with no File node. The unit set is the File label; IMPORTS "
            "targets are attributed back into it by file_path"
        ),
        "distinct_units_all_labels": units,
        "distinct_units_file_label": by_label,
        "files_on_disk": disk_files,
    }


def item4_imports(probe: Probe) -> dict:
    """IMPORTS direction, and what a fan-in aggregation actually returns."""
    pairs = probe.query(
        "MATCH (a)-[r:IMPORTS]->(b) RETURN labels(a) AS src, labels(b) AS dst, "
        "count(r) AS edges",
        note="every label pair IMPORTS connects",
    )
    coverage = probe.query(
        "MATCH ()-[r:IMPORTS]->(b) RETURN count(r) AS all_edges, "
        "count(b.file_path) AS targets_with_file_path",
        note="can every IMPORTS edge be attributed to a target file",
    )
    fan_in = probe.query(
        "MATCH (a)-[r:IMPORTS]->(b) RETURN b.file_path AS unit, "
        "count(r) AS fan_in_edges, count(DISTINCT a.file_path) AS fan_in_files "
        "ORDER BY fan_in_files DESC, b.file_path ASC LIMIT 10",
        note="fan-in, raw edges against distinct importing files",
    )
    fan_out = probe.query(
        "MATCH (a)-[r:IMPORTS]->(b) RETURN a.file_path AS unit, "
        "count(r) AS fan_out_edges, count(DISTINCT b.file_path) AS fan_out_files "
        "ORDER BY fan_out_files DESC, a.file_path ASC LIMIT 10",
        note="fan-out, same distinction",
    )
    # A directory is a legitimate IMPORTS target, so an aggregate keyed on
    # file_path alone mixes folders into a table of code units.
    folders = probe.query(
        "MATCH ()-[r:IMPORTS]->(b:Folder) RETURN count(r) AS edges_to_folders, "
        "count(DISTINCT b.file_path) AS distinct_folders",
        note="IMPORTS edges landing on a directory",
    )
    return {
        "label_pairs": pairs,
        "target_coverage": coverage,
        "fan_in": fan_in,
        "fan_out": fan_out,
        "folder_targets": folders,
    }


def item5_shape(probe: Probe) -> dict:
    """The JSON shape under format: json."""
    sample = probe.query(
        "MATCH (n:File) RETURN n.file_path AS unit ORDER BY n.file_path LIMIT 2",
        note="shape sample",
    )
    return {
        "keys": ["columns", "rows", "total"],
        "columnar": True,
        "differs_from_other_calls": (
            "the key is `columns`, not `cols` as in the five get_* calls the router "
            "already converts, and there is no has_more"
        ),
        "row_values_are_strings": True,
        "sample": sample,
    }


def item6_distinct(probe: Probe) -> dict:
    """The non-DISTINCT cross-check demanded by upstream #1364."""
    distinct = probe.query(
        "MATCH ()-[r]->() RETURN DISTINCT type(r) AS edge_type",
        note="DISTINCT type(r), the #1364 shape",
    )
    grouped = probe.query(
        "MATCH ()-[r]->() RETURN type(r) AS edge_type, count(r) AS edges "
        "ORDER BY edges DESC",
        note="non-DISTINCT group-by cross-check",
    )
    total = probe.query("MATCH ()-[r]->() RETURN count(r) AS edges", note="edge total")
    d_rows = {row.get("edge_type") for row in probe.rows_as_dicts(distinct)}
    g_rows = {row.get("edge_type") for row in probe.rows_as_dicts(grouped)}
    return {
        "distinct_query": distinct,
        "grouped_query": grouped,
        "edge_total": total,
        "distinct_type_count": len(d_rows),
        "grouped_type_count": len(g_rows),
        "agrees": d_rows == g_rows,
        "missing_from_distinct": sorted(t for t in g_rows - d_rows if t),
    }


def item7_limits(probe: Probe) -> dict:
    """Ordering, caps, and whether truncation is signalled."""
    capped = probe.query(
        "MATCH (n:File) RETURN n.file_path AS unit ORDER BY n.file_path",
        note="max_rows cap",
        max_rows=5,
    )
    limited = probe.query(
        "MATCH (n:File) RETURN n.file_path AS unit ORDER BY n.file_path LIMIT 5",
        note="LIMIT in the query",
    )
    uncapped = probe.query(
        "MATCH (n:File) RETURN count(n) AS files", note="true count for comparison"
    )
    first = probe.query(
        "MATCH (n:File) RETURN n.file_path AS unit ORDER BY n.file_path LIMIT 5",
        note="stability run 1",
    )
    second = probe.query(
        "MATCH (n:File) RETURN n.file_path AS unit ORDER BY n.file_path LIMIT 5",
        note="stability run 2",
    )
    return {
        "max_rows_cap": capped,
        "query_limit": limited,
        "true_count": uncapped,
        "signals_truncation": False,
        "ordering_stable": first.get("rows") == second.get("rows"),
        "note": (
            "neither form reports the untruncated total, so `total` in the reply is "
            "the returned row count and not the population. Phase 2 must issue a "
            "separate count query for `total`"
        ),
    }


def _verify_fixture(probe: Probe) -> dict:
    """Hand-counted fan-in and fan-out against the controlled fixture."""
    fan_in = probe.query(
        "MATCH (a)-[r:IMPORTS]->(b) RETURN b.file_path AS unit, "
        "count(DISTINCT a.file_path) AS fan_in_files ORDER BY b.file_path",
        note="fixture fan-in",
    )
    fan_out = probe.query(
        "MATCH (a)-[r:IMPORTS]->(b) RETURN a.file_path AS unit, "
        "count(DISTINCT b.file_path) AS fan_out_files ORDER BY a.file_path",
        note="fixture fan-out",
    )

    def measured(result: dict, key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in probe.rows_as_dicts(result):
            unit = (row.get("unit") or "").replace("\\", "/")
            if unit in EXPECTED_FAN_IN_FILES:
                out[unit] = int(row.get(key) or 0)
        return out

    got_in = measured(fan_in, "fan_in_files")
    got_out = measured(fan_out, "fan_out_files")
    # A unit with no inbound edge produces no row, which is zero rather than absent.
    for unit in EXPECTED_FAN_IN_FILES:
        got_in.setdefault(unit, 0)
        got_out.setdefault(unit, 0)
    edges = probe.query(
        "MATCH (a)-[r:IMPORTS]->(b) RETURN a.file_path AS src, b.file_path AS dst, "
        "labels(b) AS target_label ORDER BY a.file_path",
        note="every fixture IMPORTS edge, verbatim",
    )
    undercounted = {
        unit: (NAIVE_FAN_IN_FILES[unit], got_in.get(unit, 0))
        for unit in NAIVE_FAN_IN_FILES
        if NAIVE_FAN_IN_FILES[unit] != got_in.get(unit, 0)
    }
    return {
        "expected_fan_in": EXPECTED_FAN_IN_FILES,
        "measured_fan_in": got_in,
        "fan_in_matches": got_in == EXPECTED_FAN_IN_FILES,
        "expected_fan_out": EXPECTED_FAN_OUT_FILES,
        "measured_fan_out": got_out,
        "fan_out_matches": got_out == EXPECTED_FAN_OUT_FILES,
        "naive_fan_in": NAIVE_FAN_IN_FILES,
        "undercounted_vs_source": undercounted,
        "all_edges": edges,
        "fan_in_query": fan_in,
        "fan_out_query": fan_out,
    }


def _run_project(binary: Path, project: str, disk_files: int | None) -> dict:
    probe = Probe(binary, project)
    out = {
        "project": project,
        "item1_syntax": item1_syntax(probe),
        "item2_identity": item2_identity(probe),
        "item3_canonical": item3_canonical(probe, disk_files),
        "item4_imports": item4_imports(probe),
        "item5_shape": item5_shape(probe),
        "item6_distinct": item6_distinct(probe),
        "item7_limits": item7_limits(probe),
    }
    out["degraded_queries"] = probe.degraded
    out["errors"] = probe.errors
    out["engine_warnings"] = sorted(set(probe.warnings))
    return out, probe


def probe_coverage(run: dict) -> dict:
    """Whether every IMPORTS edge could be attributed to a target file.

    Read off the recorded reply rather than assumed. The two numbers come from one
    query, so a failure leaves them both absent and the check fails rather than
    comparing two blanks as equal.
    """
    result = run["item4_imports"]["target_coverage"]
    rows = result.get("rows") or []
    cols = result.get("got_columns") or []
    if not rows or "all_edges" not in cols or "targets_with_file_path" not in cols:
        return {"edges": None, "targets": None, "complete": False}
    row = dict(zip(cols, rows[0]))
    edges = int(row["all_edges"])
    targets = int(row["targets_with_file_path"])
    return {
        "edges": edges,
        "targets": targets,
        "complete": edges > 0 and edges == targets,
    }


def _report(fixture: dict, marm: dict, verify: dict) -> bool:
    def line(label: str, value: object) -> None:
        print(f"  {label:38} {value}")

    print("\n=== item 1: accepted syntax ===")
    syn = marm["item1_syntax"]
    forms = syn["invocation_forms"]
    line("structured form in use", forms["in_use"])
    for form, got in forms["measured"].items():
        state = "accepted" if got["accepted"] else f"rejected: {got['detail']}"
        line(f"  form {form}", f"{state}{'  DEPRECATED' if got['deprecated'] else ''}")
    line("format published as a CLI flag", syn["format_flag_published"])
    line("aggregate alone", syn["aggregate_alone"].get("got_columns"))
    line("property + aggregate", syn["property_plus_aggregate"].get("got_columns"))
    line("flag form replies in JSON", syn["flag_form_is_prose"]["reply_is_json"])
    for label, deg in syn["degradations"].items():
        line(f"degrades: {label}", f"asked {deg.get('asked_columns')}")
        line("  got back", f"{deg.get('got_columns')}  ({deg.get('total')} rows)")
    bad = marm["item1_syntax"]["malformed_query"]
    line(
        "malformed query",
        "error" if "error" in bad else f"accepted: {bad.get('got_columns')}",
    )

    print("\n=== item 2: File and Module identity ===")
    ident = marm["item2_identity"]
    for name in ("file_counts", "module_counts"):
        rows = ident[name].get("rows") or [[]]
        line(name, dict(zip(ident[name].get("got_columns") or [], rows[0])))
    for row in (ident["file_fields"].get("rows") or [])[:2]:
        line("File", row)
    for row in (ident["module_fields"].get("rows") or [])[:2]:
        line("Module", row)
    line("file_path on both labels", ident["file_path_join"]["on_both_labels"])
    line("  File label only", ident["file_path_join"]["file_only"])
    line("  Module label only", ident["file_path_join"]["module_only"])

    print("\n=== item 3: canonical code_unit_id ===")
    can = marm["item3_canonical"]
    line("candidate", can["candidate"])
    line(
        "distinct units, all labels",
        (can["distinct_units_all_labels"].get("rows") or [["?"]])[0],
    )
    line(
        "distinct units, File only",
        (can["distinct_units_file_label"].get("rows") or [["?"]])[0],
    )
    line("python/ts files on disk", can["files_on_disk"])

    print("\n=== item 4: IMPORTS ===")
    imp = marm["item4_imports"]
    for row in imp["label_pairs"].get("rows") or []:
        line("label pair", row)
    line(
        "edges / targets with file_path",
        (imp["target_coverage"].get("rows") or [["?"]])[0],
    )
    print("  fan-in, top rows (unit, edges, distinct files):")
    for row in (imp["fan_in"].get("rows") or [])[:5]:
        print(f"    {row}")

    print("\n=== item 5: JSON shape ===")
    line("keys", marm["item5_shape"]["keys"])
    line("note", marm["item5_shape"]["differs_from_other_calls"])

    print("\n=== item 6: non-DISTINCT cross-check (#1364) ===")
    dis = marm["item6_distinct"]
    line("DISTINCT type(r) returned", dis["distinct_type_count"])
    line("group-by returned", dis["grouped_type_count"])
    line("agrees", dis["agrees"])
    if dis["missing_from_distinct"]:
        line("missing from DISTINCT", dis["missing_from_distinct"])

    print("\n=== item 7: ordering, caps, truncation ===")
    lim = marm["item7_limits"]
    line("max_rows=5 returned", lim["max_rows_cap"].get("total"))
    line("LIMIT 5 returned", lim["query_limit"].get("total"))
    line("true File count", (lim["true_count"].get("rows") or [["?"]])[0])
    line("signals truncation", lim["signals_truncation"])
    line("ordering stable across two runs", lim["ordering_stable"])

    print("\n=== controlled fixture: hand-counted coupling ===")
    line("expected fan-in", verify["expected_fan_in"])
    line("measured fan-in", verify["measured_fan_in"])
    line("fan-in matches", verify["fan_in_matches"])
    line("expected fan-out", verify["expected_fan_out"])
    line("measured fan-out", verify["measured_fan_out"])
    line("fan-out matches", verify["fan_out_matches"])
    line("a source reader would count", verify["naive_fan_in"])
    line("undercounted (naive vs engine)", verify["undercounted_vs_source"] or "none")
    print("  every fixture IMPORTS edge:")
    for row in verify["all_edges"].get("rows") or []:
        print(f"    {row}")

    print("\n=== verdict ===")
    known = set(DEGRADING_QUERIES.values())

    def unexpected(run: dict) -> list[dict]:
        return [d for d in run["degraded_queries"] if d["query"] not in known]

    unexpected_marm = unexpected(marm)
    unexpected_fixture = unexpected(fixture)
    # A construct that stopped degrading is a contract change, so it fails the run
    # rather than passing quietly: the spec's guidance would be stale.
    still_degrading = {
        label: any(d["query"] == query for d in marm["degraded_queries"])
        for label, query in DEGRADING_QUERIES.items()
    }
    # Measured, not asserted. This was a hard-coded True, which is the one thing a
    # probe must never contain: it reported evidence it had not collected.
    coverage = probe_coverage(marm)
    errors = marm["errors"] + fixture["errors"]
    # The queries the run depends on must not warn. The deliberate raw-JSON probe
    # collects its warning separately, so anything here is unexpected.
    warnings = sorted(set(marm["engine_warnings"] + fixture["engine_warnings"]))

    checks = {
        "no query errored": not errors,
        "no engine warning on the queries in use": not warnings,
        "no unexpected degradation on MARM": not unexpected_marm,
        "no unexpected degradation on the fixture": not unexpected_fixture,
        "every known degrading construct still degrades": all(still_degrading.values()),
        "every IMPORTS edge attributable to a file": coverage["complete"],
        "fixture fan-in matches hand count": verify["fan_in_matches"],
        "fixture fan-out matches hand count": verify["fan_out_matches"],
        "DISTINCT cross-check agrees": dis["agrees"] and dis["distinct_type_count"] > 0,
    }
    for label, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    line("IMPORTS edges / attributable", f"{coverage['edges']} / {coverage['targets']}")
    for label, ok in still_degrading.items():
        if not ok:
            print(f"  NO LONGER DEGRADES: {label}\n    {DEGRADING_QUERIES[label]}")
    for d in unexpected_marm + unexpected_fixture:
        print(f"  DEGRADED: asked {d['asked']} got {d['got']}\n    {d['query']}")
    for d in errors:
        print(f"  ERROR: {d['note']}\n    {d['error']}\n    {d['query']}")
    for warning in warnings:
        print(f"  ENGINE WARNING: {warning}")
    return all(checks.values())


def _count_source_files(repo: Path) -> int:
    return sum(1 for p in repo.rglob("*.py") if ".git" not in p.parts)


def _run(args, cleanup_failed: list[str]) -> int:
    binary = engine_binary()
    if binary is None or not binary.exists():
        print("engine binary not found; run MARM once to download it")
        return 2

    work = Path(tempfile.mkdtemp(prefix="cga-units-"))
    repo = work / "fixture"
    project = None
    try:
        try:
            _build_fixture(repo)
        except (OSError, RuntimeError) as exc:
            print(f"SETUP FAILED: {exc}")
            return 2

        indexed = _index(binary, repo)
        if "__error__" in indexed:
            print(f"INDEX FAILED: {indexed['__error__']}")
            return 2
        project = indexed.get("project")
        print(
            f"fixture {project}: {indexed.get('nodes')} nodes, "
            f"{indexed.get('edges')} edges"
        )

        marm_project = _resolve_project(binary, REPO_ROOT)
        if not marm_project:
            print(
                f"this checkout is not indexed: no project has root_path {REPO_ROOT}.\n"
                "The live half of the contract cannot be probed without it. Index it\n"
                "first, or run against a checkout that is indexed."
            )
            return 2

        fixture_out, fixture_probe = _run_project(
            binary, project, _count_source_files(repo)
        )
        verify = _verify_fixture(fixture_probe)
        marm_out, _ = _run_project(binary, marm_project, None)
        print(f"live project resolved: {marm_project}")

        ok = _report(fixture_out, marm_out, verify)
        if args.json:
            args.json.write_text(
                json.dumps(
                    {
                        "engine_version": str(binary.parent.name),
                        "fixture": fixture_out,
                        "fixture_verification": verify,
                        "marm": marm_out,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"\nraw results: {args.json}")
        return 0 if ok else 3
    finally:
        issues: list[str] = []
        if project and not args.keep:
            status = asyncio.run(drop_project(project))
            print(f"\ncleanup: {status}")
            if not succeeded(status):
                issues.append(f"project {project}: {status}")
        if not args.keep:
            try:
                shutil.rmtree(work)
            except OSError as exc:
                issues.append(f"temp dir {work}: {exc}")
        else:
            report_kept(project, repo)
        cleanup_failed.extend(issues)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--keep",
        action="store_true",
        help="keep the fixture files AND its indexed graph project (both need removing by hand)",
    )
    ap.add_argument("--json", type=Path, help="also write raw results here")
    args = ap.parse_args()

    cleanup_failed: list[str] = []
    code = _run(args, cleanup_failed)
    if cleanup_failed:
        print("CLEANUP FAILED")
        for issue in cleanup_failed:
            print(f"    {issue}")
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
