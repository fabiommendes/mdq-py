"""
base.md, "Slug" and the `choice_id` rule of multiple-choice.md: a bracket
followed by `(` or `[` opens a markdown link and is never a slug or a
choice id. The parsing cases live in the example corpus
(`valid/multiple-choice/link-choice`, `reference-link-and-id-separators`,
`valid/essay/link-stem`, `valid/exam/title-link-is-not-slug`).
"""

from __future__ import annotations

import mdq

WIKI = "https://pt.wikipedia.org/wiki/"


def test_render_of_a_link_choice_is_a_fixed_point() -> None:
    md = f"Qual?\n\n* [*] [Brasilia]({WIKI}Brasília)\n* [ ] [rio] Rio\n"
    question = mdq.load(md, kind="question").document
    again = mdq.load(str(question), kind="question")
    assert [d for d in again.diagnostics if d.severity == "error"] == []
    assert again.document == question
