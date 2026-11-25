"""Bench helper tests: nearest-rank percentile, resource guard, clean_msg."""
from __future__ import annotations

from bench.bench_url_pte import max_rss_mb, percentile_nearest_rank


def test_percentile_nearest_rank_matches_standard():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile_nearest_rank(vals, 50.0) == 30.0
    assert percentile_nearest_rank(vals, 95.0) == 50.0
    vals4 = [1.0, 2.0, 3.0, 4.0]
    assert percentile_nearest_rank(vals4, 50.0) == 2.0
    assert percentile_nearest_rank([], 95.0) == 0.0


def test_max_rss_mb_never_crashes_without_resource():
    mb = max_rss_mb()
    assert isinstance(mb, float)
    assert mb >= 0.0


def test_clean_msg_flattens_whitespace():
    from bench.make_bench_messages import clean_msg, is_bench_source_disjoint_from_training

    assert clean_msg("a\r\nb\tc  d") == "a b c d"
    assert clean_msg("  hello   world \n") == "hello world"
    assert clean_msg("") == ""
    assert clean_msg(None) == ""  # type: ignore[arg-type]
    assert is_bench_source_disjoint_from_training(["a", "b"], ["c", "d"]) is True
    assert is_bench_source_disjoint_from_training(["a"], ["a"]) is False
