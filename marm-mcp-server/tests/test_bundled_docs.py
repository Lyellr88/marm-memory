"""Guards for the marm-docs copy bundled into the package for pip installs."""

from __future__ import annotations

from pathlib import Path

from marm_mcp_server.services import documentation

SOURCE_DOCS = Path(__file__).resolve().parents[1] / "marm-docs"
PACKAGED_DOCS = (
    Path(documentation.__file__).resolve().parent.parent / "resources" / "marm-docs"
)


def test_packaged_docs_match_source_byte_for_byte():
    source = {p.name: p.read_bytes() for p in SOURCE_DOCS.glob("*.md")}
    packaged = {p.name: p.read_bytes() for p in PACKAGED_DOCS.glob("*.md")}
    assert packaged.keys() == source.keys(), "bundled marm-docs file set drifted"
    for name in source:
        assert packaged[name] == source[name], f"bundled {name} differs from source"


def test_loader_resolves_a_docs_dir_and_lists_all_docs():
    docs_dir = documentation._docs_dir()
    assert docs_dir is not None and docs_dir.exists()
    loaded = {d["file_path"].split("/")[-1] for d in documentation.get_docs_to_load()}
    on_disk = {p.name for p in SOURCE_DOCS.glob("*.md")}
    assert loaded == on_disk and loaded, "loader did not enumerate the bundled docs"
