"""Tests for F-08: INT8 export route decision and guards.

These tests exercise the pure `choose_int8_route` function without torch,
verifying that only Route B (manual int8 embedding) can ship as int8 and
that Route A (torchao linear-only) is never accepted.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from training.sms.int8_route import choose_int8_route

def test_route_b_only_ships_int8():
    """Route B succeeded -> int8 ships via manual embedding route."""
    assert choose_int8_route(False, True) == "torchao_linear_plus_manual_int8_embedding"


def test_route_b_with_route_a_ships_int8():
    """Both routes succeeded -> still ships via Route B (Route A ignored for int8)."""
    assert choose_int8_route(True, True) == "torchao_linear_plus_manual_int8_embedding"


def test_route_a_alone_does_not_ship_int8():
    """Route A alone must never ship int8 (leaves dequantize_affine op unsupported by the target runtime)."""
    assert choose_int8_route(True, False) == "none"


def test_neither_route_does_not_ship_int8():
    """No route succeeded -> nothing ships."""
    assert choose_int8_route(False, False) == "none"
