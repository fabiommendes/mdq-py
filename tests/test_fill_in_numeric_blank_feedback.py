"""fill-in.md, "Feedback": API of the `incorrectFeedback` of a numeric blank."""

from __future__ import annotations

import mdq

FEEDBACK = "The Pico da Neblina is in the Serra do Imeri."
STEM = "The Pico da Neblina is [^neblina] meters high, and the Bandeira [^bandeira]."


def _load(front: str):
    source = (
        f"---\n{front}\n---\n\n{STEM}\n\n"
        "[^neblina/numeric(m)]: 2995 +- 5\n\n"
        "[^bandeira/numeric(m)]: 2892 +- 5\n"
    )
    return mdq.load(source, format="mdq")


def test_the_field_is_written_back_to_the_frontmatter() -> None:
    question = _load(f"incorrectFeedback:\n  neblina: {FEEDBACK}").document
    assert question.frontmatter()["incorrectFeedback"] == {"neblina": FEEDBACK}


