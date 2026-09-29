from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Literal

from .._markdown import UNICODE_SPACE
from ..models import (
    Blank,
    BooleanChoice,
    ChoiceBlank,
    EssayQuestion,
    FillInQuestion,
    MultipleChoiceQuestion,
    MultipleSelectionQuestion,
    NumericBlank,
    NumericQuestion,
    Question,
    ScoredChoice,
    ShortAnswerBlank,
    ShortAnswerQuestion,
    Statement,
    Tolerance,
    TrueFalseQuestion,
)
from ..types import EssayInput
from ._base import (
    TRUE_FALSE_FALLBACK_STEM,
    ConversionBase,
    float_answer,
    mdq_numeric_answer,
    moodle_percent,
    score_from_moodle_percent,
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
    "MoodleXmlQuestion",
    "MoodleXmlEncoder",
    "MoodleXmlDecoder",
    "MoodleXmlParser",
    "parse_cloze",
    "render_cloze",
]

type MoodleXmlType = Literal[
    "multichoice", "truefalse", "shortanswer", "numerical", "essay", "multianswer"
]
type MoodleTextFormat = Literal["html", "moodle", "plain_text", "markdown"]
type ClozeKind = Literal["SHORTANSWER", "NUMERICAL", "MULTICHOICE"]

MOODLE_XML_TYPES: frozenset[str] = frozenset(
    {"multichoice", "truefalse", "shortanswer", "numerical", "essay", "multianswer"}
)
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
CREDIT_TAG_REGEX = re.compile(r"%(-?\d+(?:\.\d+)?)%")
BLANK_MARKER_REGEX = re.compile(r"\[\^([^\]]+)\]")
CLOZE_ESCAPE_REGEX = re.compile(r"[:=~{}#\\]")
CLOZE_UNESCAPE_REGEX = re.compile(r"\\(.)")

#: The format name in error messages.
_FORMAT = "Moodle XML"


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

    supports = {
        "multiple-choice": "both",
        "multiple-selection": "both",
        "true-false": "both",
        "numeric": "both",
        "short-answer": "both",
        "essay": "both",
        "fill-in": "both",
    }

    def from_mdq(self, question: Question) -> MoodleXmlQuestion:
        return MoodleXmlEncoder().encode(question)

    def to_mdq(self, moodle: MoodleXmlQuestion) -> Question:
        return MoodleXmlDecoder().decode(moodle)

    def parse(self, source: str) -> MoodleXmlQuestion:
        return MoodleXmlParser(source).parse()


@dataclass
class MoodleAnswer:
    """One `<answer>` (or cloze option) entry."""

    text: str
    fraction: float = 0.0
    feedback: str | None = None
    tolerance: float | None = None  # numerical only


@dataclass
class MoodleCloze:
    """One inline blank of a `multianswer` question."""

    kind: ClozeKind
    answers: list[MoodleAnswer]
    weight: int = 1


@dataclass
class MoodleXmlBlock:
    """One `<question>` element."""

    type: MoodleXmlType
    questiontext: str
    name: str | None = None
    idnumber: str | None = None
    text_format: MoodleTextFormat = "markdown"
    general_feedback: str | None = None
    answers: list[MoodleAnswer] = field(default_factory=list)
    single: bool | None = None  # multichoice
    shuffle_answers: bool | None = None
    grader_info: str | None = None  # essay
    response_format: str | None = None  # essay
    unit: str | None = None  # numerical
    default_grade: float = 1.0
    tags: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return render_element(build_question_element(self))


@dataclass
class MoodleXmlQuestion:
    """A Moodle XML question: one block, or several for a true/false group."""

    blocks: list[MoodleXmlBlock] = field(default_factory=list)

    def __str__(self) -> str:
        quiz = ET.Element("quiz")
        for block in self.blocks:
            quiz.append(build_question_element(block))
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{render_element(quiz)}'


