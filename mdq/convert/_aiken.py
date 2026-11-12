"""
The Aiken converter: multiple choice questions only, to and from Aiken text.

Aiken has no metadata, feedback or partial credit, so an export reports each
loss as a diagnostic.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from re import Pattern
from string import ascii_lowercase
from typing import NoReturn

from ..models import MultipleChoiceQuestion, Question, ScoredChoice
from ._base import ConversionBase, ParserError, Report
from ._moodle import GENERAL_FEEDBACK_KEY, effective_scores, report_dropped_fields

CHOICE_REGEX = re.compile(r"(?P<letter>[a-zA-Z])[.)]\s+(?P<choice>[^\n]*)")
NEWLINE_REGEX = re.compile(r"\s*\n\s*")
WS_REGEX = re.compile(r"\s+")

__all__ = ["Aiken", "AikenQuestion", "AikenParser", "CHOICE_REGEX"]

#: The attributes Aiken has no place for.
_DROPPED_FIELDS = frozenset(
    {
        "id", "title", "tags", "weight", "shuffle", "grading", "comment", "author", "uuid",
        "locale", "attachments",
    }
)


class Aiken(ConversionBase["AikenQuestion"]):
    """
    Aiken is a very simple format for multiple choice questions.

    ```
    Question stem

    A. Option 1
    B. Option 2
    C. Option 3

    ANSWER: a
    ```

    Aiken carries no metadata, so a conversion drops `id`, `title` and every
    feedback string, and collapses partial credit to 1.0 on the highest
    scoring choice and 0.0 elsewhere. Each loss is a diagnostic.

    For more details: https://docs.moodle.org/en/Aiken_format
    """

    name = "Aiken"
    supports = frozenset({"multiple-choice"})

    def from_mdq(self, question: Question, report: Report, /) -> AikenQuestion:
        assert isinstance(question, MultipleChoiceQuestion), (
            f"{question.type!r} is excluded by `Aiken.supports`"
        )
        report_dropped_fields(
            question,
            report,
            _DROPPED_FIELDS,
            children=frozenset({"comment", "feedback"}),
        )
        if question.meta and GENERAL_FEEDBACK_KEY in question.meta:
            report.warning(
                "field-dropped",
                f"Aiken has no place for `meta.{GENERAL_FEEDBACK_KEY}`: it is dropped",
                ("meta", GENERAL_FEEDBACK_KEY),
            )
        if len(question.choices) > len(ascii_lowercase):
            report.error(
                "too-many-choices",
                f"Aiken supports at most {len(ascii_lowercase)} choices, "
                f"got {len(question.choices)}",
                ("choices",),
            )

        scores = effective_scores(question)
        # `-i` breaks ties towards the first of the highest scoring choices.
        answer = max(range(len(scores)), key=lambda i: (scores[i], -i))
        if scores != [1.0 if i == answer else 0.0 for i in range(len(scores))]:
            report.warning(
                "partial-credit-dropped",
                "Aiken has one correct choice: the first choice with the highest score "
                f"({scores[answer]!r}) is correct, and the others are wrong",
                ("choices",),
            )
        for index, choice in enumerate(question.choices):
            if NEWLINE_REGEX.search(choice.text.strip()):
                report.warning(
                    "line-breaks-dropped",
                    "an Aiken choice has one line: its line breaks are joined with a space",
                    ("choices", index, "text"),
                )

        parts = [question.stem, question.epilogue]
        return AikenQuestion(
            stem="\n\n".join(filter(None, parts)),
            choices=[choice.text for choice in question.choices],
            answer=answer,
        )

    def to_mdq(self, aiken: AikenQuestion, report: Report, /) -> MultipleChoiceQuestion:
        return MultipleChoiceQuestion(
            stem=aiken.stem,
            choices=[
                ScoredChoice(text=choice, score=1.0 if i == aiken.answer else 0.0)
                for i, choice in enumerate(aiken.choices)
            ],
        )

    def parse(self, source: str, report: Report | None = None, /) -> AikenQuestion:
        parser = AikenParser(source)
        return parser.parse()


@dataclass
class AikenQuestion:
    stem: str
    choices: list[str]
    answer: int

    def __post_init__(self) -> None:
        # A choice occupies exactly one Aiken line, so a newline in its text
        # would render source that no longer reparses.
        self.choices = [NEWLINE_REGEX.sub(" ", text).strip() for text in self.choices]

        if len(self.choices) > len(ascii_lowercase):
            raise ValueError(
                f"Aiken supports at most {len(ascii_lowercase)} choices, "
                f"got {len(self.choices)}"
            )
        if not 0 <= self.answer < len(self.choices):
            raise ValueError(
                f"answer index {self.answer} does not reference one of the "
                f"{len(self.choices)} choices"
            )

    def __str__(self) -> str:
        lines = [self.stem, ""]
        for i, choice in enumerate(self.choices):
            letter = ascii_lowercase[i]
            lines.append(f"{letter}. {choice}")

        answer = ascii_lowercase[self.answer]
        lines.append("")
        lines.append(f"ANSWER: {answer}")
        return "\n".join(lines)


class StringParser[T]:
    """
    Parser primitives for string-based formats.

    The parser always break on lines.
    """

    def __init__(self, source: str):
        self.source = source
        # Moodle reads the file with PHP's `file()`, which breaks lines only at
        # "\n": a form feed, a vertical tab or U+2028 is text, not a line break.
        self.original_lines = source.replace("\r\n", "\n").split("\n")
        if self.original_lines[-1] == "":
            self.original_lines.pop()
        self.lineno = 0
        self.colno = 0
        self.lines = deque(self.original_lines)

    def parse(self) -> T:
        """
        Parse question.
        """
        result = self.start()
        self.ws()
        if self.lines:
            i = self.lineno + 1
            j = len(self.lines)
            raise ParserError(f"unparsed lines: {i}:{j}", self.lineno, self.colno)
        return result

    def start(self) -> T:
        """
        Start the recursive descent.
        """
        raise NotImplementedError

    def peek(self) -> str:
        """
        Peek the next line.
        """
        try:
            return self.lines[0]
        except IndexError:
            return ""

    def read(self) -> str:
        """
        Read the next line.
        """
        try:
            result = self.lines.popleft()
        except IndexError:
            self.error("EOF reached")

        self.lineno += 1
        self.colno = 0
        return result

    def ws(self) -> None:
        """
        Consume whitespace and empty lines.
        """
        while self.lines and (not self.lines[0] or self.lines[0].isspace()):
            self.read()
        if m := WS_REGEX.match(self.peek()):
            self.colno += m.end()
            self.lines[0] = self.lines[0][m.end() :]

    def expect(
        self,
        pattern: str | Pattern[str],
        /,
        message: str | None = None,
        *,
        full: bool = False,
        raw: bool = False,
    ) -> str:
        """
        Expect pattern and raise ParserError if not match.
        """
        match = self.match(pattern, full=full, raw=raw)
        if match is None:
            if message is None:
                message = f"expect: {pattern!r}"
            self.error(message)
        return match

    def match(
        self, pattern: str | Pattern[str], /, *, full: bool = False, raw: bool = False
    ) -> str | None:
        """
        Match line against regex pattern.

        Consume the string and return it, if match. Return None if there is no Match.
        """

        if raw and isinstance(pattern, str):
            if full:
                return self.read() if self.peek() == pattern else None

            if self.peek().startswith(pattern):
                if self.lines[0] == pattern:
                    return self.read()
                self.lines[0] = self.lines[0][len(pattern) :]
                self.colno += len(pattern)
                return pattern
            return None

        if not isinstance(pattern, Pattern):
            pattern = re.compile(pattern)

        result = self.match_group(pattern, full=full)
        return None if result is None else result[""]

    def match_group(
        self, pattern: Pattern[str], /, *, full: bool = False
    ) -> dict[str, str] | None:
        """
        Match line against regex pattern.

        Consume the string and return it, if match. Return None if there is no Match.
        """

        go = pattern.fullmatch if full else pattern.match

        if m := go(self.peek()):
            start, end = m.span()
            value = m.group(0)
            self.lines[0] = self.lines[0][end:]
            self.colno += end

            if not self.lines[0]:
                self.lines.popleft()
                self.lineno += 1
                self.colno = 0

            return {**m.groupdict(), "": value}

        return None

    def error(self, message: str) -> NoReturn:
        """
        Raise error
        """
        raise ParserError(message, self.lineno, self.colno)


class AikenParser(StringParser[AikenQuestion]):
    def start(self) -> AikenQuestion:
        stem_lines = []

        while not (m := self.match_group(CHOICE_REGEX, full=True)):
            stem_lines.append(self.read())

        choices = [self._choice_text(m, index=0)]
        while m := self.match_group(CHOICE_REGEX, full=True):
            choices.append(self._choice_text(m, index=len(choices)))

        self.ws()
        self.expect("ANSWER:", full=False)
        self.ws()

        char = self.read().strip().lower()
        if len(char) != 1 or char not in ascii_lowercase:
            self.error("answer must be a single letter")
        answer = ascii_lowercase.index(char)

        if not 0 <= answer < len(choices):
            self.error(
                f"ANSWER {char!r} does not reference one of the "
                f"{len(choices)} parsed choices"
            )

        return AikenQuestion(
            stem="\n".join(stem_lines).strip(),
            choices=choices,
            answer=answer,
        )

    def _choice_text(self, match: dict[str, str], *, index: int) -> str:
        """
        Validate that a matched choice's letter is the expected sequential
        letter (a, b, c, ...) for its position, then return its text.
        """
        letter = match["letter"].lower()
        if index >= len(ascii_lowercase):
            self.error(f"Aiken supports at most {len(ascii_lowercase)} choices")
        expected = ascii_lowercase[index]
        if letter != expected:
            self.error(
                f"expected choice {expected.upper()!r}, got {letter.upper()!r}"
            )
        return match["choice"]
