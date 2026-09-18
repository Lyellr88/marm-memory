"""Run only inside a disposable built image, with /repository bind-mounted."""

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

os.environ.update(
    MARM_API_KEY="TestDockerGraph_12345#abcDEF",
    GRAPH_AUTO_INDEX_DEBOUNCE_SECONDS="1",
    GRAPH_AUTO_INDEX_PROJECT_TTL="10",
    WRITE_QUEUE_ENABLED="0",
)

from codebase_memory_mcp import _cli

from marm_graph.core import tool_router as router
from marm_graph.core.models import CodeLookupRequest, GraphIndexRequest
from marm_mcp_server.core.graph_index_worker import GraphIndexWorker, git_source_state
from marm_mcp_server.core.graph_supervisor import graph_supervisor


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


async def wait_for(predicate, label):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.2)
    raise AssertionError(
        f"Timed out waiting for {label}: {graph_supervisor.snapshot()}"
    )


async def main():
    # The bind mount belongs to the host uid on Linux. Create the repository
    # as marm so Git's ownership check remains enabled and can trust it.
    root = Path("/repository/fixture")
    root.mkdir()
    assert not _cli._bin_path(_cli._version()).exists(), (
        "fresh container must not use pip's binary cache"
    )
    assert Path(os.environ["CBM_BINARY_PATH"]).is_file()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Docker regression")
    git(root, "config", "user.email", "docker-test@example.invalid")
    source = root / "example.py"
    source.write_text("def initial_symbol():\n    return 1\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Initial fixture")
    worker = GraphIndexWorker()
    worker.start()
    try:
        await wait_for(
            lambda: graph_supervisor.snapshot()["available"], "worker engine startup"
        )
        client = graph_supervisor.get_client()
        indexed = await asyncio.to_thread(
            router.do_index,
            client,
            GraphIndexRequest(action="index", repo_path=str(root), mode="fast"),
        )
        assert indexed.get("status") != "error", indexed
        await wait_for(lambda: worker._indexed >= 1, "initial background indexing")
        before_count = worker._indexed
        before_git = git_source_state(str(root))
        assert before_git is not None
        request = CodeLookupRequest(query="^added_by_background_worker$", kind="symbol")
        before = await asyncio.to_thread(router.do_lookup, client, request)
        assert not before.get("results"), before
        source.write_text(
            source.read_text(encoding="utf-8")
            + "\ndef added_by_background_worker():\n    return 42\n",
            encoding="utf-8",
        )
        git(root, "add", ".")
        git(root, "commit", "-qm", "Add symbol")
        await wait_for(
            lambda: worker._indexed > before_count, "automatic update after commit"
        )
        after = await asyncio.to_thread(router.do_lookup, client, request)
        names = [entry.get("name") for entry in after.get("results", [])]
        assert "added_by_background_worker" in names, after
        assert git_source_state(str(root)) != before_git
        reason = worker._watched[str(root)].last_index_reason
        assert reason == "head_moved", reason
        print(
            "AUTO_INDEX_ACCEPTANCE "
            + json.dumps(
                {
                    "last_index_reason": reason,
                    "new_symbol": "added_by_background_worker",
                    "manual_index_calls": 1,
                }
            ),
            flush=True,
        )
    finally:
        await worker.stop()
        graph_supervisor.stop()


if __name__ == "__main__":
    asyncio.run(main())
