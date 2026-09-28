from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal, NoReturn

from ..models import (
    Blank,
    ChoiceBlank,
    EssayQuestion,
    FillInQuestion,
    MultipleChoiceQuestion,
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
from .base import TRUE_FALSE_FALLBACK_STEM, ConversionBase
from .parser import StringParser

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
    "GiftEncoder",
    "GiftDecoder",
    "GiftParser",
    "escape_gift",
    "unescape_gift",
]

FORMAT_TAG_REGEX = re.compile(r"\[(html|moodle|plain|markdown)\]")
CREDIT_TAG_REGEX = re.compile(r"%(-?\d+(?:\.\d+)?)%")
ESCAPE_REGEX = re.compile(r"[:=~{}#\\]")
UNESCAPE_REGEX = re.compile(r"\\(.)")


class Gift(ConversionBase["GiftQuestion"]):
    """
    GIFT is Moodle's plain-text question format.

    It supports multiple-choice, true/false, numeric, short-answer and
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

    supports = {
        "multiple-choice": "both",
        "true-false": "both",
        "numeric": "both",
        "essay": "both",
        "fill-in": "both",
        "short-answer": "both",
        # matching: not yet implemented in MDQ
        # multiple-numeric: not yet implemented in MDQ
    }

    def from_mdq(self, question: Question) -> GiftQuestion:
        return GiftEncoder().encode(question)

    def to_mdq(self, gift: GiftQuestion) -> Question:
        return GiftDecoder().decode(gift)

    def parse(self, source: str) -> GiftQuestion:
        return GiftParser(source).parse()


@dataclass
class GiftOption:
    """One `=`/`~` answer entry."""

    text: str
    credit: float = 0.0
    feedback: str | None = None


@dataclass
class GiftNumericOption:
    """One numeric answer entry: a value, tolerance, credit and feedback."""

    value: float
    tolerance: float = 0.0
    credit: float = 1.0
    feedback: str | None = None


@dataclass
class GiftEssay:
    """An open-ended answer body: `{}`."""


@dataclass
class GiftBoolean:
    """A true/false answer body: `{T}` / `{F}`."""

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

    def __str__(self) -> str:
        lines: list[str] = []
        if self.comment:
            lines.extend(f"// {line}" for line in self.comment.split("\n"))

        head = f"::{escape_gift(self.title)}:: " if self.title is not None else ""
        head += f"[{self.text_format}]"
        stem = escape_gift(self.stem)
        if stem:
            head += f" {stem}"

        body = render_gift_answer(self.answer)
        if self.general_feedback:
            sep = " " if body else ""
            body = f"{body}{sep}#### {escape_gift(self.general_feedback)}"

        line = f"{head} {{{body}}}"
        if self.tail:
            line += escape_gift(self.tail)
        lines.append(line)
        return "\n".join(lines)


@dataclass
class GiftQuestion:
    """A GIFT question: one block, or several for a true/false group."""

    blocks: list[GiftBlock] = field(default_factory=list)

    def __str__(self) -> str:
        return "\n\n".join(str(block) for block in self.blocks)


class GiftEncoder:
    """Converts an MDQ `Question` into a `GiftQuestion`."""

    def encode(self, question: Question) -> GiftQuestion:
        """Dispatch on `question.type` to the matching `block_from_*` builder."""
        if isinstance(question, MultipleChoiceQuestion):
            return GiftQuestion(blocks=[self.block_from_choice(question)])
        if isinstance(question, ShortAnswerQuestion):
            return GiftQuestion(blocks=[self.block_from_short(question)])
        if isinstance(question, NumericQuestion):
            return GiftQuestion(blocks=[self.block_from_numeric(question)])
        if isinstance(question, EssayQuestion):
            return GiftQuestion(blocks=[self.block_from_essay(question)])
        if isinstance(question, TrueFalseQuestion):
            return GiftQuestion(blocks=self.blocks_from_true_false(question))
        if isinstance(question, FillInQuestion):
            return GiftQuestion(blocks=[self.block_from_fill_in(question)])
        raise ValueError(f"GIFT does not support {question.type!r} questions")

    def block_from_choice(self, question: MultipleChoiceQuestion) -> GiftBlock:
        options = []
        for choice in question.choices:
            if choice.score is None:
                raise ValueError("cannot convert to GIFT: every choice must have a score")
            options.append(
                GiftOption(text=choice.text, credit=choice.score, feedback=choice.feedback)
            )
        return GiftBlock(
            stem=join_blocks(question.preamble, question.stem),
            answer=GiftChoice(options=options),
            tail=question.epilogue or "",
            title=question.title,
            comment=question.comment,
            text_format="markdown",
        )

    def block_from_short(self, question: ShortAnswerQuestion) -> GiftBlock:
        if question.one_of is None:
            raise ValueError(
                "cannot convert to GIFT: short-answer question needs `oneOf` "
                "(regex/accept/openEnded answers are not supported)"
            )
        options = [GiftOption(text=answer, credit=1.0) for answer in question.one_of]
        return GiftBlock(
            stem=join_blocks(question.preamble, question.stem),
            answer=GiftShort(options=options),
            tail=question.epilogue or "",
            title=question.title,
            comment=question.comment,
            text_format="markdown",
        )

    def block_from_numeric(self, question: NumericQuestion) -> GiftBlock:
        value = gift_numeric_value(question.answer)
        tolerance = gift_numeric_tolerance(value, question.tolerance)
        return GiftBlock(
            stem=join_blocks(question.preamble, question.stem),
            answer=GiftNumeric(options=[GiftNumericOption(value=value, tolerance=tolerance)]),
            tail=question.epilogue or "",
            title=question.title,
            comment=question.comment,
            text_format="markdown",
        )

    def block_from_essay(self, question: EssayQuestion) -> GiftBlock:
        return GiftBlock(
            stem=join_blocks(question.preamble, question.stem),
            answer=GiftEssay(),
            tail=question.epilogue or "",
            title=question.title,
            comment=question.comment,
            general_feedback=question.answer_key,
            text_format="markdown",
        )

    def blocks_from_true_false(self, question: TrueFalseQuestion) -> list[GiftBlock]:
        # The fallback stem stands for "no shared text", so it round-trips.
        stem = None if question.stem == TRUE_FALSE_FALLBACK_STEM else question.stem
        group_stem = join_blocks(question.preamble, stem)
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
                )
            )
        return blocks

    def block_from_fill_in(self, question: FillInQuestion) -> GiftBlock:
        if len(question.blanks) != 1:
            raise ValueError(
                "cannot convert to GIFT: fill-in question must have exactly one blank"
            )
        blank = question.blanks[0]
        marker = f"[^{blank.id}]"
        stem_part, sep, tail_part = question.stem.partition(marker)
        if not sep:
            raise ValueError(
                f"cannot convert to GIFT: stem does not contain blank marker {marker!r}"
            )

        if isinstance(blank, ChoiceBlank):
            # An unmarked choice inside a blank keeps `score = None`, which
            # MDQ reads as zero credit; only top-level choices are strict.
            choice_options = [
                GiftOption(
                    text=choice.text,
                    credit=choice.score or 0.0,
                    feedback=choice.feedback,
                )
                for choice in blank.choices
            ]
            answer: GiftAnswer = GiftChoice(options=choice_options)
        elif isinstance(blank, ShortAnswerBlank):
            if blank.one_of is None:
                raise ValueError(
                    "cannot convert to GIFT: short-answer blank needs `oneOf`"
                )
            answer = GiftShort(
                options=[GiftOption(text=answer_text, credit=1.0) for answer_text in blank.one_of]
            )
        else:
            value = gift_numeric_value(blank.answer)
            tolerance = gift_numeric_tolerance(value, blank.tolerance)
            answer = GiftNumeric(options=[GiftNumericOption(value=value, tolerance=tolerance)])

        return GiftBlock(
            stem=join_blocks(question.preamble, stem_part),
            answer=answer,
            tail=join_blocks(tail_part, question.epilogue),
            title=question.title,
            comment=question.comment,
            text_format="markdown",
        )


class GiftDecoder:
    """Converts a `GiftQuestion` into an MDQ `Question`."""

    def decode(self, gift: GiftQuestion) -> Question:
        """A single block converts directly; several blocks must form a true/false group."""
        if not gift.blocks:
            raise ValueError("GIFT question has no blocks")
        if len(gift.blocks) == 1:
            return self.block_to_mdq(gift.blocks[0])
        if all(isinstance(b.answer, GiftBoolean) for b in gift.blocks):
            return self.true_false_from_blocks(gift.blocks)
        raise ValueError(
            "a GIFT question group with more than one block is only "
            "supported when every block is a true/false statement"
        )

    def block_to_mdq(self, block: GiftBlock) -> Question:
        answer = block.answer

        if isinstance(answer, GiftEssay):
            return EssayQuestion(
                stem=block.stem,
                answer_key=block.general_feedback,
                title=block.title,
                comment=block.comment,
            )

        if isinstance(answer, GiftBoolean):
            if block.tail:
                raise ValueError(
                    "GIFT missing-word tail is not supported for boolean answers"
                )
            return MultipleChoiceQuestion(
                stem=block.stem,
                choices=[
                    ScoredChoice(text="True", score=1.0 if answer.value else 0.0),
                    ScoredChoice(text="False", score=0.0 if answer.value else 1.0),
                ],
                title=block.title,
                comment=block.comment,
            )

        if block.tail:
            blank = self.blank_from_answer(answer)
            stem = f"{block.stem}[^blank]{block.tail}".strip()
            return FillInQuestion(
                stem=stem, blanks=[blank], title=block.title, comment=block.comment
            )

        if isinstance(answer, GiftChoice):
            return MultipleChoiceQuestion(
                stem=block.stem,
                choices=[
                    ScoredChoice(text=o.text, score=o.credit, feedback=o.feedback)
                    for o in answer.options
                ],
                title=block.title,
                comment=block.comment,
            )

        if isinstance(answer, GiftShort):
            return ShortAnswerQuestion(
                stem=block.stem,
                one_of=[o.text for o in answer.options],
                title=block.title,
                comment=block.comment,
            )

        if isinstance(answer, GiftNumeric):
            opt = answer.options[0]
            tolerance = Tolerance(absolute=opt.tolerance) if opt.tolerance else None
            return NumericQuestion(
                stem=block.stem,
                answer=opt.value,
                tolerance=tolerance,
                title=block.title,
                comment=block.comment,
            )

        raise TypeError(f"unsupported GIFT answer kind: {type(answer).__name__}")

    def blank_from_answer(self, answer: GiftAnswer) -> Blank:
        if isinstance(answer, GiftChoice):
            return ChoiceBlank(
                id="blank",
                choices=[
                    ScoredChoice(text=o.text, score=o.credit, feedback=o.feedback)
                    for o in answer.options
                ],
            )
        if isinstance(answer, GiftShort):
            return ShortAnswerBlank(id="blank", one_of=[o.text for o in answer.options])
        if isinstance(answer, GiftNumeric):
            opt = answer.options[0]
            tolerance = Tolerance(absolute=opt.tolerance) if opt.tolerance else None
            return NumericBlank(id="blank", answer=opt.value, tolerance=tolerance)
        raise ValueError(
            f"GIFT missing-word tail is not supported for {type(answer).__name__} answers"
        )

    def true_false_from_blocks(self, blocks: list[GiftBlock]) -> TrueFalseQuestion:
        stems = [b.stem for b in blocks]
        prefix = common_prefix(stems)
        split = prefix.rfind("\n\n")

        if split == -1:
            group_stem = TRUE_FALSE_FALLBACK_STEM
            statement_texts = stems
        else:
            group_stem = prefix[:split].strip()
            boundary = split + 2
            statement_texts = [s[boundary:] for s in stems]

        choices = []
        for text, block in zip(statement_texts, blocks):
            assert isinstance(block.answer, GiftBoolean)
            choices.append(Statement(text=text.strip(), correct=block.answer.value))

        return TrueFalseQuestion(
            stem=group_stem,
            choices=choices,
            title=blocks[0].title,
            comment=blocks[0].comment,
        )


class GiftParser(StringParser[GiftQuestion]):
    """
    Character-level GIFT parser.

    GIFT is not line-oriented (an answer body may span several lines), so
    parsing scans `self.source` directly by character offset instead of
    using the line-based helpers in `StringParser`.
    """

    def start(self) -> GiftQuestion:
        blocks = [
            self.parse_block(raw, offset) for raw, offset in split_blocks(self.source)
        ]
        self.lines.clear()
        if not blocks:
            self.fail("no GIFT question found", 0)
        return GiftQuestion(blocks=blocks)

    def parse_block(self, raw: str, offset: int) -> GiftBlock:
        lines = raw.split("\n")
        comment_lines: list[str] = []
        index = 0
        consumed = offset
        while index < len(lines) and lines[index].lstrip().startswith("//"):
            comment_lines.append(lines[index].lstrip()[2:].strip())
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
        stem = unescape_gift(rest[pos:brace_pos]).strip()
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
        tail = unescape_gift(tail_raw).strip()

        answer, general_feedback = self.parse_answer(body_raw, body_offset)
        return GiftBlock(
            stem=stem,
            answer=answer,
            tail=tail,
            title=title,
            comment=comment,
            text_format=text_format,
            general_feedback=general_feedback,
        )

    def parse_answer(self, body_raw: str, offset: int) -> tuple[GiftAnswer, str | None]:
        fb_pos = find_unescaped(body_raw, "####")
        if fb_pos != -1:
            content_raw = body_raw[:fb_pos]
            general_feedback = unescape_gift(body_raw[fb_pos + 4 :]).strip() or None
        else:
            content_raw = body_raw
            general_feedback = None

        content = content_raw.strip()
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
        options = []
        for entry in split_unescaped(content, "=~"):
            credit = 1.0 if entry[0] == "=" else 0.0
            rest = entry[1:]
            match = CREDIT_TAG_REGEX.match(rest)
            if match:
                credit = float(match.group(1)) / 100
                rest = rest[match.end() :]
            hash_pos = find_unescaped(rest, "#")
            text_raw, feedback_raw = (
                (rest, None) if hash_pos == -1 else (rest[:hash_pos], rest[hash_pos + 1 :])
            )
            feedback = unescape_gift(feedback_raw).strip() if feedback_raw else None
            options.append(
                GiftOption(
                    text=unescape_gift(text_raw).strip(),
                    credit=credit,
                    feedback=feedback or None,
                )
            )
        return options

    def parse_numeric_options(self, content: str, offset: int) -> list[GiftNumericOption]:
        body = content[1:]
        if find_unescaped(body, "=") == -1:
            value, tolerance = self.parse_numeric_spec(body.strip(), offset)
            return [GiftNumericOption(value=value, tolerance=tolerance)]

        options = []
        for entry in split_unescaped(body, "="):
            rest = entry[1:]
            credit = 1.0
            match = CREDIT_TAG_REGEX.match(rest)
            if match:
                credit = float(match.group(1)) / 100
                rest = rest[match.end() :]
            hash_pos = find_unescaped(rest, "#")
            spec_raw, feedback_raw = (
                (rest, None) if hash_pos == -1 else (rest[:hash_pos], rest[hash_pos + 1 :])
            )
            value, tolerance = self.parse_numeric_spec(spec_raw.strip(), offset)
            feedback = unescape_gift(feedback_raw).strip() if feedback_raw else None
            options.append(
                GiftNumericOption(
                    value=value,
                    tolerance=tolerance,
                    credit=credit,
                    feedback=feedback or None,
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
        prefix = self.source[:pos]
        self.lineno = prefix.count("\n")
        self.colno = pos - prefix.rfind("\n") - 1
        self.error(message)


def render_gift_answer(answer: GiftAnswer) -> str:
    """Render a GIFT answer body's content, without the enclosing braces."""
    if isinstance(answer, GiftEssay):
        return ""
    if isinstance(answer, GiftBoolean):
        return "TRUE" if answer.value else "FALSE"
    if isinstance(answer, GiftChoice):
        return " ".join(render_gift_option(o) for o in answer.options)
    if isinstance(answer, GiftShort):
        return " ".join(render_gift_short_option(o) for o in answer.options)
    if isinstance(answer, GiftNumeric):
        return render_gift_numeric(answer.options)
    raise TypeError(f"unsupported GIFT answer kind: {type(answer).__name__}")


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
        entry += format_num(opt.value)
        if opt.tolerance:
            entry += f":{format_num(opt.tolerance)}"
        if opt.feedback:
            entry += f"#{escape_gift(opt.feedback)}"
        parts.append(entry)
    return "# " + " ".join(parts)


