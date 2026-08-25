import numpy as np
import pytest

from marm_mcp_server.config.settings import DEFAULT_SEMANTIC_DIM, DEFAULT_SEMANTIC_MODEL
from marm_mcp_server.core.memory import _FastEmbedEncoder


class _FakeTextEmbedding:
    """Stands in for fastembed.TextEmbedding: records the model name it was
    constructed with, and .embed() always returns a generator of one vector
    per input, matching the real API's contract."""

    def __init__(self, model_name):
        self.model_name = model_name

    def embed(self, texts):
        for i, _ in enumerate(texts):
            yield np.full(3, float(i + 1), dtype=np.float32)


@pytest.fixture
def patched_encoder(monkeypatch):
    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", _FakeTextEmbedding)
    return _FastEmbedEncoder("jinaai/jina-embeddings-v2-small-en")


def test_full_model_name_passes_through_unchanged(patched_encoder):
    assert patched_encoder._model.model_name == "jinaai/jina-embeddings-v2-small-en"


def test_legacy_minilm_short_name_keeps_compatibility(monkeypatch):
    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", _FakeTextEmbedding)
    encoder = _FastEmbedEncoder("all-MiniLM-L6-v2")
    assert encoder._model.model_name == "sentence-transformers/all-MiniLM-L6-v2"


def test_default_model_registry_metadata_matches_configured_dimension():
    from fastembed import TextEmbedding

    model = next(
        item
        for item in TextEmbedding.list_supported_models()
        if item["model"] == DEFAULT_SEMANTIC_MODEL
    )
    assert model["dim"] == DEFAULT_SEMANTIC_DIM
    assert "Prefixes for queries/documents: not necessary" in model["description"]


def test_encode_single_string_returns_one_vector_not_a_list(patched_encoder):
    """SentenceTransformer.encode(str) returns a single 1-D array. Callers
    like core/memory_ops.py do query_embedding = await
    asyncio.to_thread(mem._encode_sync, query) and then treat the result as
    one vector directly -- getting back a list-of-one here would silently
    break every dot-product/np.linalg.norm call downstream."""
    result = patched_encoder.encode("a single query string")
    assert isinstance(result, np.ndarray)
    assert result.shape == (3,)


def test_encode_list_of_strings_returns_one_vector_per_input_same_order(
    patched_encoder,
):
    """Regression target: scripts/bench_hotpath.py:80 calls
    mem.encoder.encode(texts) with a *list* of strings, then does
    zip(texts, embs) assuming positional correspondence. fastembed's
    .embed() always returns a generator regardless of batch vs single input,
    so the adapter must detect list input and materialize it, preserving
    order -- not just always take the first result."""
    texts = ["first", "second", "third"]
    result = patched_encoder.encode(texts)
    assert isinstance(result, list)
    assert len(result) == 3
    for i, vec in enumerate(result):
        assert np.array_equal(vec, np.full(3, float(i + 1), dtype=np.float32))
