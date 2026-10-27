"""
numeric.md, "Decimal places": `decimalPlaces` is the precision of the
comparison. The corpus covers the inference and the rounding of a numeric
question and of a numeric blank; this module covers the `effective_decimal_places`
property of a numeric blank.
"""

from __future__ import annotations

import mdq


def test_fill_in_numeric_blank_has_its_own_effective_places() -> None:
    question = mdq.load(
        "Quanto custa [^price]?\n\n[^price/numeric(R$)]: 2.50 +- 0.01\n",
        kind="question",
    ).document
    assert question.blanks[0].effective_decimal_places == 2