class MoodleXmlEncoder:
    """Converts an MDQ `Question` into a `MoodleXmlQuestion`."""

    def encode(self, question: Question) -> MoodleXmlQuestion:
        """Dispatch on `question.type` to the matching `block_from_*` builder."""
        if isinstance(question, MultipleChoiceQuestion):
            return MoodleXmlQuestion(blocks=[self.block_from_choice(question)])
        if isinstance(question, MultipleSelectionQuestion):
            return MoodleXmlQuestion(blocks=[self.block_from_selection(question)])
        if isinstance(question, TrueFalseQuestion):
            return MoodleXmlQuestion(blocks=self.blocks_from_true_false(question))
        if isinstance(question, NumericQuestion):
            return MoodleXmlQuestion(blocks=[self.block_from_numeric(question)])
        if isinstance(question, ShortAnswerQuestion):
            return MoodleXmlQuestion(blocks=[self.block_from_short(question)])
        if isinstance(question, EssayQuestion):
            return MoodleXmlQuestion(blocks=[self.block_from_essay(question)])
        if isinstance(question, FillInQuestion):
            return MoodleXmlQuestion(blocks=[self.block_from_fill_in(question)])
        raise ValueError(f"Moodle XML does not support {question.type!r} questions")

    def block_from_choice(self, question: MultipleChoiceQuestion) -> MoodleXmlBlock:
        answers = []
        for choice in question.choices:
            if choice.score is None:
                raise ValueError(
                    "cannot convert to Moodle XML: every choice must have a score"
                )
            answers.append(
                MoodleAnswer(
                    text=choice.text,
                    fraction=moodle_percent(choice.score, format=_FORMAT),
                    feedback=choice.feedback,
                )
            )
        return MoodleXmlBlock(
            type="multichoice",
            questiontext=join_blocks(question.preamble, question.stem, question.epilogue),
            answers=answers,
            single=True,
            shuffle_answers=question.shuffle,
            name=question.title,
            idnumber=question.id,
            tags=list(question.tags),
            default_grade=question.weight,
        )

    def block_from_selection(self, question: MultipleSelectionQuestion) -> MoodleXmlBlock:
        n_correct = sum(1 for c in question.choices if c.correct)
        n_incorrect = len(question.choices) - n_correct
        answers = []
        for choice in question.choices:
            if choice.correct:
                share = 1 / n_correct if n_correct else 0.0
            else:
                share = -1 / n_incorrect if n_incorrect else 0.0
            fraction = moodle_percent(share, format=_FORMAT)
            answers.append(MoodleAnswer(text=choice.text, fraction=fraction, feedback=choice.feedback))
        return MoodleXmlBlock(
            type="multichoice",
            questiontext=join_blocks(question.preamble, question.stem, question.epilogue),
            answers=answers,
            single=False,
            shuffle_answers=question.shuffle,
            name=question.title,
            idnumber=question.id,
            tags=list(question.tags),
            default_grade=question.weight,
        )

    def blocks_from_true_false(self, question: TrueFalseQuestion) -> list[MoodleXmlBlock]:
        # The fallback stem stands for "no shared text", so it round-trips.
        stem = None if question.stem == TRUE_FALSE_FALLBACK_STEM else question.stem
        group_stem = join_blocks(question.preamble, stem, question.epilogue)
        blocks = []
        for i, statement in enumerate(question.choices):
            text = f"{group_stem}\n\n{statement.text}" if group_stem else statement.text
            answers = [
                MoodleAnswer(text="True", fraction=100.0 if statement.correct else 0.0),
                MoodleAnswer(text="False", fraction=0.0 if statement.correct else 100.0),
            ]
            blocks.append(
                MoodleXmlBlock(
                    type="truefalse",
                    questiontext=text,
                    answers=answers,
                    shuffle_answers=question.shuffle if i == 0 else None,
                    name=question.title if i == 0 else None,
                    idnumber=question.id if i == 0 else None,
                    tags=list(question.tags) if i == 0 else [],
                    default_grade=question.weight,
                )
            )
        return blocks

    def block_from_numeric(self, question: NumericQuestion) -> MoodleXmlBlock:
        value = float_answer(question.answer, question.tolerance, format=_FORMAT)
        tolerance = numeric_tolerance(value, question.tolerance)
        answers = [MoodleAnswer(text=format_num(value), fraction=100.0, tolerance=tolerance)]
        return MoodleXmlBlock(
            type="numerical",
            questiontext=join_blocks(question.preamble, question.stem, question.epilogue),
            answers=answers,
            unit=question.unit,
            name=question.title,
            idnumber=question.id,
            tags=list(question.tags),
            default_grade=question.weight,
        )

    def block_from_short(self, question: ShortAnswerQuestion) -> MoodleXmlBlock:
        if question.one_of is None:
            raise ValueError(
                "cannot convert to Moodle XML: short-answer question needs `oneOf` "
                "(regex/accept/openEnded answers are not supported)"
            )
        answers = [MoodleAnswer(text=text, fraction=100.0) for text in question.one_of]
        return MoodleXmlBlock(
            type="shortanswer",
            questiontext=join_blocks(question.preamble, question.stem, question.epilogue),
            answers=answers,
            name=question.title,
            idnumber=question.id,
            tags=list(question.tags),
            default_grade=question.weight,
        )

    def block_from_essay(self, question: EssayQuestion) -> MoodleXmlBlock:
        return MoodleXmlBlock(
            type="essay",
            questiontext=join_blocks(question.preamble, question.stem, question.epilogue),
            grader_info=question.answer_key,
            response_format=essay_response_format_from_input(question.input),
            name=question.title,
            idnumber=question.id,
            tags=list(question.tags),
            default_grade=question.weight,
        )

    def block_from_fill_in(self, question: FillInQuestion) -> MoodleXmlBlock:
        blanks_by_id = {blank.id: blank for blank in question.blanks}
        referenced: set[str] = set()

        def replace(match: re.Match[str]) -> str:
            blank_id = match.group(1)
            blank = blanks_by_id.get(blank_id)
            if blank is None:
                raise ValueError(
                    f"cannot convert to Moodle XML: stem references unknown blank {blank_id!r}"
                )
            referenced.add(blank_id)
            cloze = self.cloze_from_blank(blank)
            if not any(answer.fraction == 100 for answer in cloze.answers):
                # qtype_multianswer_validate_question rejects a subquestion
                # with no answer worth exactly 100% (`fractionsnomax`).
                raise ValueError(
                    f"cannot convert to Moodle XML: blank {blank_id!r} has no "
                    f"answer worth 100%, which Moodle requires in an embedded answer"
                )
            return render_cloze(cloze)

        questiontext = BLANK_MARKER_REGEX.sub(replace, question.stem)
        missing = [blank.id for blank in question.blanks if blank.id not in referenced]
        if missing:
            raise ValueError(
                f"cannot convert to Moodle XML: blank(s) not referenced by the stem: {missing!r}"
            )
        return MoodleXmlBlock(
            type="multianswer",
            questiontext=join_blocks(question.preamble, questiontext, question.epilogue),
            shuffle_answers=question.shuffle,
            name=question.title,
            idnumber=question.id,
            tags=list(question.tags),
            default_grade=question.weight,
        )

    def cloze_from_blank(self, blank: Blank) -> MoodleCloze:
        if isinstance(blank, ChoiceBlank):
            # An unmarked choice inside a blank keeps `score = None`, which
            # MDQ reads as zero credit; only top-level choices are strict.
            answers = [
                MoodleAnswer(text=choice.text, fraction=(choice.score or 0.0) * 100)
                for choice in blank.choices
            ]
            return MoodleCloze(kind="MULTICHOICE", answers=answers)
        if isinstance(blank, ShortAnswerBlank):
            if blank.one_of is None:
                raise ValueError("cannot convert to Moodle XML: short-answer blank needs `oneOf`")
            return MoodleCloze(
                kind="SHORTANSWER",
                answers=[MoodleAnswer(text=text, fraction=100.0) for text in blank.one_of],
            )
        value = float_answer(blank.answer, blank.tolerance, format=_FORMAT)
        tolerance = numeric_tolerance(value, blank.tolerance)
        return MoodleCloze(
            kind="NUMERICAL",
            answers=[MoodleAnswer(text=format_num(value), fraction=100.0, tolerance=tolerance)],
        )


