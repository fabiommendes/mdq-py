from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from collections.abc import Sequence
from typing import ClassVar, Literal, TypedDict, assert_never

from .._markdown import UNICODE_SPACE, locate_blank_markers
from ..models import (
    AnswerPattern,
    Blank,
    BooleanChoice,
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
from ..types import EssayContent
from ._base import (
    blank_choice_scores,
    split_true_false_group,
    true_false_group_stem,
    effective_scores,
    ConversionBase,
    ImportedAnswer,
    exported_general_feedback,
    general_feedback_meta,
    mdq_text,
    exported_short_answers,
    float_answer,
    numeric_answer_key,
    short_answer_key,
    require_automatic,
    moodle_percent,
    score_from_moodle_percent,
)
from ._common import (
    escape_text,
    find_unescaped,
    format_num,
    join_blocks,
    numeric_tolerance,
    parse_entries,
    unescape_text,
)
from ._string_parser import StringParser

__all__ = [
    "MoodleXml",
    "MoodleXmlType",
    "MoodleTextFormat",
    "ClozeKind",
    "MoodleAnswer",
    "MoodleCloze",
    "MoodleXmlBlock",
    "MultichoiceBlock",
    "TrueFalseBlock",
    "ShortAnswerBlock",
    "NumericalBlock",
    "EssayBlock",
    "MultianswerBlock",
    "MoodleXmlQuestion",
    "encode_question",
    "decode_question",
    "MoodleXmlParser",
    "parse_cloze",
    "render_cloze",
]

type MoodleXmlType = Literal[
    "multichoice", "truefalse", "shortanswer", "numerical", "essay", "multianswer"
]
type MoodleTextFormat = Literal["html", "moodle_auto_format", "plain_text", "markdown"]

#: The `format` attribute values Moodle recognizes, except `wiki_like`.
MOODLE_TEXT_FORMATS: tuple[MoodleTextFormat, ...] = (
    "html",
    "moodle_auto_format",
    "plain_text",
    "markdown",
)
type ClozeKind = Literal["SHORTANSWER", "NUMERICAL", "MULTICHOICE"]

CLOZE_KIND_ALIASES: dict[str, ClozeKind] = {
    "SHORTANSWER": "SHORTANSWER",
    "SA": "SHORTANSWER",
    "NUMERICAL": "NUMERICAL",
    "NM": "NUMERICAL",
    "MULTICHOICE": "MULTICHOICE",
    "MC": "MULTICHOICE",
    "MULTICHOICE_V": "MULTICHOICE",
    "MULTICHOICE_H": "MULTICHOICE",
    "MCV": "MULTICHOICE",
    "MCH": "MULTICHOICE",
}
CLOZE_HEADER_REGEX = re.compile(r"\{(\d+):([A-Za-z_]+):")

#: The format name in error messages.
_FORMAT = "Moodle XML"



class _BlockFields(TypedDict):
    """The `_BlockBase` fields, as the arguments of any block."""

    questiontext: str
    name: str | None
    idnumber: str | None
    text_format: MoodleTextFormat
    general_feedback: str | None
    general_feedback_format: MoodleTextFormat | None
    default_grade: float
    tags: list[str]


class _BlockMeta(TypedDict):
    """The `_BlockBase` fields that come from the metadata of an MDQ question."""

    name: str | None
    idnumber: str | None
    tags: list[str]
    default_grade: float
    general_feedback: str | None


class _QuestionMeta(TypedDict):
    """The MDQ question fields that come from the metadata of a block."""

    title: str | None
    id: str | None
    tags: list[str]
    weight: float
    meta: dict[str, object] | None


def _block_meta(question: Question) -> _BlockMeta:
    """The metadata of `question`, as the arguments of a block."""
    return {
        "name": question.title,
        "idnumber": question.id,
        "tags": list(question.tags),
        "default_grade": question.weight,
        "general_feedback": exported_general_feedback(question, format=_FORMAT),
    }


def _question_meta(block: _BlockBase) -> _QuestionMeta:
    """The metadata of `block`, as the arguments of an MDQ question."""
    return {
        "title": block.name,
        "id": block.idnumber,
        "tags": list(block.tags),
        "weight": block.default_grade,
        "meta": general_feedback_meta(block.general_feedback),
    }


def _moodle_shuffle(value: bool | Literal["inherit"]) -> bool | None:
    """An MDQ `shuffle`, as Moodle's optional `shuffleanswers`."""
    return None if value == "inherit" else value


def _mdq_shuffle(value: bool | None) -> bool | Literal["inherit"]:
    """Moodle's optional `shuffleanswers`, as an MDQ `shuffle`."""
    return "inherit" if value is None else value


class MoodleXml(ConversionBase["MoodleXmlQuestion"]):
    """
    Moodle XML is Moodle's question-bank interchange format.

    ```xml
    <quiz>
      <question type="multichoice">
        <name><text>Capital</text></name>
        <questiontext format="markdown"><text>What is the capital of Brazil?</text></questiontext>
        <answer fraction="100"><text>Brasilia</text></answer>
        <answer fraction="0"><text>Rio de Janeiro</text></answer>
      </question>
    </quiz>
    ```

    For more details: https://docs.moodle.org/502/en/Moodle_XML_format
    """

    supports = frozenset(
        {
            "multiple-choice",
            "multiple-selection",
            "true-false",
            "numeric",
            "short-answer",
            "essay",
            "fill-in",
        }
    )

    def from_mdq(self, question: Question) -> MoodleXmlQuestion:
        return encode_question(question)

    def to_mdq(self, moodle: MoodleXmlQuestion) -> Question:
        return decode_question(moodle)

    def parse(self, source: str) -> MoodleXmlQuestion:
        return MoodleXmlParser(source).parse()


@dataclass
class MoodleAnswer:
    """One `<answer>` (or cloze option) entry."""

    text: str
    fraction: float = 0.0
    feedback: str | None = None
    tolerance: float | None = None  # numerical only
    #: The `format` of the `<answer>` and of its `<feedback>` as read from a
    #: file (`None`: that of the question). A rendered answer takes the format
    #: of its question, so these take no part in equality.
    text_format: MoodleTextFormat | None = field(default=None, compare=False)
    feedback_format: MoodleTextFormat | None = field(default=None, compare=False)


@dataclass
class MoodleCloze:
    """One inline blank of a `multianswer` question."""

    kind: ClozeKind
    answers: list[MoodleAnswer]
    weight: int = 1


@dataclass
class _BlockBase:
    """The fields every `<question>` element has."""

    type: ClassVar[MoodleXmlType]

    questiontext: str
    name: str | None = None
    idnumber: str | None = None
    text_format: MoodleTextFormat = "markdown"
    general_feedback: str | None = None
    default_grade: float = 1.0
    tags: list[str] = field(default_factory=list)
    #: The `format` of `<generalfeedback>` as read from a file (`None`: that
    #: of the question). Not rendered, so not compared.
    general_feedback_format: MoodleTextFormat | None = field(default=None, compare=False)

    def __str__(self) -> str:
        return render_element(self.to_element())

    def to_element(self) -> ET.Element:
        """Build the `<question>` element of this block."""
        question_el = ET.Element("question", attrib={"type": self.type})
        if self.name is not None:
            name_el = ET.SubElement(question_el, "name")
            ET.SubElement(name_el, "text").text = self.name
        if self.idnumber is not None:
            ET.SubElement(question_el, "idnumber").text = self.idnumber

        questiontext_el = ET.SubElement(
            question_el, "questiontext", attrib={"format": self.text_format}
        )
        ET.SubElement(questiontext_el, "text").text = self.questiontext

        if self.general_feedback is not None:
            feedback_el = ET.SubElement(
                question_el, "generalfeedback", attrib={"format": self.text_format}
            )
            ET.SubElement(feedback_el, "text").text = self.general_feedback

        ET.SubElement(question_el, "defaultgrade").text = format_num(self.default_grade)

        self._add_details(question_el)

        if self.tags:
            tags_el = ET.SubElement(question_el, "tags")
            for tag in self.tags:
                tag_el = ET.SubElement(tags_el, "tag")
                ET.SubElement(tag_el, "text").text = tag
        return question_el

    def _add_details(self, question_el: ET.Element) -> None:
        """Add the elements that only this type of question has."""

    def _add_answers(self, question_el: ET.Element, answers: list[MoodleAnswer]) -> None:
        """Add one `<answer>` element per answer."""
        for answer in answers:
            answer_el = ET.SubElement(
                question_el,
                "answer",
                attrib={
                    "fraction": format_num(answer.fraction),
                    "format": self.text_format,
                },
            )
            ET.SubElement(answer_el, "text").text = answer.text
            if answer.feedback is not None:
                answer_feedback_el = ET.SubElement(
                    answer_el, "feedback", attrib={"format": self.text_format}
                )
                ET.SubElement(answer_feedback_el, "text").text = answer.feedback
            if answer.tolerance is not None:
                ET.SubElement(answer_el, "tolerance").text = format_num(answer.tolerance)


@dataclass
class MultichoiceBlock(_BlockBase):
    """A `multichoice` question. `single` is `None` when the element has no `<single>`."""

    type: ClassVar[MoodleXmlType] = "multichoice"

    answers: list[MoodleAnswer] = field(default_factory=list)
    single: bool | None = None
    shuffle_answers: bool | None = None

    def _add_details(self, question_el: ET.Element) -> None:
        if self.single is not None:
            ET.SubElement(question_el, "single").text = bool_to_moodle(self.single)
        if self.shuffle_answers is not None:
            ET.SubElement(question_el, "shuffleanswers").text = bool_to_moodle(
                self.shuffle_answers
            )
        self._add_answers(question_el, self.answers)


@dataclass
class TrueFalseBlock(_BlockBase):
    """A `truefalse` question."""

    type: ClassVar[MoodleXmlType] = "truefalse"

    answers: list[MoodleAnswer] = field(default_factory=list)
    shuffle_answers: bool | None = None

    def _add_details(self, question_el: ET.Element) -> None:
        self._add_answers(question_el, self.answers)


@dataclass
class ShortAnswerBlock(_BlockBase):
    """A `shortanswer` question."""

    type: ClassVar[MoodleXmlType] = "shortanswer"

    answers: list[MoodleAnswer] = field(default_factory=list)

    def _add_details(self, question_el: ET.Element) -> None:
        ET.SubElement(question_el, "usecase").text = "0"
        self._add_answers(question_el, self.answers)


@dataclass
class NumericalBlock(_BlockBase):
    """A `numerical` question."""

    type: ClassVar[MoodleXmlType] = "numerical"

    answers: list[MoodleAnswer] = field(default_factory=list)
    unit: str | None = None

    def _add_details(self, question_el: ET.Element) -> None:
        self._add_answers(question_el, self.answers)
        if self.unit is not None:
            units_el = ET.SubElement(question_el, "units")
            unit_el = ET.SubElement(units_el, "unit")
            ET.SubElement(unit_el, "unit_name").text = self.unit
            ET.SubElement(unit_el, "unit_multiplier").text = "1"


@dataclass
class EssayBlock(_BlockBase):
    """An `essay` question."""

    type: ClassVar[MoodleXmlType] = "essay"

    grader_info: str | None = None
    response_format: str | None = None
    #: The `format` of `<graderinfo>` as read from a file (`None`: that of the question).
    grader_info_format: MoodleTextFormat | None = field(default=None, compare=False)

    def _add_details(self, question_el: ET.Element) -> None:
        if self.grader_info is not None:
            graderinfo_el = ET.SubElement(
                question_el, "graderinfo", attrib={"format": self.text_format}
            )
            ET.SubElement(graderinfo_el, "text").text = self.grader_info
        if self.response_format is not None:
            ET.SubElement(question_el, "responseformat").text = self.response_format


@dataclass
class MultianswerBlock(_BlockBase):
    """A `multianswer` (cloze) question: its blanks live inside `questiontext`."""

    type: ClassVar[MoodleXmlType] = "multianswer"

    shuffle_answers: bool | None = None


type MoodleXmlBlock = (
    MultichoiceBlock
    | TrueFalseBlock
    | ShortAnswerBlock
    | NumericalBlock
    | EssayBlock
    | MultianswerBlock
)


@dataclass
class MoodleXmlQuestion:
    """A Moodle XML question: one block, or several for a true/false group."""

    blocks: Sequence[MoodleXmlBlock] = field(default_factory=list)

    def __str__(self) -> str:
        quiz = ET.Element("quiz")
        for block in self.blocks:
            quiz.append(block.to_element())
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{render_element(quiz)}'



def encode_question(question: Question) -> MoodleXmlQuestion:
    """Convert an MDQ question into a `MoodleXmlQuestion`, by its type."""
    match question:
        case MultipleChoiceQuestion():
            return MoodleXmlQuestion(blocks=[block_from_choice(question)])
        case MultipleSelectionQuestion():
            return MoodleXmlQuestion(blocks=[block_from_selection(question)])
        case TrueFalseQuestion():
            return MoodleXmlQuestion(blocks=blocks_from_true_false(question))
        case NumericQuestion():
            return MoodleXmlQuestion(blocks=[block_from_numeric(question)])
        case ShortAnswerQuestion():
            return MoodleXmlQuestion(blocks=[block_from_short(question)])
        case EssayQuestion():
            return MoodleXmlQuestion(blocks=[block_from_essay(question)])
        case FillInQuestion():
            return MoodleXmlQuestion(blocks=[block_from_fill_in(question)])
        case OrderingQuestion():
            raise ValueError(
                f"Moodle XML does not support {question.type!r} questions"
            )
        case _:
            assert_never(question)

def block_from_choice(question: MultipleChoiceQuestion) -> MultichoiceBlock:
    answers = [
        MoodleAnswer(
            text=choice.text,
            fraction=moodle_percent(score, format=_FORMAT),
            feedback=choice.feedback,
        )
        for choice, score in zip(question.choices, effective_scores(question))
    ]
    return MultichoiceBlock(
        questiontext=join_blocks(question.stem, question.epilogue),
        answers=answers,
        single=True,
        shuffle_answers=_moodle_shuffle(question.shuffle),
        **_block_meta(question),
    )

def block_from_selection(question: MultipleSelectionQuestion
) -> MultichoiceBlock:
    n_correct = sum(1 for c in question.choices if c.correct)
    n_incorrect = len(question.choices) - n_correct
    answers = []
    for choice in question.choices:
        if choice.correct:
            share = 1 / n_correct if n_correct else 0.0
        else:
            share = -1 / n_incorrect if n_incorrect else 0.0
        fraction = moodle_percent(share, format=_FORMAT)
        answers.append(
            MoodleAnswer(
                text=choice.text, fraction=fraction, feedback=choice.feedback
            )
        )
    return MultichoiceBlock(
        questiontext=join_blocks(question.stem, question.epilogue),
        answers=answers,
        single=False,
        shuffle_answers=_moodle_shuffle(question.shuffle),
        **_block_meta(question),
    )

def blocks_from_true_false(question: TrueFalseQuestion
) -> list[TrueFalseBlock]:
    group_stem = true_false_group_stem(question)
    group_feedback = exported_general_feedback(question, format=_FORMAT)
    blocks = []
    for i, statement in enumerate(question.choices):
        text = f"{group_stem}\n\n{statement.text}" if group_stem else statement.text
        answers = [
            MoodleAnswer(text="True", fraction=100.0 if statement.correct else 0.0),
            MoodleAnswer(
                text="False", fraction=0.0 if statement.correct else 100.0
            ),
        ]
        blocks.append(
            TrueFalseBlock(
                questiontext=text,
                answers=answers,
                shuffle_answers=_moodle_shuffle(question.shuffle) if i == 0 else None,
                name=question.title if i == 0 else None,
                idnumber=question.id if i == 0 else None,
                tags=list(question.tags) if i == 0 else [],
                default_grade=question.weight,
                general_feedback=group_feedback if i == 0 else None,
            )
        )
    return blocks

def block_from_numeric(question: NumericQuestion) -> NumericalBlock:
    value = float_answer(question.answer, question.tolerance, format=_FORMAT)
    tolerance = numeric_tolerance(value, question.tolerance)
    answers = [
        MoodleAnswer(text=format_num(value), fraction=100.0, tolerance=tolerance)
    ]
    if question.incorrect_feedback is not None:
        answers.append(any_other_answer(question.incorrect_feedback))
    return NumericalBlock(
        questiontext=join_blocks(question.stem, question.epilogue),
        answers=answers,
        unit=question.unit,
        **_block_meta(question),
    )

def block_from_short(question: ShortAnswerQuestion) -> ShortAnswerBlock:
    require_automatic(question, format=_FORMAT)
    answers = short_moodle_answers(
        question.accept, question.reject, question.incorrect_feedback
    )
    return ShortAnswerBlock(
        questiontext=join_blocks(question.stem, question.epilogue),
        answers=answers,
        **_block_meta(question),
    )

def any_other_answer(feedback: str) -> MoodleAnswer:
    """Moodle's "any other answer" idiom: a `*` answer worth 0% with the feedback."""
    return MoodleAnswer(text="*", fraction=0.0, feedback=feedback)


def short_moodle_answers(
    accept: list[AnswerPattern] | None,
    reject: list[AnswerPattern] | None,
    incorrect_feedback: str | None,
) -> list[MoodleAnswer]:
    """The answers of a short answer, or of a short answer blank, in Moodle's order."""
    answers = [
        MoodleAnswer(text=a.text, fraction=a.credit * 100, feedback=a.feedback)
        for a in exported_short_answers(accept, reject, format=_FORMAT)
    ]
    if incorrect_feedback is not None:
        answers.append(any_other_answer(incorrect_feedback))
    return answers

def block_from_essay(question: EssayQuestion) -> EssayBlock:
    return EssayBlock(
        questiontext=join_blocks(question.stem, question.epilogue),
        grader_info=question.answer_key,
        response_format=essay_response_format_from_content(question.content),
        **_block_meta(question),
    )

def block_from_fill_in(question: FillInQuestion) -> MultianswerBlock:
    blanks_by_id = {blank.id: blank for blank in question.blanks}
    referenced: set[str] = set()

    def replace(blank_id: str) -> str:
        blank = blanks_by_id.get(blank_id)
        if blank is None:
            raise ValueError(
                f"cannot convert to Moodle XML: stem references unknown blank {blank_id!r}"
            )
        referenced.add(blank_id)
        cloze = cloze_from_blank(blank)
        if cloze.kind == "MULTICHOICE" and len(cloze.answers) < 2:
            # qtype_multianswer_validate_question: `notenoughanswers`.
            raise ValueError(
                f"cannot convert to Moodle XML: choice blank {blank_id!r} needs "
                f"at least 2 choices, which Moodle requires in an embedded answer"
            )
        if not any(answer.fraction == 100 for answer in cloze.answers):
            # qtype_multianswer_validate_question rejects a subquestion
            # with no answer worth exactly 100% (`fractionsnomax`).
            raise ValueError(
                f"cannot convert to Moodle XML: blank {blank_id!r} has no "
                f"answer worth 100%, which Moodle requires in an embedded answer"
            )
        return render_cloze(cloze)

    # Code, `[^x](url)` links and autolinks are literal text, not blanks.
    questiontext = question.stem
    for marker in reversed(locate_blank_markers(question.stem)):
        if marker.span is not None:
            start, end = marker.span
            questiontext = questiontext[:start] + replace(marker.id) + questiontext[end:]
    missing = [blank.id for blank in question.blanks if blank.id not in referenced]
    if missing:
        raise ValueError(
            f"cannot convert to Moodle XML: blank(s) not referenced by the stem: {missing!r}"
        )
    return MultianswerBlock(
        questiontext=join_blocks(questiontext, question.epilogue),
        shuffle_answers=_moodle_shuffle(question.shuffle),
        **_block_meta(question),
    )

def cloze_from_blank(blank: Blank) -> MoodleCloze:
    match blank:
        case ChoiceBlank():
            answers = [
                MoodleAnswer(
                    text=choice.text, fraction=score * 100, feedback=choice.feedback
                )
                for choice, score in zip(blank.choices, blank_choice_scores(blank))
            ]
            return MoodleCloze(kind="MULTICHOICE", answers=answers)
        case ShortAnswerBlank():
            return MoodleCloze(
                kind="SHORTANSWER",
                answers=short_moodle_answers(
                    blank.accept, blank.reject, blank.incorrect_feedback
                ),
            )
        case NumericBlank():
            value = float_answer(blank.answer, blank.tolerance, format=_FORMAT)
            tolerance = numeric_tolerance(value, blank.tolerance)
            answers = [
                MoodleAnswer(text=format_num(value), fraction=100.0, tolerance=tolerance)
            ]
            if blank.incorrect_feedback is not None:
                answers.append(any_other_answer(blank.incorrect_feedback))
            return MoodleCloze(kind="NUMERICAL", answers=answers)
        case _:
            assert_never(blank)



def decode_question(moodle: MoodleXmlQuestion) -> Question:
    """A single block converts directly; several blocks must form a true/false group."""
    if not moodle.blocks:
        raise ValueError("Moodle XML question has no blocks")
    blocks = [markdown_block(block) for block in moodle.blocks]
    if len(blocks) == 1:
        return block_to_mdq(blocks[0])
    statements = [b for b in blocks if isinstance(b, TrueFalseBlock)]
    if len(statements) == len(blocks):
        return true_false_from_blocks(statements)
    raise ValueError(
        "a Moodle XML question group with more than one block is only "
        "supported when every block is a true/false statement"
    )

def markdown_block(block: MoodleXmlBlock) -> MoodleXmlBlock:
    """
    The block with each text in MDQ's Markdown, by the `format` of its own
    element (`mdq_text`): the question text, the general feedback, the grader
    info, the feedback of every answer and the text of a choice. The text of a
    short answer or numeric answer is not Markdown, so it is kept. The
    question text of a cloze question is converted by `fill_in_from_block`,
    around its blanks.
    """
    default = block.text_format

    def convert(text: str | None, text_format: MoodleTextFormat | None) -> str | None:
        return None if text is None else mdq_text(text, text_format or default)

    def convert_answer(answer: MoodleAnswer, *, text: bool) -> MoodleAnswer:
        return replace(
            answer,
            text=(convert(answer.text, answer.text_format) or "") if text else answer.text,
            feedback=convert(answer.feedback, answer.feedback_format),
        )

    general_feedback = convert(block.general_feedback, block.general_feedback_format)
    match block:
        case MultichoiceBlock():
            return replace(
                block,
                questiontext=mdq_text(block.questiontext, default),
                general_feedback=general_feedback,
                answers=[convert_answer(a, text=True) for a in block.answers],
            )
        case ShortAnswerBlock() | NumericalBlock():
            return replace(
                block,
                questiontext=mdq_text(block.questiontext, default),
                general_feedback=general_feedback,
                answers=[convert_answer(a, text=False) for a in block.answers],
            )
        case EssayBlock():
            return replace(
                block,
                questiontext=mdq_text(block.questiontext, default),
                general_feedback=general_feedback,
                grader_info=convert(block.grader_info, block.grader_info_format),
            )
        case TrueFalseBlock():
            return replace(
                block,
                questiontext=mdq_text(block.questiontext, default),
                general_feedback=general_feedback,
            )
        case MultianswerBlock():
            return replace(block, general_feedback=general_feedback)
        case _:
            assert_never(block)


def block_to_mdq(block: MoodleXmlBlock) -> Question:
    match block:
        case MultichoiceBlock(single=False):
            return selection_from_block(block)
        case MultichoiceBlock():
            return choice_from_block(block)
        case TrueFalseBlock():
            return choice_from_true_false_block(block)
        case ShortAnswerBlock():
            return short_answer_from_block(block)
        case NumericalBlock():
            return numeric_from_block(block)
        case EssayBlock():
            return essay_from_block(block)
        case MultianswerBlock():
            return fill_in_from_block(block)
        case _:
            assert_never(block)

def imported_answers(answers: Sequence[MoodleAnswer]) -> list[ImportedAnswer]:
    """The answers of a Moodle short answer or numerical question, for the key helpers."""
    return [
        ImportedAnswer(a.text, score_from_moodle_percent(a.fraction), a.feedback, a.tolerance)
        for a in answers
    ]

def short_answer_from_block(block: ShortAnswerBlock) -> ShortAnswerQuestion:
    key = short_answer_key(
        imported_answers(block.answers), format=_FORMAT, any_answer=True
    )
    return ShortAnswerQuestion(
        stem=block.questiontext,
        accept=key.accept,
        reject=key.reject,
        incorrect_feedback=key.incorrect_feedback,
        **_question_meta(block),
    )

def choice_from_block(block: MultichoiceBlock) -> MultipleChoiceQuestion:
    return MultipleChoiceQuestion(
        stem=block.questiontext,
        choices=[
            ScoredChoice(
                text=a.text,
                score=score_from_moodle_percent(a.fraction),
                feedback=a.feedback,
            )
            for a in block.answers
        ],
        shuffle=_mdq_shuffle(block.shuffle_answers),
        **_question_meta(block),
    )

def selection_from_block(block: MultichoiceBlock) -> MultipleSelectionQuestion:
    return MultipleSelectionQuestion(
        stem=block.questiontext,
        choices=[
            BooleanChoice(text=a.text, correct=a.fraction > 0, feedback=a.feedback)
            for a in block.answers
        ],
        shuffle=_mdq_shuffle(block.shuffle_answers),
        **_question_meta(block),
    )

def choice_from_true_false_block(block: TrueFalseBlock
) -> MultipleChoiceQuestion:
    correct = statement_correct(block)
    return MultipleChoiceQuestion(
        stem=block.questiontext,
        choices=[
            ScoredChoice(text="True", score=1.0 if correct else 0.0),
            ScoredChoice(text="False", score=0.0 if correct else 1.0),
        ],
        **_question_meta(block),
    )

def numeric_from_block(block: NumericalBlock) -> NumericQuestion:
    key = numeric_answer_key(imported_answers(block.answers), format=_FORMAT)
    return NumericQuestion(
        stem=block.questiontext,
        answer=key.answer,
        unit=_mdq_unit(block.unit),
        tolerance=key.tolerance,
        incorrect_feedback=key.incorrect_feedback,
        **_question_meta(block),
    )

def essay_from_block(block: EssayBlock) -> EssayQuestion:
    return EssayQuestion(
        stem=block.questiontext,
        answer_key=block.grader_info,
        content=essay_content_from_response_format(block.response_format),
        **_question_meta(block),
    )

def fill_in_from_block(block: MultianswerBlock) -> FillInQuestion:
    segments, clozes = parse_cloze(block.questiontext)
    segments = [mdq_text(segment, block.text_format) for segment in segments]
    parts = [segments[0]]
    blanks: list[Blank] = []
    for i, cloze in enumerate(clozes):
        blank_id = f"blank{i + 1}"
        blanks.append(blank_from_cloze(blank_id, cloze, block.text_format))
        parts.append(f"[^{blank_id}]")
        parts.append(segments[i + 1])
    return FillInQuestion(
        stem="".join(parts),
        blanks=blanks,
        shuffle=_mdq_shuffle(block.shuffle_answers),
        **_question_meta(block),
    )

def blank_from_cloze(
    blank_id: str, cloze: MoodleCloze, text_format: MoodleTextFormat
) -> Blank:
    """The blank of a cloze: its texts are written in the `text_format` of the question."""
    is_choice = cloze.kind == "MULTICHOICE"
    answers = [
        replace(
            a,
            text=mdq_text(a.text, text_format) if is_choice else a.text,
            feedback=None if a.feedback is None else mdq_text(a.feedback, text_format),
        )
        for a in cloze.answers
    ]
    if is_choice:
        return ChoiceBlank(
            id=blank_id,
            choices=[
                ScoredChoice(
                    text=a.text,
                    score=score_from_moodle_percent(a.fraction),
                    feedback=a.feedback,
                )
                for a in answers
            ],
        )
    if cloze.kind == "SHORTANSWER":
        short = short_answer_key(imported_answers(answers), format=_FORMAT)
        return ShortAnswerBlank(
            id=blank_id,
            accept=short.accept,
            reject=short.reject,
            incorrect_feedback=short.incorrect_feedback,
        )
    numeric = numeric_answer_key(imported_answers(answers), format=_FORMAT)
    return NumericBlank(
        id=blank_id,
        answer=numeric.answer,
        tolerance=numeric.tolerance,
        incorrect_feedback=numeric.incorrect_feedback,
    )

def true_false_from_blocks(blocks: list[TrueFalseBlock]) -> TrueFalseQuestion:
    texts = [b.questiontext for b in blocks]
    group_stem, statement_texts = split_true_false_group(texts)

    choices = [
        Statement(text=text.strip(), correct=statement_correct(block))
        for text, block in zip(statement_texts, blocks)
    ]

    meta = _question_meta(blocks[0])
    meta["meta"] = general_feedback_meta(*(b.general_feedback for b in blocks))
    return TrueFalseQuestion(
        stem=group_stem,
        choices=choices,
        shuffle=_mdq_shuffle(blocks[0].shuffle_answers),
        **meta,
    )


class MoodleXmlParser(StringParser[MoodleXmlQuestion]):
    """
    Moodle XML parses with `xml.etree.ElementTree` rather than the base
    class's line-based helpers; `self.lines` is only used to locate errors.
    """

    def start(self) -> MoodleXmlQuestion:
        try:
            root = ET.fromstring(self.source)
        except ET.ParseError as exc:
            line, col = exc.position
            self.lineno = max(line - 1, 0)
            self.colno = col
            self.lines.clear()
            self.error(f"malformed Moodle XML: {exc}")
        self.lines.clear()

        if root.tag != "quiz":
            self.error(f"expected a <quiz> root element, got <{root.tag}>")

        blocks = []
        for question_el in root.findall("question"):
            qtype = question_el.get("type")
            if qtype == "category":
                continue
            blocks.append(self.block_from_element(question_el))
        return MoodleXmlQuestion(blocks=blocks)

    def block_from_element(self, question_el: ET.Element) -> MoodleXmlBlock:
        qtype = question_el.get("type")

        name_el = question_el.find("name")
        name = text_node_content(name_el) if name_el is not None else None

        idnumber_el = question_el.find("idnumber")
        idnumber = idnumber_el.text if idnumber_el is not None else None

        questiontext_el = question_el.find("questiontext")
        questiontext = (
            text_node_content(questiontext_el) if questiontext_el is not None else ""
        )
        text_format = moodle_text_format(
            questiontext_el.get("format") if questiontext_el is not None else None
        )

        generalfeedback_el = question_el.find("generalfeedback")
        general_feedback = (
            text_node_content(generalfeedback_el)
            if generalfeedback_el is not None
            else None
        )
        general_feedback_format = element_text_format(generalfeedback_el, text_format)

        defaultgrade_el = question_el.find("defaultgrade")
        default_grade = (
            float(defaultgrade_el.text)
            if defaultgrade_el is not None and defaultgrade_el.text
            else 1.0
        )

        tags = [text_node_content(tag_el) for tag_el in question_el.findall("tags/tag")]
        common = _BlockFields(
            questiontext=questiontext,
            name=name,
            idnumber=idnumber,
            text_format=text_format,
            general_feedback=general_feedback,
            general_feedback_format=general_feedback_format,
            default_grade=default_grade,
            tags=tags,
        )

        shuffle_answers = parse_bool_element(question_el.find("shuffleanswers"))
        answers = [answer_from_element(a) for a in question_el.findall("answer")]
        match qtype:
            case "multichoice":
                single = parse_bool_element(question_el.find("single"))
                return MultichoiceBlock(
                    **common, answers=answers, single=single, shuffle_answers=shuffle_answers
                )
            case "truefalse":
                return TrueFalseBlock(**common, answers=answers, shuffle_answers=shuffle_answers)
            case "shortanswer":
                return ShortAnswerBlock(**common, answers=answers)
            case "numerical":
                unit_name_el = question_el.find("units/unit/unit_name")
                unit = unit_name_el.text if unit_name_el is not None else None
                return NumericalBlock(**common, answers=answers, unit=unit)
            case "essay":
                graderinfo_el = question_el.find("graderinfo")
                grader_info = (
                    text_node_content(graderinfo_el) if graderinfo_el is not None else None
                )
                responseformat_el = question_el.find("responseformat")
                response_format = (
                    responseformat_el.text if responseformat_el is not None else None
                )
                return EssayBlock(
                    **common,
                    grader_info=grader_info,
                    response_format=response_format,
                    grader_info_format=element_text_format(graderinfo_el, text_format),
                )
            case "multianswer":
                return MultianswerBlock(**common, shuffle_answers=shuffle_answers)
            case _:
                raise ValueError(f"unsupported Moodle XML question type: {qtype!r}")


def _mdq_unit(unit: str | None) -> str | None:
    """Remove the characters that the MDQ `UNIT` terminal excludes from a Moodle unit."""
    return re.sub(rf"[()\[\]{UNICODE_SPACE}]", "", unit or "") or None


def parse_cloze(text: str) -> tuple[list[str], list[MoodleCloze]]:
    """
    Split `text` into the plain segments around each `{weight:KIND:...}` blank.

    A blank's body may itself contain `{`, `}`, `~`, `=`, `#`, `:` and `\\`
    escaped with a leading backslash; the scan tracks escapes so those
    characters don't prematurely end the blank.
    """
    segments = []
    clozes = []
    last = 0
    pos = 0
    n = len(text)
    while pos < n:
        ch = text[pos]
        if ch == "\\" and pos + 1 < n:
            pos += 2
            continue
        if ch == "{" and (header := CLOZE_HEADER_REGEX.match(text, pos)):
            close = find_unescaped(text, "}", header.end())
            if close == -1:
                raise ValueError(f"unterminated cloze blank at position {pos}")
            segments.append(text[last:pos])
            weight = int(header.group(1))
            kind = normalize_cloze_kind(header.group(2))
            answers = parse_cloze_options(text[header.end() : close], kind)
            clozes.append(MoodleCloze(kind=kind, answers=answers, weight=weight))
            pos = close + 1
            last = pos
            continue
        pos += 1
    segments.append(text[last:])
    return segments, clozes


def render_cloze(cloze: MoodleCloze) -> str:
    """Render one inline cloze blank, always using its canonical kind name."""
    parts = []
    for answer in cloze.answers:
        if answer.fraction == 100.0:
            prefix = "="
        elif answer.fraction == 0.0:
            prefix = "~"
        else:
            prefix = f"~%{format_num(answer.fraction)}%"
        entry = prefix + escape_text(answer.text)
        if cloze.kind == "NUMERICAL" and answer.tolerance:
            entry += f":{escape_text(format_num(answer.tolerance))}"
        if answer.feedback:
            entry += f"#{escape_text(answer.feedback)}"
        parts.append(entry)
    return f"{{{cloze.weight}:{cloze.kind}:{''.join(parts)}}}"


def normalize_cloze_kind(raw: str) -> ClozeKind:
    """Resolve a cloze kind name or abbreviation to its canonical `ClozeKind`."""
    try:
        return CLOZE_KIND_ALIASES[raw.upper()]
    except KeyError:
        raise ValueError(f"unsupported cloze kind: {raw!r}") from None


def parse_cloze_options(body: str, kind: ClozeKind) -> list[MoodleAnswer]:
    """Parse a cloze blank's `=`/`~`-delimited option list."""
    answers = []
    for entry in parse_entries(body, "=~", lambda percent: percent / 100):
        text_raw = entry.text
        tolerance = None
        if kind == "NUMERICAL":
            colon_pos = find_unescaped(text_raw, ":")
            if colon_pos != -1:
                tolerance = float(unescape_text(text_raw[colon_pos + 1 :]))
                text_raw = text_raw[:colon_pos]
        feedback = unescape_text(entry.feedback) if entry.feedback else None
        answers.append(
            MoodleAnswer(
                text=unescape_text(text_raw),
                fraction=entry.credit * 100,
                feedback=feedback or None,
                tolerance=tolerance,
            )
        )
    return answers


def render_element(elem: ET.Element) -> str:
    """Indent `elem` in place and serialize it (no XML declaration)."""
    ET.indent(elem, space="  ")
    return ET.tostring(elem, encoding="unicode")


def text_node_content(parent: ET.Element) -> str:
    """Read the `<text>` child of `parent`, e.g. `<name><text>...</text></name>`."""
    text_el = parent.find("text")
    return (text_el.text if text_el is not None else None) or ""


def moodle_text_format(value: str | None) -> MoodleTextFormat:
    """
    The `format` attribute `value` as a `MoodleTextFormat`. A missing value,
    `wiki_like` (which MDQ has no reading of) and an unknown one are `html`,
    as Moodle's own importer reads them.
    """
    value = (value or "").strip()
    for known in MOODLE_TEXT_FORMATS:
        if value == known:
            return known
    return "html"


def element_text_format(
    element: ET.Element | None, default: MoodleTextFormat
) -> MoodleTextFormat | None:
    """
    The `format` of a text element such as `<generalfeedback>`, which
    defaults to `default` (the format of the question text) when missing.
    `None` if there is no element.
    """
    if element is None:
        return None
    return moodle_text_format(element.get("format")) if "format" in element.attrib else default


def answer_from_element(answer_el: ET.Element) -> MoodleAnswer:
    """
    Parse one `<answer>` element into a `MoodleAnswer`. The `<answer>` and its
    `<feedback>` are `html` when they have no `format`, as in Moodle.
    """
    feedback_el = answer_el.find("feedback")
    feedback = text_node_content(feedback_el) if feedback_el is not None else None
    tolerance_el = answer_el.find("tolerance")
    tolerance = (
        float(tolerance_el.text)
        if tolerance_el is not None and tolerance_el.text
        else None
    )
    return MoodleAnswer(
        text=text_node_content(answer_el),
        fraction=float(answer_el.get("fraction", "0")),
        feedback=feedback or None,
        tolerance=tolerance,
        text_format=moodle_text_format(answer_el.get("format")),
        feedback_format=moodle_text_format(
            feedback_el.get("format") if feedback_el is not None else None
        ),
    )


def parse_bool_element(elem: ET.Element | None) -> bool | None:
    """Parse a `true`/`false` element's text, or `None` if the element is absent."""
    if elem is None or elem.text is None:
        return None
    return elem.text.strip().lower() == "true"


def bool_to_moodle(value: bool) -> str:
    """Render a bool the way Moodle XML spells it: `true`/`false`."""
    return "true" if value else "false"


def statement_correct(block: TrueFalseBlock) -> bool:
    """A true/false block's statement is correct when its `True` answer has positive fraction."""
    for answer in block.answers:
        if answer.text.strip().lower() == "true":
            return answer.fraction > 0
    return bool(block.answers) and block.answers[0].fraction > 0


#: Moodle's essay `<responseformat>` values that MDQ has an essay `content` for.
_ESSAY_CONTENT_BY_RESPONSE_FORMAT: dict[str, EssayContent] = {
    "editor": "text",
    "plain": "plain",
    "monospaced": "code",
}
_ESSAY_RESPONSE_FORMAT_BY_CONTENT = {
    content: response_format
    for response_format, content in _ESSAY_CONTENT_BY_RESPONSE_FORMAT.items()
}


def essay_content_from_response_format(response_format: str | None) -> EssayContent:
    """
    Map a Moodle `<responseformat>` value to an MDQ essay `content` kind.
    A value MDQ has no kind for (or a missing one) is read as `"text"`.
    """
    return _ESSAY_CONTENT_BY_RESPONSE_FORMAT.get(response_format or "", "text")


def essay_response_format_from_content(content: EssayContent) -> str:
    """Inverse of `essay_content_from_response_format`."""
    return _ESSAY_RESPONSE_FORMAT_BY_CONTENT[content]
