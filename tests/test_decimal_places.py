"""
numeric.md, "Decimal places": `decimalPlaces` is the precision of the
comparison. The corpus covers the inference and the rounding of a numeric
question; this module covers the places of a numeric blank.
"""

from __future__ import annotations

import mdq


def test_fill_in_numeric_blank_rounds_with_its_own_places() -> None:
    question = mdq.load(
        "Quanto custa [^price]?\n\n[^price/numeric(R$)]: 2.50 +- 0.01\n",
        kind="question",
    ).document
    assert question.blanks[0].effective_decimal_places == 2
    assert question.score_response({"price": 2.505}).score == 1.0
    assert question.score_response({"price": 2.515}).score == 0.0
