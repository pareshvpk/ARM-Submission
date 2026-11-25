"""CPU utilisation parsing from hand-written /proc/stat snapshots."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.run_bench import cpu_util_from_proc_stat, sample_cpu_util

PREV = """cpu  100 0 50 850 0 0 0 0 0 0
cpu0 50 0 25 425 0 0 0 0 0 0
cpu1 50 0 25 425 0 0 0 0 0 0
"""

CURR = """cpu  150 0 75 1075 0 0 0 0 0 0
cpu0 80 0 40 480 0 0 0 0 0 0
cpu1 70 0 35 595 0 0 0 0 0 0
"""


def test_overall_and_per_core_utilisation():
    overall, per_core = cpu_util_from_proc_stat(PREV, CURR)
    assert overall == 25.0
    assert per_core == [45.0, 15.0]


def test_missing_proc_stat_yields_nulls():
    assert cpu_util_from_proc_stat("", "") == (None, None)
    assert sample_cpu_util(None, None) == {
        "cpu_util_percent": None,
        "cpu_util_percent_per_core": None,
    }