class MoodleXmlDecoder:
    """Converts a `MoodleXmlQuestion` into an MDQ `Question`."""

    def decode(self, moodle: MoodleXmlQuestion) -> Question:
        """A single block converts directly; several blocks must form a true/false group."""
        if not moodle.blocks:
            raise ValueError("Moodle XML question has no blocks")
        if len(moodle.blocks) == 1:
            return self.block_to_mdq(moodle.blocks[0])
        if all(b.type == "truefalse" for b in moodle.blocks):
            return self.true_false_from_blocks(moodle.blocks)
        raise ValueError(
            "a Moodle XML question group with more than one block is only "
            "supported when every block is a true/false statement"
        )

    def block_to_mdq(self, block: MoodleXmlBlock) -> Question:
        if block.type == "multichoice":
            if block.single is False:
                return self.selection_from_block(block)
            return self.choice_from_block(block)
        if block.type == "truefalse":
            return self.choice_from_true_false_block(block)
        if block.type == "shortanswer":
            return ShortAnswerQuestion(
                stem=block.questiontext,
                one_of=[a.text for a in block.answers],
                title=block.name,
                id=block.idnumber,
                tags=list(block.tags),
                weight=block.default_grade,
            )
        if block.type == "numerical":
            return self.numeric_from_block(block)
        if block.type == "essay":
            return self.essay_from_block(block)
        if block.type == "multianswer":
            return self.fill_in_from_block(block)
        raise ValueError(f"Moodle XML does not support {block.type!r} questions")

    def choice_from_block(self, block: MoodleXmlBlock) -> MultipleChoiceQuestion:
        return MultipleChoiceQuestion(
            stem=block.questiontext,
            choices=[
                ScoredChoice(
                    text=a.text, score=score_from_moodle_percent(a.fraction), feedback=a.feedback
                )
                for a in block.answers
            ],
            shuffle=block.shuffle_answers,
            title=block.name,
            id=block.idnumber,
            tags=list(block.tags),
            weight=block.default_grade,
        )

    def selection_from_block(self, block: MoodleXmlBlock) -> MultipleSelectionQuestion:
        return MultipleSelectionQuestion(
            stem=block.questiontext,
            choices=[
                BooleanChoice(text=a.text, correct=a.fraction > 0, feedback=a.feedback)
                for a in block.answers
            ],
            shuffle=block.shuffle_answers,
            title=block.name,
            id=block.idnumber,
            tags=list(block.tags),
            weight=block.default_grade,
        )

    def choice_from_true_false_block(self, block: MoodleXmlBlock) -> MultipleChoiceQuestion:
        correct = statement_correct(block)
        return MultipleChoiceQuestion(
            stem=block.questiontext,
            choices=[
                ScoredChoice(text="True", score=1.0 if correct else 0.0),
                ScoredChoice(text="False", score=0.0 if correct else 1.0),
            ],
            title=block.name,
            id=block.idnumber,
            tags=list(block.tags),
            weight=block.default_grade,
        )

    def numeric_from_block(self, block: MoodleXmlBlock) -> NumericQuestion:
        answer = block.answers[0]
        tolerance = Tolerance(absolute=answer.tolerance) if answer.tolerance else None
        return NumericQuestion(
            stem=block.questiontext,
            answer=mdq_numeric_answer(answer.text),
            unit=_mdq_unit(block.unit),
            tolerance=tolerance,
            title=block.name,
            id=block.idnumber,
            tags=list(block.tags),
            weight=block.default_grade,
        )

    def essay_from_block(self, block: MoodleXmlBlock) -> EssayQuestion:
        return EssayQuestion(
            stem=block.questiontext,
            answer_key=block.grader_info,
            input=essay_input_from_response_format(block.response_format),
            title=block.name,
            id=block.idnumber,
            tags=list(block.tags),
            weight=block.default_grade,
        )

    def fill_in_from_block(self, block: MoodleXmlBlock) -> FillInQuestion:
        segments, clozes = parse_cloze(block.questiontext)
        parts = [segments[0]]
        blanks: list[Blank] = []
        for i, cloze in enumerate(clozes):
            blank_id = f"blank{i + 1}"
            blanks.append(self.blank_from_cloze(blank_id, cloze))
            parts.append(f"[^{blank_id}]")
            parts.append(segments[i + 1])
        return FillInQuestion(
            stem="".join(parts),
            blanks=blanks,
            shuffle=block.shuffle_answers,
            title=block.name,
            id=block.idnumber,
            tags=list(block.tags),
            weight=block.default_grade,
        )

    def blank_from_cloze(self, blank_id: str, cloze: MoodleCloze) -> Blank:
        if cloze.kind == "MULTICHOICE":
            return ChoiceBlank(
                id=blank_id,
                choices=[
                    ScoredChoice(
                    text=a.text, score=score_from_moodle_percent(a.fraction), feedback=a.feedback
                )
                    for a in cloze.answers
                ],
            )
        if cloze.kind == "SHORTANSWER":
            return ShortAnswerBlank(id=blank_id, one_of=[a.text for a in cloze.answers])
        answer = cloze.answers[0]
        tolerance = Tolerance(absolute=answer.tolerance) if answer.tolerance else None
        return NumericBlank(id=blank_id, answer=mdq_numeric_answer(answer.text), tolerance=tolerance)

    def true_false_from_blocks(self, blocks: list[MoodleXmlBlock]) -> TrueFalseQuestion:
        texts = [b.questiontext for b in blocks]
        prefix = common_prefix(texts)
        split = prefix.rfind("\n\n")

        if split == -1:
            group_stem = TRUE_FALSE_FALLBACK_STEM
            statement_texts = texts
        else:
            group_stem = prefix[:split].strip()
            boundary = split + 2
            statement_texts = [t[boundary:] for t in texts]

        choices = [
            Statement(text=text.strip(), correct=statement_correct(block))
            for text, block in zip(statement_texts, blocks)
        ]

        return TrueFalseQuestion(
            stem=group_stem,
            choices=choices,
            shuffle=blocks[0].shuffle_answers,
            title=blocks[0].name,
            id=blocks[0].idnumber,
            tags=list(blocks[0].tags),
            weight=blocks[0].default_grade,
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
            if qtype not in MOODLE_XML_TYPES:
                raise ValueError(f"unsupported Moodle XML question type: {qtype!r}")
            blocks.append(self.block_from_element(question_el))
        return MoodleXmlQuestion(blocks=blocks)

    def block_from_element(self, question_el: ET.Element) -> MoodleXmlBlock:
        qtype = question_el.get("type")
        assert qtype in MOODLE_XML_TYPES

        name_el = question_el.find("name")
        name = text_node_content(name_el) if name_el is not None else None

        idnumber_el = question_el.find("idnumber")
        idnumber = idnumber_el.text if idnumber_el is not None else None

        questiontext_el = question_el.find("questiontext")
        questiontext = text_node_content(questiontext_el) if questiontext_el is not None else ""
        text_format = (
            questiontext_el.get("format", "markdown") if questiontext_el is not None else "markdown"
        )

        generalfeedback_el = question_el.find("generalfeedback")
        general_feedback = (
            text_node_content(generalfeedback_el) if generalfeedback_el is not None else None
        )

        defaultgrade_el = question_el.find("defaultgrade")
        default_grade = (
            float(defaultgrade_el.text)
            if defaultgrade_el is not None and defaultgrade_el.text
            else 1.0
        )

        single = parse_bool_element(question_el.find("single"))
        shuffle_answers = parse_bool_element(question_el.find("shuffleanswers"))
        answers = [answer_from_element(a) for a in question_el.findall("answer")]

        graderinfo_el = question_el.find("graderinfo")
        grader_info = text_node_content(graderinfo_el) if graderinfo_el is not None else None

        responseformat_el = question_el.find("responseformat")
        response_format = responseformat_el.text if responseformat_el is not None else None

        unit_name_el = question_el.find("units/unit/unit_name")
        unit = unit_name_el.text if unit_name_el is not None else None

        tags = [
            text_node_content(tag_el) for tag_el in question_el.findall("tags/tag")
        ]

        return MoodleXmlBlock(
            type=qtype,  # type: ignore[arg-type]  # narrowed by the membership check above
            questiontext=questiontext,
            name=name,
            idnumber=idnumber,
            text_format=text_format,  # type: ignore[arg-type]  # Moodle format attribute is free text
            general_feedback=general_feedback,
            answers=answers,
            single=single,
            shuffle_answers=shuffle_answers,
            grader_info=grader_info,
            response_format=response_format,
            unit=unit,
            default_grade=default_grade,
            tags=tags,
        )


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
        entry = prefix + escape_cloze(answer.text)
        if cloze.kind == "NUMERICAL" and answer.tolerance:
            entry += f":{escape_cloze(format_num(answer.tolerance))}"
        if answer.feedback:
            entry += f"#{escape_cloze(answer.feedback)}"
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
    for entry in split_unescaped(body, "=~"):
        credit = 1.0 if entry[0] == "=" else 0.0
        rest = entry[1:]
        credit_match = CREDIT_TAG_REGEX.match(rest)
        if credit_match:
            credit = float(credit_match.group(1)) / 100
            rest = rest[credit_match.end() :]
        hash_pos = find_unescaped(rest, "#")
        text_raw, feedback_raw = (
            (rest, None) if hash_pos == -1 else (rest[:hash_pos], rest[hash_pos + 1 :])
        )
        tolerance = None
        if kind == "NUMERICAL":
            colon_pos = find_unescaped(text_raw, ":")
            if colon_pos != -1:
                tolerance = float(unescape_cloze(text_raw[colon_pos + 1 :]))
                text_raw = text_raw[:colon_pos]
        feedback = unescape_cloze(feedback_raw) if feedback_raw else None
        answers.append(
            MoodleAnswer(
                text=unescape_cloze(text_raw),
                fraction=credit * 100,
                feedback=feedback or None,
                tolerance=tolerance,
            )
        )
    return answers


def escape_cloze(text: str) -> str:
    r"""Backslash-escape a cloze body's special characters (`:=~{}#\`)."""
    return CLOZE_ESCAPE_REGEX.sub(lambda m: "\\" + m.group(), text)


def unescape_cloze(text: str) -> str:
    """Undo `escape_cloze`."""
    return CLOZE_UNESCAPE_REGEX.sub(r"\1", text)


def find_unescaped(text: str, target: str, start: int = 0) -> int:
    """Return the index of the first unescaped occurrence of `target`, or -1."""
    i = start
    n = len(text)
    m = len(target)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i : i + m] == target:
            return i
        i += 1
    return -1


