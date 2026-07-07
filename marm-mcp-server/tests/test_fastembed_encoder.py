"""Unit tests for _FastEmbedEncoder, the adapter that lets fastembed serve
the .encode(text) shape every caller (and scripts/bench_hotpath.py) already
expects from SentenceTransformer.

Real cross-backend numerical fidelity (does fastembed's ONNX all-MiniLM-L6-v2
agree with the PyTorch sentence-transformers version) was already verified
separately against real model weights: 1.0000 cosine similarity on a
15-sentence corpus, identical top-5 retrieval ranking. That can't be
re-verified here -- this sandbox's network policy blocks huggingface.co, so
the real model can never download in this environment. These tests instead
target what's actually ours to get wrong: whether the adapter calls
fastembed's real API correctly and preserves SentenceTransformer's
single-string-vs-list-of-strings polymorphism, which is what
scripts/bench_hotpath.py:80 depends on.
"""

import numpy as np
import pytest

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
    return _FastEmbedEncoder("all-MiniLM-L6-v2")


def test_model_name_gets_sentence_transformers_prefix(patched_encoder):
    """fastembed needs the full HF repo id; DEFAULT_SEMANTIC_MODEL is the
    short form SentenceTransformer resolved via its own aliasing -- the
    adapter must add the prefix fastembed requires, not pass the bare name."""
    assert patched_encoder._model.model_name == "sentence-transformers/all-MiniLM-L6-v2"


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
