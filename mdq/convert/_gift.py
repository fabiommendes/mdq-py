"""
The GIFT converter: multiple choice, true or false, numeric, short answer and
essay questions, and the GIFT missing-word form as a single-blank fill-in
question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Literal, NoReturn, assert_never

from .._markdown import locate_blank_markers
from ..types import Diacritics
from ..models import (
    AnswerPattern,
    Blank,
    ChoiceBlank,
    EssayQuestion,
    FillInQuestion,
    MultipleChoiceQuestion,
    MultipleSelectionQuestion,
    NumericBlank,
    NumericQuestion,
    OrderingQuestion,
    Question,
    ScoredChoice,
    ShortAnswerBlank,
    ShortAnswerQuestion,
    Statement,
    TrueFalseQuestion,
)
from ._base import ConversionBase, Report, fail_at
from ._moodle import (
    ImportedAnswer,
    blank_choice_scores,
    blank_id_after,
    effective_scores,
    escape_literal_markers,
    exported_general_feedback,
    exported_short_answers,
    float_answer,
    format_moodle_percent,
    general_feedback_meta,
    moodle_grade,
    moodle_score,
    numeric_answer_key,
    report_dropped_fields,
    require_automatic,
    score_from_moodle_percent,
    short_answer_key,
    split_true_false_group,
    true_false_group_stem,
)
from ._text import html_blanks_to_mdq, mdq_text
from ._common import (
    find_unescaped,
    format_num,
    join_blocks,
    numeric_tolerance,
    parse_entries,
)
from ._common import escape_text as escape_gift
from ._common import unescape_text as unescape_gift

#: The characters PHP's `trim()` removes. Moodle's GIFT reader trims with it,
#: so a Unicode space (NBSP, em space) at the edge of a text is kept.
PHP_SPACE = " \t\n\r\0\x0b"

__all__ = [
    "Gift",
    "GiftAnswer",
    "GiftTextFormat",
    "GiftOption",
    "GiftNumericOption",
    "GiftEssay",
    "GiftBoolean",
    "GiftChoice",
    "GiftShort",
    "GiftNumeric",
    "GiftBlock",
    "GiftQuestion",
    "encode_question",
    "decode_question",
    "GiftParser",
    "escape_gift",
    "unescape_gift",
]

FORMAT_TAG_REGEX = re.compile(r"\[(html|moodle|plain|markdown)\]")
BLANK_LINE_REGEX = re.compile(r"\n[ \t]*\n")


class Gift(ConversionBase["GiftQuestion"]):
    """
    GIFT is Moodle's plain-text question format.

    It supports multiple-choice, true or false, numeric, short-answer and
    essay questions, plus a "missing word" form (a `{...}` answer body
    embedded mid-sentence) that MDQ maps to a single-blank `fill-in`
    question.

    ```
    ::Q1:: Question stem {
    =Option 1
    ~Option 2
    ~Option 3
    }
    ```

    For more details: https://docs.moodle.org/502/en/GIFT_format
    """

    name = "GIFT"
    supports = frozenset(
        {
            "multiple-choice",
            "true-false",
            "numeric",
            "essay",
            "fill-in",
            "short-answer",
            # matching: not yet implemented in MDQ
            # multiple-numeric: not yet implemented in MDQ
        }
    )

    def from_mdq(self, question: Question, report: Report, /) -> GiftQuestion:
        return encode_question(question, report)

    def to_mdq(self, gift: GiftQuestion, report: Report, /) -> Question:
        return decode_question(gift, report)

    def parse(self, source: str, report: Report | None = None, /) -> GiftQuestion:
        return GiftParser(source, report or Report(self.name)).parse()


@dataclass
class GiftOption:
    """One `=`/`~` answer entry."""

    text: str
    credit: float = 1.0
    feedback: str | None = None


@dataclass
class GiftNumericOption:
    """
    One numeric answer entry: a value, tolerance, credit and feedback.
    `any_value` is Moodle's `*` ("any other answer"), which has no value.
    """

    value: float
    tolerance: float = 0.0
    credit: float = 1.0
    feedback: str | None = None
    any_value: bool = False


@dataclass
class GiftEssay:
    """An open-ended answer body: `{}`."""


@dataclass
class GiftBoolean:
    """A true or false answer body: `{T}` / `{F}`."""

    value: bool


@dataclass
class GiftChoice:
    """A multiple-choice answer body: at least one `~` entry."""

    options: list[GiftOption] = field(default_factory=list)


@dataclass
class GiftShort:
    """A short-answer body: only `=` entries."""

    options: list[GiftOption] = field(default_factory=list)


@dataclass
class GiftNumeric:
    """A numeric answer body: `#value:tolerance` or a weighted `=`-entry list."""

    options: list[GiftNumericOption] = field(default_factory=list)


type GiftAnswer = GiftEssay | GiftBoolean | GiftChoice | GiftShort | GiftNumeric
type GiftTextFormat = Literal["moodle", "html", "plain", "markdown"]


@dataclass
class GiftBlock:
    """One `::Title:: [format] stem {answer} tail` GIFT block."""

    stem: str
    answer: GiftAnswer
    tail: str = ""
    title: str | None = None
    comment: str | None = None
    text_format: GiftTextFormat = "moodle"
    general_feedback: str | None = None
    #: The whitespace between the stem and `{`, and between `}` and the tail,
    #: as the source had it (a missing-word question keeps the spaces around
    #: its blank). Layout, not content: it takes no part in equality.
    #: `None` is the single space before `{` that GIFT usually has.
    stem_space: str | None = field(default=None, compare=False)
    tail_space: str = field(default="", compare=False)

    def __str__(self) -> str:
        lines: list[str] = []
        if self.comment:
            lines.extend(f"// {line}" for line in self.comment.split("\n"))

        head = f"::{escape_gift(self.title)}:: " if self.title is not None else ""
        head += f"[{self.text_format}]"
        # The space around the answer body may hold a blank line too.
        space = " " if self.stem_space is None else self.stem_space
        if self.stem:
            head += f" {escape_gift_lines(self.stem + space)}"
            space = ""

        body = render_gift_answer(self.answer)
        if self.general_feedback:
            sep = " " if body else ""
            body = f"{body}{sep}#### {escape_gift_lines(self.general_feedback)}"

        line = f"{head}{space}{{{body}}}"
        if self.tail:
            line += escape_gift_lines(self.tail_space + self.tail)
        lines.append(line)
        return "\n".join(lines)


@dataclass
class GiftQuestion:
    """A GIFT question: one block, or several for a true or false group."""

    blocks: list[GiftBlock] = field(default_factory=list)

    def __str__(self) -> str:
        return "\n\n".join(str(block) for block in self.blocks)


def gift_block(
    question: Question,
    stem: str,
    answer: GiftAnswer,
    report: Report,
    *,
    tail: str = "",
    general_feedback: str | None = None,
) -> GiftBlock:
    """
    Build the block of `question` with the metadata every GIFT encoder
    copies. GIFT has no epilogue: the caller joins it to the stem, as Moodle
    XML does, or puts it in the tail of a missing-word question. The general
    feedback is `meta.generalFeedback`, or `general_feedback` (the answer key
    of an essay, GIFT has one `####` for both: the answer key wins and
    `meta.generalFeedback` is dropped, `general-feedback-dropped`).
    """
    meta_feedback = exported_general_feedback(question, report)
    if general_feedback is not None and meta_feedback is not None:
        report.warning(
            "general-feedback-dropped",
            "GIFT has one `####` text: `meta.generalFeedback` is dropped, and the "
            "`answerKey` is written",
            ("meta", "generalFeedback"),
        )
        meta_feedback = None
    return GiftBlock(
        stem=stem,
        answer=answer,
        tail=tail,
        title=question.title,
        comment=question.comment,
        text_format="markdown",
        general_feedback=general_feedback if meta_feedback is None else meta_feedback,
    )


#: The attributes GIFT has no place for.
_DROPPED_FIELDS = frozenset(
    {
        "id", "tags", "weight", "shuffle", "unit", "domain", "decimal_places", "content",
        "highlight", "grading", "pre_accept", "pre_reject", "author", "uuid", "locale",
    }
)

#: The keys of a question dict that are not text Moodle reads.
_NOT_TEXT_KEYS = frozenset({"id", "uuid", "author", "locale", "comment", "tags", "title", "type"})

_INDENTED_LINE_REGEX = re.compile(r"\n[ \t]+[^ \t\n]")


def report_indentation(question: Question, report: Report) -> None:
    """
    Report `indentation-lost` for each text with a line, other than the
    first, that starts with a space or tab: Moodle trims every line, so an
    indented code block or a nested list changes.
    """

    def walk(value: object, path: tuple[str | int, ...]) -> None:
        if isinstance(value, str):
            if _INDENTED_LINE_REGEX.search(value):
                report.warning(
                    "indentation-lost",
                    "GIFT has a line that starts with a space or tab: Moodle trims every "
                    "line, so an indented code block or a nested list changes",
                    path,
                )
        elif isinstance(value, dict):
            for key, item in value.items():
                if key == "meta":
                    if isinstance(item, dict) and "generalFeedback" in item:
                        walk(item["generalFeedback"], path + ("meta", "generalFeedback"))
                elif key not in _NOT_TEXT_KEYS:
                    walk(item, path + (key,))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, path + (index,))

    walk(question.to_dict(), ())


def encode_question(question: Question, report: Report) -> GiftQuestion:
    """Convert an MDQ question into a `GiftQuestion`, by its type."""
    # The grading of a multiple-choice question is in the score of each choice.
    fields = (
        _DROPPED_FIELDS - {"grading"}
        if isinstance(question, MultipleChoiceQuestion)
        else _DROPPED_FIELDS
    )
    children = frozenset({"comment", "feedback"}) if isinstance(question, TrueFalseQuestion) else frozenset({"comment"})
    report_dropped_fields(question, report, fields, children=children)
    report_indentation(question, report)
    match question:
        case MultipleChoiceQuestion():
            return GiftQuestion(blocks=[block_from_choice(question, report)])
        case ShortAnswerQuestion():
            return GiftQuestion(blocks=[block_from_short(question, report)])
        case NumericQuestion():
            return GiftQuestion(blocks=[block_from_numeric(question, report)])
        case EssayQuestion():
            return GiftQuestion(blocks=[block_from_essay(question, report)])
        case TrueFalseQuestion():
            return GiftQuestion(blocks=blocks_from_true_false(question, report))
        case FillInQuestion():
            return GiftQuestion(blocks=[block_from_fill_in(question, report)])
        case MultipleSelectionQuestion() | OrderingQuestion():
            raise AssertionError(f"{question.type!r} is excluded by `Gift.supports`")
        case _:
            assert_never(question)

def with_epilogue(question: Question) -> str:
    """The stem followed by the epilogue: after `}` GIFT would read a missing-word question."""
    return join_blocks(question.stem, question.epilogue)

def block_from_choice(question: MultipleChoiceQuestion, report: Report) -> GiftBlock:
    options = [
        GiftOption(
            text=choice.text,
            credit=moodle_score(score, report, ("choices", index, "score")),
            feedback=choice.feedback,
        )
        for index, (choice, score) in enumerate(zip(question.choices, effective_scores(question)))
    ]
    return gift_block(question, with_epilogue(question), GiftChoice(options=options), report)

def block_from_short(question: ShortAnswerQuestion, report: Report) -> GiftBlock:
    require_automatic(question.automation, report)
    options = short_options(
        question.accept, question.reject, question.incorrect_feedback, question.diacritics, report
    )
    return gift_block(question, with_epilogue(question), GiftShort(options=options), report)

def short_options(
    accept: list[AnswerPattern] | None,
    reject: list[AnswerPattern] | None,
    incorrect_feedback: str | None,
    diacritics: Diacritics,
    report: Report,
) -> list[GiftOption]:
    """
    The entries of a short answer: the literal answers, then the
    `incorrectFeedback` as Moodle's "any other answer" (`=%0%*#feedback`).
    """
    options = [
        GiftOption(text=answer.text, credit=answer.credit, feedback=answer.feedback)
        for answer in exported_short_answers(accept, reject, report, diacritics)
    ]
    if incorrect_feedback is not None:
        options.append(GiftOption(text="*", credit=0.0, feedback=incorrect_feedback))
    return options

def block_from_numeric(question: NumericQuestion, report: Report) -> GiftBlock:
    value = float_answer(question.answer, question.tolerance, report)
    tolerance = numeric_tolerance(value, question.tolerance)
    options = [GiftNumericOption(value=value, tolerance=tolerance)]
    if question.incorrect_feedback is not None:
        options.append(
            GiftNumericOption(
                value=0.0, credit=0.0, feedback=question.incorrect_feedback, any_value=True
            )
        )
    answer = GiftNumeric(options=options)
    return gift_block(question, with_epilogue(question), answer, report)

def block_from_essay(question: EssayQuestion, report: Report) -> GiftBlock:
    return gift_block(
        question, with_epilogue(question), GiftEssay(), report, general_feedback=question.answer_key
    )

def blocks_from_true_false(question: TrueFalseQuestion, report: Report) -> list[GiftBlock]:
    group_stem = true_false_group_stem(question)
    group_feedback = exported_general_feedback(question, report)
    blocks = []
    for i, statement in enumerate(question.choices):
        stem = f"{group_stem}\n\n{statement.text}" if group_stem else statement.text
        blocks.append(
            GiftBlock(
                stem=stem,
                answer=GiftBoolean(value=statement.correct),
                title=question.title if i == 0 else None,
                comment=question.comment if i == 0 else None,
                text_format="markdown",
                general_feedback=group_feedback if i == 0 else None,
            )
        )
    return blocks

def block_from_fill_in(question: FillInQuestion, report: Report) -> GiftBlock:
    if len(question.blanks) != 1:
        report.error(
            "multiple-blanks",
            "cannot convert to GIFT: fill-in question must have exactly one blank",
            ("blanks",),
        )
    blank = question.blanks[0]
    marker = f"[^{blank.id}]"
    # Code, `[^x](url)` links and autolinks are literal text, not blanks.
    span = next(
        (
            m.span
            for m in locate_blank_markers(question.stem)
            if m.id == blank.id and m.span is not None
        ),
        None,
    )
    if span is None:
        report.error(
            "blank-marker-mismatch",
            f"cannot convert to GIFT: stem does not contain blank marker {marker!r}",
            ("stem",),
        )
    stem_part, tail_part = question.stem[: span[0]], question.stem[span[1] :]

    answer: GiftAnswer
    with report.under("blanks", 0):
        match blank:
            case ChoiceBlank():
                choice_options = [
                    GiftOption(
                        text=choice.text,
                        credit=moodle_score(score, report, ("choices", index, "score")),
                        feedback=choice.feedback,
                    )
                    for index, (choice, score) in enumerate(
                        zip(blank.choices, blank_choice_scores(blank))
                    )
                ]
                answer = GiftChoice(options=choice_options)
            case ShortAnswerBlank():
                require_automatic(blank.automation(question.unmatched), report, ())
                answer = GiftShort(
                    options=short_options(
                        blank.accept,
                        blank.reject,
                        blank.incorrect_feedback,
                        question.diacritics,
                        report,
                    )
                )
            case NumericBlank():
                value = float_answer(blank.answer, blank.tolerance, report)
                tolerance = numeric_tolerance(value, blank.tolerance)
                numeric_options = [GiftNumericOption(value=value, tolerance=tolerance)]
                if blank.incorrect_feedback is not None:
                    numeric_options.append(
                        GiftNumericOption(
                            value=0.0,
                            credit=0.0,
                            feedback=blank.incorrect_feedback,
                            any_value=True,
                        )
                    )
                answer = GiftNumeric(options=numeric_options)
            case _:
                assert_never(blank)

    # The epilogue holds no blank: once it joins the tail, its `[^id]` is
    # escaped, or the import would read it as a blank.
    epilogue = escape_literal_markers(question.epilogue or "", set())
    tail = "\n".join(
        part for part in (tail_part.strip(PHP_SPACE), epilogue.strip(PHP_SPACE)) if part
    )
    stem = stem_part.strip(PHP_SPACE)
    block = gift_block(question, stem, answer, report, tail=tail)
    if stem:
        block.stem_space = stem_part[len(stem_part.rstrip(PHP_SPACE)) :]
    if tail_part.strip(PHP_SPACE):
        block.tail_space = tail_part[: len(tail_part) - len(tail_part.lstrip(PHP_SPACE))]
    return block



def decode_question(gift: GiftQuestion, report: Report) -> Question:
    """A single block converts directly; several blocks must form a true or false group."""
    if not gift.blocks:
        report.error("no-question", "GIFT question has no blocks")
    blocks = [markdown_block(block, report) for block in gift.blocks]
    if len(blocks) == 1:
        return block_to_mdq(blocks[0], report)
    if all(isinstance(b.answer, GiftBoolean) for b in blocks):
        return true_false_from_blocks(blocks, report)
    report.error(
        "multiple-questions",
        "a GIFT question group with more than one block is only "
        "supported when every block is a true or false statement"
    )

def markdown_block(block: GiftBlock, report: Report) -> GiftBlock:
    """
    The block with its Markdown texts in MDQ's Markdown: the stem, tail,
    general feedback, choice texts and every feedback of a `[plain]` or `[html]`
    block are converted (`mdq_text`). `[html]` becomes an HTML block only in a
    whole block of the document: the stem of a question without a tail and the
    general feedback. The text of a short answer or numeric option is not
    Markdown, so it is kept.
    """
    block_format = block.text_format
    if block_format not in ("plain", "html"):
        return block

    def convert(text: str | None, *, whole: bool = False) -> str | None:
        return None if text is None else mdq_text(text, block_format, block=whole, html=report.html)

    def convert_option(option: GiftOption, *, text: bool) -> GiftOption:
        return replace(
            option,
            text=mdq_text(option.text, block.text_format, html=report.html) if text else option.text,
            feedback=convert(option.feedback),
        )

    answer = block.answer
    match answer:
        case GiftChoice():
            answer = GiftChoice([convert_option(o, text=True) for o in answer.options])
        case GiftShort():
            answer = GiftShort([convert_option(o, text=False) for o in answer.options])
        case GiftNumeric():
            answer = GiftNumeric(
                [replace(o, feedback=convert(o.feedback)) for o in answer.options]
            )
        case GiftEssay() | GiftBoolean():
            pass
        case _:
            assert_never(answer)
    if report.html == "markdown" and block_format == "html" and block.tail:
        # A missing-word stem is converted as a whole, around its blank.
        stem, tail = block.stem, block.tail
    else:
        stem = mdq_text(block.stem, block_format, block=not block.tail, html=report.html)
        tail = mdq_text(block.tail, block_format, html=report.html)
    return replace(
        block,
        stem=stem,
        tail=tail,
        general_feedback=convert(block.general_feedback, whole=True),
        answer=answer,
    )

def block_to_mdq(block: GiftBlock, report: Report) -> Question:
    answer = block.answer
    meta = general_feedback_meta(block.general_feedback)

    match answer:
        case GiftEssay():
            stem = block.stem
            if block.tail:
                report.warning(
                    "missing-word-joined",
                    "an essay has no blank: the text after `{}` is joined to the stem",
                    ("stem",),
                )
                stem = f"{stem} {block.tail}"
            return EssayQuestion(
                stem=stem,
                answer_key=block.general_feedback,
                title=block.title,
                comment=block.comment,
            )
        case GiftBoolean() if not block.tail:
            return MultipleChoiceQuestion(
                stem=block.stem,
                choices=[
                    ScoredChoice(text="True", score=1.0 if answer.value else 0.0),
                    ScoredChoice(text="False", score=0.0 if answer.value else 1.0),
                ],
                meta=meta,
                title=block.title,
                comment=block.comment,
            )
        case GiftChoice() | GiftShort() | GiftNumeric() | GiftBoolean():
            pass
        case _:
            assert_never(answer)

    if block.tail:
        with report.under("blanks", 0):
            blank = blank_from_answer(answer, report)
        blank = blank.model_copy(update={"id": blank_id_after(block.stem + block.tail, blank.id)})
        stem = f"{block.stem}{block.stem_space or ''}[^{blank.id}]{block.tail_space}{block.tail}"
        if block.text_format == "html":
            stem = html_blanks_to_mdq(stem, report)
        stem = escape_literal_markers(stem, {blank.id})
        return FillInQuestion(
            stem=stem, blanks=[blank], meta=meta,
                title=block.title, comment=block.comment
        )

    match answer:
        case GiftChoice():
            return MultipleChoiceQuestion(
                stem=block.stem,
                choices=[
                    ScoredChoice(text=o.text, score=o.credit, feedback=o.feedback)
                    for o in answer.options
                ],
                meta=meta,
                title=block.title,
                comment=block.comment,
            )
        case GiftShort():
            short = short_answer_key(imported_options(answer.options), report)
            return ShortAnswerQuestion(
                stem=block.stem,
                accept=short.accept,
                reject=short.reject,
                incorrect_feedback=short.incorrect_feedback,
                meta=meta,
                title=block.title,
                comment=block.comment,
            )
        case GiftNumeric():
            numeric = numeric_answer_key(
                imported_numeric_options(answer.options), report
            )
            return NumericQuestion(
                stem=block.stem,
                answer=numeric.answer,
                tolerance=numeric.tolerance,
                incorrect_feedback=numeric.incorrect_feedback,
                meta=meta,
                title=block.title,
                comment=block.comment,
            )
        case GiftEssay() | GiftBoolean():
            raise AssertionError("an essay and a true or false answer are converted above")
        case _:
            assert_never(answer)

def imported_options(options: list[GiftOption]) -> list[ImportedAnswer]:
    """The short-answer options of a GIFT body, as the answers of `short_answer_key`."""
    return [ImportedAnswer(o.text, o.credit, o.feedback) for o in options]


def imported_numeric_options(options: list[GiftNumericOption]) -> list[ImportedAnswer]:
    """The numeric options of a GIFT body, as the answers of `numeric_answer_key`."""
    return [
        ImportedAnswer("*" if o.any_value else format_num(o.value), o.credit, o.feedback, o.tolerance)
        for o in options
    ]


def blank_from_answer(answer: GiftAnswer, report: Report) -> Blank:
    match answer:
        case GiftChoice():
            return ChoiceBlank(
                id="blank",
                choices=[
                    ScoredChoice(text=o.text, score=o.credit, feedback=o.feedback)
                    for o in answer.options
                ],
            )
        case GiftShort():
            short = short_answer_key(imported_options(answer.options), report)
            return ShortAnswerBlank(
                id="blank",
                accept=short.accept,
                reject=short.reject,
                incorrect_feedback=short.incorrect_feedback,
            )
        case GiftNumeric():
            numeric = numeric_answer_key(
                imported_numeric_options(answer.options), report
            )
            return NumericBlank(
                id="blank",
                answer=numeric.answer,
                tolerance=numeric.tolerance,
                incorrect_feedback=numeric.incorrect_feedback,
            )
        case GiftBoolean():
            return ChoiceBlank(
                id="blank",
                choices=[
                    ScoredChoice(text="True", score=1.0 if answer.value else 0.0),
                    ScoredChoice(text="False", score=0.0 if answer.value else 1.0),
                ],
            )
        case GiftEssay():
            raise AssertionError("an essay is joined to its tail before it gets here")
        case _:
            assert_never(answer)

def true_false_from_blocks(blocks: list[GiftBlock], report: Report) -> TrueFalseQuestion:
    group_stem, statement_texts = split_true_false_group([b.stem for b in blocks])
    first = blocks[0]
    for block in blocks[1:]:
        if block.title is not None and block.title != first.title:
            report.warning(
                "field-dropped",
                f"the title {block.title!r} of a later statement is dropped: the group "
                f"keeps the title of the first one, {first.title!r}",
                ("title",),
            )

    choices = []
    for text, block in zip(statement_texts, blocks):
        assert isinstance(block.answer, GiftBoolean)
        choices.append(Statement(text=text.strip(PHP_SPACE), correct=block.answer.value))

    return TrueFalseQuestion(
        stem=group_stem,
        choices=choices,
        meta=general_feedback_meta(*(b.general_feedback for b in blocks)),
        title=first.title,
        comment=first.comment,
    )


class GiftParser:
    """
    Character-level GIFT parser.

    GIFT is not line-oriented (an answer body may span several lines), so
    parsing scans `self.source` directly by character offset.
    """

    def __init__(self, source: str, report: Report | None = None):
        self.source = source
        self.report = report or Report("GIFT")

    def parse(self) -> GiftQuestion:
        blocks = []
        for raw, offset, blank_line in split_blocks(self.source):
            if blank_line is not None:
                self.report.warning(
                    "gift-blank-line",
                    "the question has a blank line before or inside its answer body: Moodle "
                    "splits a question at every blank line",
                    (),
                    blank_line + 1,
                )
            blocks.append(self.parse_block(raw, offset))
        if not blocks:
            self.fail("no GIFT question found", 0)
        return GiftQuestion(blocks=blocks)

    def parse_block(self, raw: str, offset: int) -> GiftBlock:
        lines = raw.split("\n")
        comment_lines: list[str] = []
        index = 0
        consumed = offset
        while index < len(lines) and lines[index].lstrip(PHP_SPACE).startswith("//"):
            comment_lines.append(lines[index].lstrip(PHP_SPACE)[2:].strip(PHP_SPACE))
            consumed += len(lines[index]) + 1
            index += 1
        rest = "\n".join(lines[index:])
        comment = "\n".join(comment_lines) if comment_lines else None

        pos = 0
        title: str | None = None
        if rest.startswith("::"):
            end = find_unescaped(rest, "::", 2)
            if end == -1:
                self.fail("missing closing '::' for title", consumed)
            title = unescape_gift(rest[2:end])
            pos = end + 2

        text_format: GiftTextFormat = "moodle"
        ws_match = re.match(r"[ \t]*", rest[pos:])
        tag_start = pos + (ws_match.end() if ws_match else 0)
        match = FORMAT_TAG_REGEX.match(rest, tag_start)
        if match:
            tag = match.group(1)
            if tag == "html":
                text_format = "html"
            elif tag == "plain":
                text_format = "plain"
            elif tag == "markdown":
                text_format = "markdown"
            pos = match.end()

        brace_pos = find_unescaped(rest, "{", pos)
        if brace_pos == -1:
            self.fail("missing answer '{...}' body", consumed + pos)
        stem_raw = unescape_gift(rest[pos:brace_pos])
        stem = stem_raw.strip(PHP_SPACE)
        stem_space = stem_raw[len(stem_raw.rstrip(PHP_SPACE)) :] if stem else None
        pos = brace_pos + 1

        close_pos = find_unescaped(rest, "}", pos)
        if close_pos == -1:
            self.fail("missing closing '}' for answer body", consumed + pos)
        body_raw = rest[pos:close_pos]
        body_offset = consumed + pos
        pos = close_pos + 1

        tail_raw = rest[pos:]
        extra_open = find_unescaped(tail_raw, "{")
        if extra_open != -1:
            self.fail(
                "only one {...} answer body is allowed per block",
                consumed + pos + extra_open,
            )
        tail_unescaped = unescape_gift(tail_raw)
        tail = tail_unescaped.strip(PHP_SPACE)
        tail_space = (
            tail_unescaped[: len(tail_unescaped) - len(tail_unescaped.lstrip(PHP_SPACE))]
            if tail
            else ""
        )

        answer, general_feedback = self.parse_answer(body_raw, body_offset)
        return GiftBlock(
            stem=stem,
            answer=answer,
            tail=tail,
            title=title,
            comment=comment,
            text_format=text_format,
            general_feedback=general_feedback,
            stem_space=stem_space,
            tail_space=tail_space,
        )

    def parse_answer(self, body_raw: str, offset: int) -> tuple[GiftAnswer, str | None]:
        fb_pos = find_unescaped(body_raw, "####")
        if fb_pos != -1:
            content_raw = body_raw[:fb_pos]
            general_feedback = unescape_gift(body_raw[fb_pos + 4 :]).strip(PHP_SPACE) or None
        else:
            content_raw = body_raw
            general_feedback = None

        content = content_raw.strip(PHP_SPACE)
        if content == "":
            return GiftEssay(), general_feedback

        upper = content.upper()
        if upper in ("T", "TRUE", "F", "FALSE"):
            return GiftBoolean(value=upper.startswith("T")), general_feedback

        if content.startswith("#"):
            numeric_options = self.parse_numeric_options(content, offset)
            return GiftNumeric(options=numeric_options), general_feedback

        if find_unescaped(content_raw, "~") != -1:
            return GiftChoice(options=self.parse_options(content_raw)), general_feedback

        text_options = self.parse_options(content_raw)
        if not text_options:
            self.fail("could not classify empty or malformed answer body", offset)
        return GiftShort(options=text_options), general_feedback

    def parse_options(self, content: str) -> list[GiftOption]:
        return [
            GiftOption(
                text=unescape_gift(entry.text).strip(PHP_SPACE),
                credit=entry.credit,
                feedback=unescape_feedback(entry.feedback),
            )
            for entry in parse_entries(content, "=~", score_from_moodle_percent)
        ]

    def parse_numeric_options(
        self, content: str, offset: int
    ) -> list[GiftNumericOption]:
        body = content[1:]
        if find_unescaped(body, "=") == -1:
            value, tolerance = self.parse_numeric_spec(body.strip(PHP_SPACE), offset)
            return [GiftNumericOption(value=value, tolerance=tolerance)]

        options = []
        for entry in parse_entries(body, "=~", score_from_moodle_percent):
            spec = entry.text.strip(PHP_SPACE)
            # `=%0%*#fb` is MDQ's form of "any other answer"; `~#fb` is Moodle's own.
            any_value = spec == "*" or (spec == "" and entry.credit == 0.0)
            value, tolerance = (0.0, 0.0) if any_value else self.parse_numeric_spec(spec, offset)
            options.append(
                GiftNumericOption(
                    value=value,
                    tolerance=tolerance,
                    credit=entry.credit,
                    feedback=unescape_feedback(entry.feedback),
                    any_value=any_value,
                )
            )
        return options

    def parse_numeric_spec(self, spec: str, offset: int) -> tuple[float, float]:
        try:
            if ".." in spec:
                low_s, high_s = spec.split("..", 1)
                low, high = float(low_s), float(high_s)
                return (low + high) / 2, (high - low) / 2
            if ":" in spec:
                value_s, tol_s = spec.split(":", 1)
                return float(value_s), float(tol_s)
            return float(spec), 0.0
        except ValueError:
            self.fail(f"invalid numeric answer: {spec!r}", offset)

    def fail(self, message: str, pos: int) -> NoReturn:
        """Raise a `ParserError` located at absolute source offset `pos`."""
        fail_at(self.source, pos, message)


def unescape_feedback(raw: str | None) -> str | None:
    """The text of an entry's `#feedback`, or `None` if it is missing or blank."""
    return (unescape_gift(raw).strip(PHP_SPACE) or None) if raw else None


