"""Finding local models, and refusing to browse outside them."""

import json
import os
from pathlib import Path

import pytest

from marm_mcp_server.services import model_discovery as md


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Point discovery at a scratch tree, not the developer's real 62 GB one."""
    monkeypatch.setattr(md.Path, "home", staticmethod(lambda: tmp_path / "home"))
    monkeypatch.delenv("MARM_LLM_MODEL_ROOTS", raising=False)
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    # The saved-roots flag reads SQLite; these tests are about the scanner.
    monkeypatch.setattr(md, "_extra_roots", lambda: [])
    md.invalidate()
    yield
    md.invalidate()


def _write(path: Path, size: int = 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    return path


def test_an_lm_studio_tree_is_named_by_publisher_and_repo(tmp_path, monkeypatch):
    root = tmp_path / "home" / ".lmstudio" / "models"
    _write(root / "unsloth" / "gpt-oss-20b-GGUF" / "gpt-oss-20b-Q4.gguf", 2048)
    found = md.discover(force=True)
    names = [m["name"] for m in found["models"]]
    assert "unsloth/gpt-oss-20b-GGUF/gpt-oss-20b-Q4.gguf" in names
    assert found["models"][0]["source"] == "LM Studio"


def test_a_projector_is_not_offered_as_a_model(tmp_path):
    """Regression: an mmproj file loads *alongside* a model, never instead.

    Offering it is how a reader selects something that cannot serve, and the
    failure surfaces much later as a runtime error they cannot connect back
    to this list.
    """
    root = tmp_path / "home" / ".lmstudio" / "models"
    _write(root / "org" / "repo" / "mmproj-gemma-BF16.gguf", 4096)
    _write(root / "org" / "repo" / "gemma-Q4_0.gguf", 2048)
    names = [m["name"] for m in md.discover(force=True)["models"]]
    assert any("gemma-Q4_0" in n for n in names)
    assert not any("mmproj" in n for n in names)


def test_an_ollama_blob_is_resolved_through_its_manifest(tmp_path):
    """Ollama stores weights under a hash, so the manifest IS the name.

    Walking blobs alone yields `sha256-3f8a...`, which tells a reader nothing
    and cannot be matched to anything they typed at `ollama run`.
    """
    root = tmp_path / "home" / ".ollama" / "models"
    digest = "sha256:" + "ab" * 32
    blob = _write(root / "blobs" / digest.replace(":", "-"), 4096)
    manifest = root / "manifests" / "registry.ollama.ai" / "library" / "llama3.2" / "8b"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "layers": [
                    {
                        "mediaType": "application/vnd.ollama.image.license",
                        "digest": "x",
                    },
                    {
                        "mediaType": "application/vnd.ollama.image.model",
                        "digest": digest,
                    },
                ]
            }
        )
    )
    models = md.discover(force=True)["models"]
    assert len(models) == 1
    assert models[0]["name"] == "llama3.2:8b"
    assert models[0]["path"] == str(blob)
    assert models[0]["source"] == "Ollama"


def test_a_sharded_huggingface_repo_is_one_entry_not_fifteen(tmp_path):
    """A 15-shard model is one choice, and none of the shards loads alone."""
    hub = tmp_path / "home" / ".cache" / "huggingface" / "hub"
    snapshot = hub / "models--org--Big-Model" / "snapshots" / "abc123"
    for i in range(1, 16):
        _write(snapshot / f"model-{i:05d}-of-00015.safetensors", 1024)
    models = md.discover(force=True)["models"]
    assert len(models) == 1
    assert models[0]["name"] == "org/Big-Model"
    assert models[0]["shards"] == 15
    assert models[0]["size_bytes"] == 15 * 1024


def test_browse_refuses_a_path_outside_every_root(tmp_path):
    """The containment check is the whole security surface of Browse."""
    root = tmp_path / "home" / ".lmstudio" / "models"
    _write(root / "org" / "repo" / "m.gguf")
    secret = tmp_path / "secret"
    secret.mkdir()
    result = md.browse(str(secret))
    assert result["entries"] == []
    assert "outside every known model directory" in result["error"]


def test_browse_refuses_a_traversal_that_escapes_a_root(tmp_path):
    """`<root>/../..` must be judged after resolution, not as typed."""
    root = tmp_path / "home" / ".lmstudio" / "models"
    _write(root / "org" / "repo" / "m.gguf")
    escaped = md.browse(str(root / ".." / ".." / ".." / "secret"))
    assert "outside every known model directory" in escaped["error"]


def test_browse_does_not_offer_a_parent_above_the_root(tmp_path):
    """Without this, Browse walks up out of the scope it is meant to have."""
    root = tmp_path / "home" / ".lmstudio" / "models"
    _write(root / "org" / "repo" / "m.gguf")
    assert md.browse(str(root))["parent"] is None
    assert md.browse(str(root / "org"))["parent"] == str(root)


def test_validate_rejects_a_file_that_is_not_a_model(tmp_path):
    root = tmp_path / "home" / ".lmstudio" / "models"
    plain = _write(root / "notes.txt")
    verdict = md.validate(str(plain))
    assert verdict["valid"] is False
    assert "recognised model file" in verdict["reason"]


def test_validate_accepts_a_real_model_file(tmp_path):
    root = tmp_path / "home" / ".lmstudio" / "models"
    model = _write(root / "org" / "repo" / "m.gguf", 4096)
    verdict = md.validate(str(model))
    assert verdict == {
        "valid": True,
        "path": str(model),
        "kind": "file",
        "size_bytes": 4096,
        "format": "gguf",
    }


def test_a_root_that_does_not_exist_is_reported_rather_than_dropped(tmp_path):
    """ "Ollama is not installed" and "installed and empty" differ, and a
    reader hunting a missing model needs to tell them apart."""
    roots = md.candidate_roots()
    ollama = [r for r in roots if r["source"] == "Ollama"]
    assert ollama, "Ollama must always be offered as a place to look"
    # Only the home-scoped root, because only that one is isolated: the Linux
    # branch also offers /usr/share and /var/lib paths, which the fixture
    # cannot redirect. Asserting over all of them made the result depend on
    # whether the host happened to have packaged Ollama installed.
    scoped = [r for r in ollama if str(tmp_path) in r["path"]]
    assert scoped, "the home-scoped Ollama root must be among the candidates"
    assert all(r["exists"] is False for r in scoped)


def test_an_unreadable_directory_does_not_abort_the_scan(tmp_path):
    """One chmod-000 directory must not cost every other model on the box."""
    root = tmp_path / "home" / ".lmstudio" / "models"
    _write(root / "org" / "repo" / "good.gguf", 2048)
    blocked = root / "blocked"
    blocked.mkdir(parents=True)
    _write(blocked / "hidden.gguf")
    os.chmod(blocked, 0o000)
    try:
        names = [m["name"] for m in md.discover(force=True)["models"]]
        assert any("good.gguf" in n for n in names)
    finally:
        os.chmod(blocked, 0o755)
