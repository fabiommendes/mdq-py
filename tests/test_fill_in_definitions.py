"""
Blank definitions of a fill-in question (docs/question-types/fill-in.md
"Blank definitions"). The corpus covers the definitions themselves; this
module checks the message of a detached definition, which a `.lint.json`
does not record.
"""

from __future__ import annotations

import mdq


def test_a_definition_after_a_paragraph_is_detached() -> None:
    loaded = mdq.load(
        "A capital é [^capital] e a do Acre é [^acre].\n\n"
        "[^capital/short-answer]: Brasília\n\n"
        "Rio Branco fica às margens do rio Acre.\n\n"
        "[^acre/short-answer]: Rio Branco\n",
        kind="question",
    )
    [diagnostic] = loaded.diagnostics
    assert "[^acre/short-answer]" in diagnostic.message
