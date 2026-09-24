"""
`Diagnostic`, the one problem shape every stage of `mdq.loading`'s
pipeline reports through -- a parse failure, a pydantic error, a lint
warning, an unknown frontmatter key.

Split out from `mdq.loading` (which owns and re-exports it) so that
`mdq.linter` and `mdq.parser` -- both upstream of `mdq.loading` in the
pipeline -- can report `Diagnostic`s of their own without importing back
into the module that orchestrates them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning", "info"]

#: Severity, ranked so "at or above" (as `Loaded.validate` uses it) is a
#: plain integer comparison. Higher is more severe.
RANK: dict[Severity, int] = {"info": 1, "warning": 2, "error": 3}


@dataclass(frozen=True)
class Diagnostic:
    """
    One problem found while loading a document.

    `path` locates the offending value the way a `jsonschema`
    `ValidationError.path` or a pydantic error's `loc` does: a tuple of
    keys/indices from the document's root. `line` is set only for a
    parse failure tied to a source node, and only when that node's
    position in the source is known.
    """

    severity: Severity
    code: str
    message: str
    path: tuple[str | int, ...] = ()
    line: int | None = None
