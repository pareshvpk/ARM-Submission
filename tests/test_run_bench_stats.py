"""calc_stats must stay safe on empty input; callers use .get with 0.0."""
from __future__ import annotations

from bench.run_bench import calc_stats


def test_calc_stats_empty_list_returns_empty_dict():
    assert calc_stats([]) == {}


def test_calc_stats_empty_list_get_p95_defaults_to_zero():
    stats = calc_stats([])
    assert stats.get("p95_ms", 0.0) == 0.0
    assert stats.get("count", 0) == 0


def test_calc_stats_non_empty_reports_count_and_p95():
    stats = calc_stats([10.0, 20.0, 30.0, 40.0, 50.0])
    assert stats["count"] == 5
    assert stats["p50_ms"] == 30.0
    assert stats["p95_ms"] == 50.0
    assert stats["min_ms"] == 10.0
    assert stats["max_ms"] == 50.0
    assert stats["mean_ms"] == 30.0


def test_calc_stats_unit_suffix():
    stats = calc_stats([1.0, 2.0, 3.0], unit="s")
    assert "p95_s" in stats
    assert "p95_ms" not in stats


def test_calc_stats_nearest_rank():
    import math

    vals = [1.0, 2.0, 3.0, 4.0]
    stats = calc_stats(vals)
    n = len(vals)
    exp50 = sorted(vals)[math.ceil(0.5 * n) - 1]
    exp95 = sorted(vals)[math.ceil(0.95 * n) - 1]
    exp99 = sorted(vals)[math.ceil(0.99 * n) - 1]
    assert stats["p50_ms"] == exp50
    assert stats["p95_ms"] == exp95
    assert stats["p99_ms"] == exp99
    from bench.run_bench import _percentile_nearest_rank, _default_route_present

    assert _percentile_nearest_rank([1.0, 2.0, 3.0, 4.0], 50.0) == 2.0
    route_on = "Iface\tDestination\tGateway\neth0\t00000000\t0102A8C0\n"
    route_off = "Iface\tDestination\tGateway\n"
    assert _default_route_present(route_on) is True
    assert _default_route_present(route_off) is False
    route_zero_gw = "Iface\tDestination\tGateway\neth0\t00000000\t00000000\n"
    assert _default_route_present(route_zero_gw) is False