def render_gift_answer(answer: GiftAnswer) -> str:
    """Render a GIFT answer body's content, without the enclosing braces."""
    match answer:
        case GiftEssay():
            return ""
        case GiftBoolean():
            return "TRUE" if answer.value else "FALSE"
        case GiftChoice():
            return " ".join(render_gift_option(o) for o in answer.options)
        case GiftShort():
            return " ".join(render_gift_short_option(o) for o in answer.options)
        case GiftNumeric():
            return render_gift_numeric(answer.options)
        case _:
            assert_never(answer)


def render_gift_numeric(options: list[GiftNumericOption]) -> str:
    """Render a numeric answer body: the compact `#value:tol` form when possible."""
    if len(options) == 1 and options[0].credit == 1.0 and not options[0].feedback:
        opt = options[0]
        if opt.tolerance:
            return f"#{format_num(opt.value)}:{format_num(opt.tolerance)}"
        return f"#{format_num(opt.value)}"

    parts = []
    for opt in options:
        entry = "="
        if opt.credit != 1.0:
            entry += f"%{format_credit(opt.credit)}%"
        entry += "*" if opt.any_value else format_num(opt.value)
        if opt.tolerance:
            entry += f":{format_num(opt.tolerance)}"
        if opt.feedback:
            entry += f"#{escape_gift_lines(opt.feedback)}"
        parts.append(entry)
    return "# " + " ".join(parts)


