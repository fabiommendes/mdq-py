"""
Pydantic models for the MDQ document tree and for grading results.

These models are the public shape of a *validated* document. The
pipeline is markdown -> json -> json validated against `schema/` ->
model, so a model is what "parse, don't validate" hands back: by the
time one exists, the document is known to be well formed.

Two rules govern this package:

1. The models mirror the JSON schemas in `schema/` and in most cases should not
   be stricter than them. A few exceptions are rules that are obligatory in the
   question specification but cannot be enforced by the JSON schema. Things like
   "all keys in a list of objects must be unique".

2. Field names are the schema's names in snake_case, with the camelCase
   spelling kept as an alias, so a model round-trips to the document it
   came from.

This package's layout mirrors `docs/question-types/*`, one module per
question family, all building on `_base.MdqModel`/`BaseQuestion`:
`_choice` (multiple-choice, multiple-selection, true-false), `_numeric`,
`_text` (short-answer, essay), `_fill_in`, `_ordering`, and `_exam`
(the `Question`/`ExamEntry` unions, `Include`/`IncludeAll`, `Exam`
itself). `_score` holds `QuestionScore`, every `score_response()`'s
return type. Five more private modules hold the non-model helpers each
`render()`/`lint()` method calls into: `_render`, `_lint`, `_regex`,
`_query`, `_slugify`.

This package imports `mdq._parser` and `mdq._markdown` -- a new
direction of coupling for the model layer, which otherwise knows
nothing about how Markdown gets parsed. It is deliberate:
`_base.normalize_paragraphs`/`normalize_intro` need to canonicalize
`preamble`/`stem`/`epilogue` into the exact fixed point a
render-then-parse round trip produces, and the only way to guarantee
that without a second, drifting copy of the parser's reconstruction
rules is to call the parser itself (`_parser.reconstruct_blocks`).
Neither module has a reciprocal dependency on this one (they hand back
plain dicts), so this stays one-directional.

Only the document tree is re-exported here: question classes, choice
and blank shapes, the exam types, and `QuestionScore`. The Literal type
aliases a field's type mentions (`GradingStrategy`, `Diacritics`, ...)
live in `mdq.types`, the single source for all of them.
"""

from __future__ import annotations

from ._base import BaseQuestion, MdqModel
from ._choice import (
    BooleanChoice,
    MultipleChoiceQuestion,
    MultipleSelectionQuestion,
    ScoredChoice,
    Statement,
    TrueFalseQuestion,
)
from ._exam import (
    Exam,
    ExamEntry,
    Include,
    IncludeAll,
    Question,
    QuestionRoot,
    Select,
    select_random,
)
from ._fill_in import Blank, ChoiceBlank, FillInQuestion, NumericBlank, ShortAnswerBlank
from ._numeric import NumericQuestion, Tolerance
from ._ordering import OrderingAlternative, OrderingLine, OrderingQuestion
from ._score import QuestionScore
from ._text import AnswerPattern, EssayQuestion, ShortAnswerQuestion

__all__ = [
    "MdqModel",
    "Tolerance",
    "ScoredChoice",
    "BooleanChoice",
    "Statement",
    "BaseQuestion",
    "MultipleChoiceQuestion",
    "MultipleSelectionQuestion",
    "TrueFalseQuestion",
    "NumericQuestion",
    "ShortAnswerQuestion",
    "AnswerPattern",
    "EssayQuestion",
    "ChoiceBlank",
    "ShortAnswerBlank",
    "NumericBlank",
    "Blank",
    "FillInQuestion",
    "OrderingLine",
    "OrderingAlternative",
    "OrderingQuestion",
    "Question",
    "QuestionRoot",
    "Include",
    "IncludeAll",
    "ExamEntry",
    "Select",
    "select_random",
    "Exam",
    "QuestionScore",
]
