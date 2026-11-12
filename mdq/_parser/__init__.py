"""
The MDQ Markdown parser.

Turns MDQ source into the JSON-like dict shapes `schema/*.yaml`
describe (the ones `mdq.load`/`mdq.parse` validate through the pydantic
models): `parse_question` for a
single question, `parse_exam` for an exam (its `include`/`includeAll`
blocks left unresolved -- see `mdq.models.Exam.resolve`), and `is_exam`
to tell which one a document is before parsing it.

Split by concern, leaf modules first: `_frontmatter` (the `---` YAML
block and its per-type known-keys tables), `_choices` (bracket-marker
list items, shared by multiple-choice/-selection/true-false/fill-in),
`_numeric` (the `sign? numeric_value abstol? reltol?` grammar), `_ordering`
(indentation leveling) and `_attachments` (the `## [attachments]` section and
the split of the blocks after the body into sections). `_question` builds on
them for `MDQParser`,
the recursive-descent parser for one question document. `_exam` builds
on `_question` (it calls `parse_question` for each inline question
block) for the exam-level `===`/`---` block-splitting grammar.
`_spaces` reads the source of either one for the `non-ascii-whitespace`
lint (`find_unicode_spaces`).

`reconstruct_blocks`, `find_forbidden_elements` and
`find_stray_choice_markers` are exposed here too, even though they read
like `mdq.models` helpers: they replay a
stem/epilogue field through `MDQParser` to canonicalize it or
check it for constructs base.md forbids, so they belong next to the
grammar they reuse, not in `mdq._markdown` (which only wraps the
underlying `markdown_it.MarkdownIt` instance, `md`).
"""

from __future__ import annotations

from ._choices import SLUG_PREFIX_RE
from ._exam import INHERITED_FIELDS, SEPARATOR, inherit, is_exam, parse_exam
from ._frontmatter import compose_yaml, dump_yaml, frontmatter_fields, load_yaml
from ._numeric import parse_numeric_answer, parse_numeric_string
from ._blocks import (
    close_unclosed_fence,
    find_answer_key_forbidden_elements,
    find_forbidden_elements,
    find_stray_choice_markers,
    first_fenced_code,
    has_unclosed_fence,
    reconstruct_blocks,
)
from ._question import parse_question
from ._rubric import (
    Annotation,
    Annotations,
    RubricSyntaxError,
    check_criterion_start,
    scan_annotations,
)
from ._spaces import find_unicode_spaces

__all__ = [
    "parse_question",
    "parse_exam",
    "is_exam",
    "INHERITED_FIELDS",
    "inherit",
    "SLUG_PREFIX_RE",
    "SEPARATOR",
    "reconstruct_blocks",
    "find_forbidden_elements",
    "find_answer_key_forbidden_elements",
    "find_stray_choice_markers",
    "close_unclosed_fence",
    "first_fenced_code",
    "has_unclosed_fence",
    "parse_numeric_answer",
    "parse_numeric_string",
    "find_unicode_spaces",
    "load_yaml",
    "dump_yaml",
    "compose_yaml",
    "frontmatter_fields",
    "Annotation",
    "Annotations",
    "RubricSyntaxError",
    "check_criterion_start",
    "scan_annotations",
]
