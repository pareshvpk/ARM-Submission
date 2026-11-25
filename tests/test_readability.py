"""flesch_reading_ease: fixed sentences with known readability bands."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.readability import flesch_reading_ease


def test_simple_sentence_scores_above_80():
    text = "The cat sat on the mat. The dog ran in the sun."
    assert flesch_reading_ease(text) > 80.0


def test_dense_polysyllabic_sentence_scores_below_30():
    text = (
        "The implementation of comprehensive interoperability necessitates "
        "considerable administrative coordination."
    )
    assert flesch_reading_ease(text) < 30.0


def test_empty_text_does_not_raise():
    assert isinstance(flesch_reading_ease(""), float)
