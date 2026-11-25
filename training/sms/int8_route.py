"""Pure INT8 export route decision.

The route decision is factored out of `export_sms.py` so it can be unit tested
without importing torch or any ExecuTorch dependency.

Route B (manual int8 embedding) is the only acceptable route for the shipped
int8 `.pte`. Route A (torchao linear-only int8) leaves a `dequantize_affine`
op that ExecuTorch has no kernel for on the Arm Linux, so it must never be written
as the shipped int8 file.
"""

ROUTE_B = "torchao_linear_plus_manual_int8_embedding"
ROUTE_NONE = "none"


def choose_int8_route(route_a_succeeded: bool, route_b_succeeded: bool) -> str:
    """Return the int8 route to ship, or 'none' when no acceptable route succeeded.

    Route B (manual int8 embedding) is always preferred. Route A alone never
    ships because its output is unrunnable on the Arm Linux.
    """
    if route_b_succeeded:
        return ROUTE_B
    return ROUTE_NONE


def int8_should_fail(route_a_succeeded: bool, route_b_succeeded: bool) -> bool:
    """Return True when the export must fail non-zero (no acceptable int8 route)."""
    return choose_int8_route(route_a_succeeded, route_b_succeeded) == ROUTE_NONE
