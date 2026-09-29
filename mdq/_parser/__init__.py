"""
The MDQ Markdown parser.

Turns MDQ source into the JSON-like dict shapes `schema/*.yaml` and
`mdq.validator.validate_document` describe: `parse_question` for a
single question, `parse_exam` for an exam (its `include`/`include-all`
blocks left unresolved -- see `mdq.models.Exam.resolve`), and `is_exam`
to tell which one a document is before parsing it.

Split by concern, leaf modules first: `_frontmatter` (the `---` YAML
block and its per-type known-keys tables), `_choices` (bracket-marker
list items, shared by multiple-choice/-selection/true-false/fill-in),
`_numeric` (the `sign? value abstol? reltol?` grammar) and `_ordering`
(indentation leveling). `_question` builds on all four for `MDQParser`,
the recursive-descent parser for one question document. `_exam` builds
on `_question` (it calls `parse_question` for each inline question
block) for the exam-level `===`/`---` block-splitting grammar.

`reconstruct_blocks` and `find_forbidden_elements` are exposed here too,
even though they read like `mdq.models` helpers: both replay a
preamble/epilogue/stem field through `MDQParser` to canonicalize it or
check it for constructs base.md forbids, so they belong next to the
grammar they reuse, not in `mdq._markdown` (which only wraps the
underlying `markdown_it.MarkdownIt` instance, `md`).
"""

from __future__ import annotations

from ._choices import SLUG_BODY_RE, SLUG_PREFIX_RE
from ._exam import INHERITED_FIELDS, SEPARATOR, is_exam, parse_exam
from ._frontmatter import COMMON_QUESTION_KEYS
from ._numeric import parse_numeric_answer
from ._question import find_forbidden_elements, parse_question, reconstruct_blocks

__all__ = [
    "parse_question",
    "parse_exam",
    "is_exam",
    "INHERITED_FIELDS",
    "SLUG_BODY_RE",
    "SLUG_PREFIX_RE",
    "SEPARATOR",
    "COMMON_QUESTION_KEYS",
    "reconstruct_blocks",
    "find_forbidden_elements",
    "parse_numeric_answer",
]
