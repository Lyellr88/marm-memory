"""Rank-aware metrics in the LoCoMo retrieval harness."""

import importlib.util
import math
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts/benchmarking/accuracy/locomo/run_eval.py"
)
_spec = importlib.util.spec_from_file_location("locomo_run_eval", SCRIPT)
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)


def test_a_gold_item_at_rank_one_scores_perfectly():
    m = run_eval.rank_metrics(["g", "x", "y"], {"g"}, k=5)
    assert m == {"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0}


def test_rank_is_what_mrr_and_ndcg_reward():
    first = run_eval.rank_metrics(["g", "x", "y"], {"g"}, k=5)
    third = run_eval.rank_metrics(["x", "y", "g"], {"g"}, k=5)
    assert first["recall_at_k"] == third["recall_at_k"] == 1.0
    assert third["mrr"] == pytest.approx(1 / 3)
    assert third["ndcg_at_k"] == pytest.approx(1 / math.log2(4))
    assert third["ndcg_at_k"] < first["ndcg_at_k"]


def test_a_miss_scores_zero():
    assert run_eval.rank_metrics(["x", "y"], {"g"}, k=5) == {
        "recall_at_k": 0.0,
        "mrr": 0.0,
        "ndcg_at_k": 0.0,
    }


def test_only_the_top_k_count():
    m = run_eval.rank_metrics(["x", "y", "g"], {"g"}, k=2)
    assert m == {"recall_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0}


def test_several_gold_items_share_the_ideal():
    m = run_eval.rank_metrics(["g1", "x", "g2"], {"g1", "g2"}, k=5)
    assert m["recall_at_k"] == 1.0
    assert m["mrr"] == 1.0
    ideal = 1 + 1 / math.log2(3)
    assert m["ndcg_at_k"] == pytest.approx((1 + 1 / math.log2(4)) / ideal)


def test_an_empty_gold_set_is_not_scored():
    assert run_eval.rank_metrics(["x"], set(), k=5) is None