def render_gift_option(option: GiftOption) -> str:
    """Render one choice answer entry: `=` for full credit, `~` otherwise."""
    if option.credit == 1.0:
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
    a `%NN%` tag whenever it isn't the default 1.0.
    """
    entry = "="
    if option.credit != 1.0:
        entry += f"%{format_credit(option.credit)}%"
    return entry + render_gift_option_tail(option)


def render_gift_option_tail(option: GiftOption) -> str:
    """Render an option's escaped text and optional `#feedback` suffix."""
    tail = escape_gift(option.text)
    if option.feedback:
        tail += f"#{escape_gift(option.feedback)}"
    return tail


def format_credit(credit: float) -> str:
    """Render a 0..1 credit fraction as a GIFT percentage, e.g. `0.5` -> `"50"`."""
    return format_num(credit * 100)


def format_num(value: float) -> str:
    """Render a float compactly: as an integer when it has no fractional part."""
    if value == int(value):
        return str(int(value))
    return repr(value)


def escape_gift(text: str) -> str:
    """Backslash-escape GIFT's special characters (`:=~{}#\\`)."""
    return ESCAPE_REGEX.sub(lambda m: "\\" + m.group(), text)


def unescape_gift(text: str) -> str:
    """Undo `escape_gift`."""
    return UNESCAPE_REGEX.sub(r"\1", text)


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


