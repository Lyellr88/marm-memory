"""Guards for the marm-docs bundled inside the package.

These docs live in exactly one place, `marm_mcp_server/resources/marm-docs/`, so
a single path works for pip wheels, the Docker image, and dev checkouts. Before
v2.31.0 a second copy sat at the repo root; it was never included in the wheel,
so every path pointing at it resolved to nothing once installed -- the doc
indexer silently indexed zero docs and `read_protocol_file()` returned
"PROTOCOL.md file not found" on every pip install. These tests pin both
behaviors to the packaged location.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from marm_mcp_server.services import documentation
from marm_mcp_server.utils import helpers

EXPECTED_DOCS = {"FAQ.md", "PROTOCOL-LITE.md", "PROTOCOL.md", "README.md"}


def test_docs_live_inside_the_package():
    """The resolved docs dir must be under the installed package, not beside it.

    Anything outside `marm_mcp_server/` is not packaged and breaks on pip.
    """
    package_root = Path(helpers.__file__).resolve().parent.parent
    resolved = helpers.docs_dir()

    assert resolved is not None, "packaged marm-docs directory is missing"
    assert package_root in resolved.parents
    assert {p.name for p in resolved.glob("*.md")} == EXPECTED_DOCS


def test_indexer_and_protocol_readers_share_one_location():
    """Both consumers must agree, or one of them silently reads nothing."""
    assert documentation._docs_dir() == helpers.docs_dir()


def test_loader_enumerates_every_packaged_doc():
    loaded = {d["file_path"].split("/")[-1] for d in documentation.get_docs_to_load()}
    assert loaded == EXPECTED_DOCS


def test_protocol_files_are_readable_from_the_package():
    """Regression test for the bug that shipped: both readers returned failure
    values on pip installs because they pointed outside the package."""
    protocol = asyncio.run(helpers.read_protocol_file())
    assert "not found" not in protocol
    assert "Error reading" not in protocol
    assert len(protocol) > 500, "PROTOCOL.md read back suspiciously short"

    lite = asyncio.run(helpers.read_protocol_lite_file())
    assert lite.strip(), "PROTOCOL-LITE.md read back empty"


def test_no_stray_docs_copy_outside_the_package():
    """A second copy is how this broke: it drifts and it does not ship."""
    repo_copy = Path(helpers.__file__).resolve().parents[2] / "marm-docs"
    assert not repo_copy.exists(), (
        f"{repo_copy} reintroduces the duplicate that is excluded from the wheel; "
        "keep marm_mcp_server/resources/marm-docs/ as the only location"
    )