def render_gift_option(option: GiftOption) -> str:
    """
    Render one choice answer entry: `=` for full credit, `~` otherwise. A
    text that starts with `%` gets an explicit `%credit%`, or it reads as one.
    """
    if option.text.startswith("%"):
        marker = "=" if option.credit == 1.0 else "~"
        entry = f"{marker}%{format_credit(option.credit)}%"
    elif option.credit == 1.0:
        entry = "="
    elif option.credit == 0.0:
        entry = "~"
    else:
        entry = f"~%{format_credit(option.credit)}%"
    return entry + render_gift_option_tail(option)


def render_gift_short_option(option: GiftOption) -> str:
    """
    Render one short-answer entry: always the `=` delimiter (a `~` would
    misclassify the body as a choice on reparse), with credit carried by
    a `%NN%` tag whenever it isn't the default 1.0 or the text starts with `%`.
    """
    entry = "="
    if option.credit != 1.0 or option.text.startswith("%"):
        entry += f"%{format_credit(option.credit)}%"
    return entry + render_gift_option_tail(option)


def render_gift_option_tail(option: GiftOption) -> str:
    """Render an option's escaped text and optional `#feedback` suffix."""
    tail = escape_gift_lines(option.text)
    if option.feedback:
        tail += f"#{escape_gift_lines(option.feedback)}"
    return tail


