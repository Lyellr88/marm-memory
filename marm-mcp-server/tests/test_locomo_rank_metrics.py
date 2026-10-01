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


@pytest.mark.parametrize("k", [0, -1])
def test_an_empty_top_k_scores_zero_instead_of_dividing_by_zero(k):
    assert run_eval.rank_metrics(["g"], {"g"}, k=k) == {
        "recall_at_k": 0.0,
        "mrr": 0.0,
        "ndcg_at_k": 0.0,
    }


def test_the_summary_table_shows_semantic_recall_at_k():
    row = {
        "total": 4,
        "any_hit_rate": 0.5,
        "all_hit_rate": 0.25,
        "evidence_recall": 0.4,
        "semantic_any_hit_rate": 0.5,
        "log_any_hit_rate": 0.25,
        "semantic_recall_at_k": 0.375,
        "mrr": 0.3,
        "ndcg_at_k": 0.35,
    }
    header = run_eval.table_header()
    line = run_eval.table_row("OVERALL", row)
    assert "sem-R@k" in header
    assert "37.5%" in line
    assert len(header) == len(line)


def test_a_question_with_no_semantic_gold_is_left_out_of_rank_averages():
    # Its semantic write failed: it counts for coverage, not for ranking.
    bucket = run_eval._blank_bucket()
    run_eval._add_ranks(bucket, {"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0})
    run_eval._add_ranks(bucket, None)
    assert bucket["semantic_rank_total"] == 1
    assert run_eval._rank_rates(bucket) == {
        "semantic_recall_at_k": 1.0,
        "mrr": 1.0,
        "ndcg_at_k": 1.0,
    }


def test_a_category_with_nothing_to_rank_reports_none_not_zero():
    rates = run_eval._rank_rates(run_eval._blank_bucket())
    assert rates == {"semantic_recall_at_k": None, "mrr": None, "ndcg_at_k": None}


def test_the_table_shows_unavailable_rank_values_as_na():
    row = {
        "total": 4,
        "any_hit_rate": 0.5,
        "all_hit_rate": 0.25,
        "evidence_recall": 0.4,
        "semantic_any_hit_rate": 0.0,
        "log_any_hit_rate": 0.25,
        "semantic_recall_at_k": None,
        "mrr": None,
        "ndcg_at_k": None,
    }
    line = run_eval.table_row("OVERALL", row)
    assert line.count("n/a") == 3
    assert len(line) == len(run_eval.table_header())
