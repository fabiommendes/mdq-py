from __future__ import annotations

import re
from dataclasses import dataclass
from string import ascii_lowercase

from ..models import MultipleChoiceQuestion, Question, ScoredChoice
from ._base import ConversionBase
from ._string_parser import StringParser

CHOICE_REGEX = re.compile(r"(?P<letter>[a-zA-Z])[.)]\s+(?P<choice>[^\n]*)")
NEWLINE_REGEX = re.compile(r"\s*\n\s*")

__all__ = ["Aiken", "AikenQuestion", "AikenParser", "CHOICE_REGEX"]


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
    scoring choice and 0.0 elsewhere.

    For more details: https://docs.moodle.org/en/Aiken_format
    """

    supports = {"multiple-choice": "both"}

    def from_mdq(self, question: Question) -> AikenQuestion:
        if not isinstance(question, MultipleChoiceQuestion):
            raise ValueError(f"Aiken does not support {question.type!r} questions")

        scores = [choice.score for choice in question.choices]
        if any(score is None for score in scores):
            raise ValueError(
                "cannot convert to Aiken: every choice must have a score"
            )

        parts = [question.preamble, question.stem, question.epilogue]
        return AikenQuestion(
            stem="\n\n".join(filter(None, parts)),
            choices=[choice.text for choice in question.choices],
            # `-i` breaks ties towards the first of the highest scoring choices.
            answer=max(range(len(scores)), key=lambda i: (scores[i], -i)),
        )

    def to_mdq(self, aiken: AikenQuestion) -> MultipleChoiceQuestion:
        return MultipleChoiceQuestion(
            stem=aiken.stem,
            choices=[
                ScoredChoice(text=choice, score=1.0 if i == aiken.answer else 0.0)
                for i, choice in enumerate(aiken.choices)
            ],
        )

    def parse(self, source: str) -> AikenQuestion:
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


class AikenParser(StringParser[AikenQuestion]):
    def start(self):
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