def escape_gift_lines(text: str) -> str:
    r"""
    Escape `text` for GIFT and encode each blank line with the `\n` escape
    (`a\n\nb` is the two lines `a\n` and `b`), since Moodle splits a question at
    every blank line. Moodle reads both forms back as `a\n\nb`.
    """
    lines: list[str] = []
    for line in escape_gift(text).split("\n"):
        if lines and not line.strip(PHP_SPACE):
            lines[-1] += "\\n"
        else:
            lines.append(line)
    return "\n".join(lines)


def format_credit(credit: float) -> str:
    """
    Render a 0..1 credit fraction as a GIFT percentage, e.g. `0.5` ->
    `"50"`. A Moodle grade is written as Moodle writes it (5/6 is
    `"83.33333"`).
    """
    grade = moodle_grade(credit)
    if grade is not None:
        return format_moodle_percent(grade)
    return format_num(credit * 100)


def split_blocks(source: str) -> list[tuple[str, int, int | None]]:
    """
    Split GIFT source into `(block_text, start_offset, blank_line)` triples.

    Blocks are separated by blank lines, except inside an unescaped
    `{...}` answer body, which may itself span blank lines, and before the
    `{`. `blank_line` is the 0-based line of the first blank line that a block
    keeps (Moodle would split the question there), or `None`.
    """
    blocks: list[tuple[str, int, int | None]] = []
    current: list[str] = []
    current_start: int | None = None
    blank_line: int | None = None
    depth = 0
    closed = False
    in_comment = True  # still within the block's leading `//` comment lines
    offset = 0

    for lineno, line in enumerate(source.split("\n")):
        blank = not line.strip(PHP_SPACE)
        if blank and not current:
            offset += len(line) + 1
            continue  # blank lines between blocks
        if blank and depth == 0 and closed:
            blocks.append(("\n".join(current), current_start or 0, blank_line))
            current = []
            current_start = None
            blank_line = None
            closed = False
            in_comment = True
            offset += len(line) + 1
            continue
        if blank and not in_comment and blank_line is None:
            blank_line = lineno

        if current_start is None:
            current_start = offset
        current.append(line)
        # A leading `// ...` comment line's braces don't count towards the
        # answer body: `parse_block` strips these lines before parsing.
        if in_comment and line.lstrip(PHP_SPACE).startswith("//"):
            pass
        else:
            in_comment = False
            depth, closed = update_brace_state(line, depth, closed)
        offset += len(line) + 1

    if current:
        blocks.append(("\n".join(current), current_start or 0, blank_line))
    return blocks


def update_brace_state(line: str, depth: int, closed: bool) -> tuple[int, bool]:
    """
    Update unescaped-brace nesting `depth` after scanning `line`.

    `closed` becomes true once the block's single `{...}` body has been
    seen and closed -- only then does a blank line end the block, since a
    stem may itself contain a blank line before its body starts.
    """
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                closed = True
        i += 1
    return depth, closed