def split_blocks(source: str) -> list[tuple[str, int]]:
    """
    Split GIFT source into `(block_text, start_offset)` pairs.

    Blocks are separated by blank lines, except inside an unescaped
    `{...}` answer body, which may itself span blank lines.
    """
    blocks: list[tuple[str, int]] = []
    current: list[str] = []
    current_start: int | None = None
    depth = 0
    closed = False
    in_comment = True  # still within the block's leading `//` comment lines
    offset = 0

    for line in source.split("\n"):
        blank = not line.strip()
        if blank and not current:
            offset += len(line) + 1
            continue  # blank lines between blocks
        if blank and depth == 0 and closed:
            blocks.append(("\n".join(current), current_start or 0))
            current = []
            current_start = None
            closed = False
            in_comment = True
            offset += len(line) + 1
            continue

        if current_start is None:
            current_start = offset
        current.append(line)
        # A leading `// ...` comment line's braces don't count towards the
        # answer body: `parse_block` strips these lines before parsing.
        if in_comment and line.lstrip().startswith("//"):
            pass
        else:
            in_comment = False
            depth, closed = update_brace_state(line, depth, closed)
        offset += len(line) + 1

    if current:
        blocks.append(("\n".join(current), current_start or 0))
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


def gift_numeric_value(answer: float | str) -> float:
    """Resolve an MDQ numeric `answer` (a rational string or a float) to a float."""
    if isinstance(answer, str):
        return float(Fraction(answer))
    return float(answer)


def gift_numeric_tolerance(value: float, tolerance: Tolerance | None) -> float:
    """Resolve an MDQ `Tolerance` to a single absolute GIFT tolerance."""
    if tolerance is None:
        return 0.0
    if tolerance.absolute is not None:
        return tolerance.absolute
    if tolerance.relative is not None:
        return tolerance.relative * abs(value)
    return 0.0