def split_unescaped(text: str, chars: str) -> list[str]:
    """Split `text` into segments, each starting at an unescaped char in `chars`."""
    positions = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch in chars:
            positions.append(i)
        i += 1
    return [text[a:b] for a, b in zip(positions, positions[1:] + [n])]


def build_question_element(block: MoodleXmlBlock) -> ET.Element:
    """Build the `<question>` element for one `MoodleXmlBlock`."""
    question_el = ET.Element("question", attrib={"type": block.type})
    if block.name is not None:
        name_el = ET.SubElement(question_el, "name")
        ET.SubElement(name_el, "text").text = block.name
    if block.idnumber is not None:
        ET.SubElement(question_el, "idnumber").text = block.idnumber

    questiontext_el = ET.SubElement(question_el, "questiontext", attrib={"format": block.text_format})
    ET.SubElement(questiontext_el, "text").text = block.questiontext

    if block.general_feedback is not None:
        feedback_el = ET.SubElement(
            question_el, "generalfeedback", attrib={"format": block.text_format}
        )
        ET.SubElement(feedback_el, "text").text = block.general_feedback

    ET.SubElement(question_el, "defaultgrade").text = format_num(block.default_grade)

    if block.type == "multichoice":
        if block.single is not None:
            ET.SubElement(question_el, "single").text = bool_to_moodle(block.single)
        if block.shuffle_answers is not None:
            ET.SubElement(question_el, "shuffleanswers").text = bool_to_moodle(block.shuffle_answers)
    elif block.type == "shortanswer":
        ET.SubElement(question_el, "usecase").text = "0"

    for answer in block.answers:
        answer_el = ET.SubElement(
            question_el,
            "answer",
            attrib={"fraction": format_num(answer.fraction), "format": block.text_format},
        )
        ET.SubElement(answer_el, "text").text = answer.text
        if answer.feedback is not None:
            answer_feedback_el = ET.SubElement(
                answer_el, "feedback", attrib={"format": block.text_format}
            )
            ET.SubElement(answer_feedback_el, "text").text = answer.feedback
        if answer.tolerance is not None:
            ET.SubElement(answer_el, "tolerance").text = format_num(answer.tolerance)

    if block.grader_info is not None:
        graderinfo_el = ET.SubElement(question_el, "graderinfo", attrib={"format": block.text_format})
        ET.SubElement(graderinfo_el, "text").text = block.grader_info
    if block.response_format is not None:
        ET.SubElement(question_el, "responseformat").text = block.response_format

    if block.unit is not None:
        units_el = ET.SubElement(question_el, "units")
        unit_el = ET.SubElement(units_el, "unit")
        ET.SubElement(unit_el, "unit_name").text = block.unit
        ET.SubElement(unit_el, "unit_multiplier").text = "1"

    if block.tags:
        tags_el = ET.SubElement(question_el, "tags")
        for tag in block.tags:
            tag_el = ET.SubElement(tags_el, "tag")
            ET.SubElement(tag_el, "text").text = tag

    return question_el


def render_element(elem: ET.Element) -> str:
    """Indent `elem` in place and serialize it (no XML declaration)."""
    ET.indent(elem, space="  ")
    return ET.tostring(elem, encoding="unicode")


def text_node_content(parent: ET.Element) -> str:
    """Read the `<text>` child of `parent`, e.g. `<name><text>...</text></name>`."""
    text_el = parent.find("text")
    return (text_el.text if text_el is not None else None) or ""


def answer_from_element(answer_el: ET.Element) -> MoodleAnswer:
    """Parse one `<answer>` element into a `MoodleAnswer`."""
    feedback_el = answer_el.find("feedback")
    feedback = text_node_content(feedback_el) if feedback_el is not None else None
    tolerance_el = answer_el.find("tolerance")
    tolerance = (
        float(tolerance_el.text) if tolerance_el is not None and tolerance_el.text else None
    )
    return MoodleAnswer(
        text=text_node_content(answer_el),
        fraction=float(answer_el.get("fraction", "0")),
        feedback=feedback or None,
        tolerance=tolerance,
    )


def parse_bool_element(elem: ET.Element | None) -> bool | None:
    """Parse a `true`/`false` element's text, or `None` if the element is absent."""
    if elem is None or elem.text is None:
        return None
    return elem.text.strip().lower() == "true"


def bool_to_moodle(value: bool) -> str:
    """Render a bool the way Moodle XML spells it: `true`/`false`."""
    return "true" if value else "false"


def statement_correct(block: MoodleXmlBlock) -> bool:
    """A true/false block's statement is correct when its `True` answer has positive fraction."""
    for answer in block.answers:
        if answer.text.strip().lower() == "true":
            return answer.fraction > 0
    return bool(block.answers) and block.answers[0].fraction > 0


def essay_input_from_response_format(response_format: str | None) -> EssayInput:
    """Map a Moodle `<responseformat>` value to an MDQ essay `input` kind."""
    if response_format == "editor":
        return "text"
    if response_format == "plain":
        return "plain"
    if response_format == "monospaced":
        return "code"
    return "text"


def essay_response_format_from_input(input_: EssayInput) -> str:
    """Inverse of `essay_input_from_response_format`."""
    return {"text": "editor", "plain": "plain", "code": "monospaced"}[input_]


def common_prefix(strings: list[str]) -> str:
    """Return the longest common prefix of `strings` (empty if `strings` is empty)."""
    if not strings:
        return ""
    first, *rest = strings
    length = len(first)
    for s in rest:
        length = min(length, len(s))
        while first[:length] != s[:length]:
            length -= 1
    return first[:length]


def join_blocks(*parts: str | None) -> str:
    """Join non-empty, stripped parts with a blank line, as preamble/stem/epilogue do."""
    stripped = [part.strip() for part in parts if part]
    return "\n\n".join(part for part in stripped if part)


def numeric_tolerance(value: float, tolerance: Tolerance | None) -> float:
    """Resolve an MDQ `Tolerance` to a single absolute Moodle XML tolerance."""
    if tolerance is None:
        return 0.0
    if tolerance.absolute is not None:
        return tolerance.absolute
    if tolerance.relative is not None:
        return tolerance.relative * abs(value)
    return 0.0


def format_num(value: float) -> str:
    """Render a float compactly: as an integer when it has no fractional part."""
    if value == int(value):
        return str(int(value))
    return repr(value)
