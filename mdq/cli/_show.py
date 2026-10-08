"""
`mdq show`: human-readable console presentation of a parsed MDQ document.

`models.BaseQuestion.render()` is the round-trip serializer: it turns a
model back into MDQ Markdown, byte for byte close enough to parse back
into the same model. This module is a different concern entirely -- a
*view* for a human at a terminal, not a serializer. It draws each
question as a card, the way a quiz page would show it: a type badge and a
title on the border, metadata as chips, radio buttons and checkboxes for
choices, empty input fields for typed answers. Rich-text fields (preamble,
stem, epilogue, choice text, feedback, comment, an essay's answer key) go
through `rich.markdown.Markdown` since they are Markdown themselves.

The answer key -- whichever shape it takes for a given question type -- is
always set apart from the plain choices/blanks by color and, where it
stands alone, its own bordered panel. With the key hidden, the view shows
what a student would see.

Colors, glyphs and borders come from a `Theme` (see `_show_theme`).

The interface is small on purpose: `show_source` for a whole document (a
question or an exam -- told apart by content, via `mdq.load`/`mdq.parse`),
plus `render_question` and `render_exam` for callers that already hold a
model.

Everything that can embed document content goes through `Text`, never a
markup `str`: a title, tag or id is free to carry square brackets, and
Rich would parse them as markup (a stray `[/]` would even raise).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

import typer
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.segment import Segment
from rich.table import Table
from rich.text import Text
from rich.theme import Theme as ConsoleTheme

from .. import _schedule, models
from ..models import _render
from .._banks import FileLoader, QuestionBank
from .._loading import InvalidDocument, parse
from ..types import NumericDomain, Source, Unmatched
from ._app import app
from ._show_theme import Theme, ThemeName, resolve_theme

#: Widest card. A card as wide as a 200-column terminal is hard to read.
_MAX_CARD_WIDTH = 100
#: Width of the column that holds a choice's radio button or checkbox.
_MARK_WIDTH = 9
#: Width of the mock input field of a typed answer.
_INPUT_WIDTH = 32
#: `[^id]` in a fill-in stem, with an optional `/kind` and `/option`.
_BLANK_REF = re.compile(r"\[\^([^\]/\s]+)(?:/[^\]]*)?\]")


def show_source(
    src: Source,
    console: Console,
    *,
    show_answer_key: bool = True,
    bank: QuestionBank | None = None,
    theme: ThemeName | str | None = None,
) -> None:
    """
    Load an MDQ document and print a human-readable rendering of it.

    Dispatches on the document's own kind: an exam is rendered by
    `render_exam`, a single question by `render_question`.

    Args:
        src: Anything `mdq.parse` accepts -- MDQ source text, a `Path`,
            or an open file. A `Path` resolves an exam's include blocks
            against its own directory unless `bank` overrides it; text
            has no directory, so its include blocks stay unresolved.
        console: Where to print the rendering.
        show_answer_key: When false, everything that would reveal the
            correct answer (correctness marks, an essay's answer key, a
            short answer's accepted values, a numeric answer, ...) is
            replaced by a note that it is hidden. Choices, statements
            and blanks themselves are still shown -- only the key is
            hidden, as when previewing a question for a student.
        bank: Resolves an exam's include blocks, if given. Ignored for a
            question document.
        theme: `dark`, `light`, `plain` or `auto` (the default).

    Raises:
        InvalidDocument: `src` is not a valid MDQ document.
    """
    document = parse(src)
    if isinstance(document, models.Exam):
        if bank is None and isinstance(src, Path):
            bank = FileLoader(src.parent)
        if bank is not None:
            document = document.resolve(bank)
        if not any(isinstance(q, models.IncludeAll) for q in document.questions):
            document = document.with_ids()
        render_exam(document, console, show_answer_key=show_answer_key, theme=theme)
    else:
        render_question(
            document.with_ids(), console, show_answer_key=show_answer_key, theme=theme
        )


def render_question(
    question: models.Question,
    console: Console,
    *,
    show_answer_key: bool = True,
    theme: ThemeName | str | None = None,
) -> None:
    """Print a human-readable rendering of a single question."""
    with _View(console, theme, show_answer_key) as view:
        console.print(view.question_card(question))


def render_exam(
    exam: models.Exam,
    console: Console,
    *,
    show_answer_key: bool = True,
    theme: ThemeName | str | None = None,
) -> None:
    """Print a human-readable rendering of an exam and every question in it."""
    with _View(console, theme, show_answer_key) as view:
        view.exam = exam
        console.print(view.exam_banner(exam))
        for index, question in enumerate(exam.questions, start=1):
            console.print()
            console.print(view.question_divider(index, question))
            if isinstance(question, models.Include):
                console.print(view.placeholder(f"Includes question {question.include!r}."))
            elif isinstance(question, models.IncludeAll):
                console.print(
                    view.placeholder(f"Includes questions matching {question.include_all!r}.")
                )
            else:
                console.print(view.question_card(question))


class _LeftBar:
    """Draws `inner` with a colored bar down its left edge, like a quote."""

    def __init__(self, inner: RenderableType, bar: str, style: str) -> None:
        self.inner = inner
        self.bar = bar
        self.style = style

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        gutter = Segment(f"{self.bar} ", console.get_style(self.style))
        lines = console.render_lines(
            self.inner, options.update(width=max(options.max_width - 2, 1)), pad=True
        )
        for line in lines:
            yield gutter
            yield from line
            yield Segment.line()


class _View:
    """
    One rendering pass: the console, the theme and whether to show the key.

    A context manager because it installs the theme's Markdown styles on
    the console for as long as it renders.
    """

    def __init__(
        self,
        console: Console,
        theme: ThemeName | str | None,
        show_answer_key: bool,
    ) -> None:
        self.console = console
        self.t = resolve_theme(theme, console)
        self.g = self.t.glyphs
        self.show_key = show_answer_key
        #: The exam being rendered, if any. A question inherits its locale
        #: and author, so a card does not repeat the ones that match.
        self.exam: models.Exam | None = None

    def __enter__(self) -> _View:
        if self.t.inline_code:
            self.console.push_theme(ConsoleTheme({"markdown.code": self.t.inline_code}))
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self.t.inline_code:
            self.console.pop_theme()

    #
    # Cards
    #
    def question_card(self, question: models.Question) -> RenderableType:
        heading = question.title or question.id or question.type
        title = Text.assemble(
            (f" {_type_label(question.type)} ", self.t.badge_style(question.type)),
            "  ",
            (heading, f"bold {self.t.fg}".strip()),
        )
        subtitle = (
            Text(f" {question.id} ", style=self.t.muted)
            if question.id and question.id != heading
            else None
        )

        parts: list[RenderableType] = []
        chips = self._question_chips(question)
        if chips.plain:
            parts += [chips, _GAP]
        for text in (question.preamble, question.stem):
            if text:
                parts.append(self._md(self._mark_blanks(text, question)))
        parts.append(_GAP)
        parts += self._body(question)
        if question.epilogue:
            parts += [_GAP, self._md(question.epilogue)]
        if self.show_key and question.comment:
            parts += [
                _GAP,
                self._callout(
                    f"{self.g.note} Instructor note",
                    self._md(question.comment),
                    border=self.t.note,
                    style=self.t.note_style,
                ),
            ]
        return Panel(
            Group(*parts),
            title=title,
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
            box=self.t.card_box,
            border_style=self.t.border,
            style=self.t.card_style,
            padding=(1, 2),
            width=self._card_width(),
        )

    def exam_banner(self, exam: models.Exam) -> RenderableType:
        heading = exam.title or exam.id or "Exam"
        title = Text.assemble(
            (" EXAM ", self.t.badge_style("exam")), "  ", (heading, f"bold {self.t.fg}".strip())
        )
        subtitle = (
            Text(f" {exam.id} ", style=self.t.muted) if exam.id and exam.id != heading else None
        )
        parts: list[RenderableType] = []
        if exam.description:
            facts = Table.grid(padding=(0, 2))
            facts.add_column(style=self.t.muted, no_wrap=True)
            facts.add_column(ratio=1)
            facts.add_row("Description", Text(exam.description))
            parts += [facts, _GAP]
        chips = self._exam_chips(exam)
        if chips.plain:
            parts.append(chips)
        if exam.instructions:
            parts += [
                _GAP,
                self._callout(
                    f"{self.g.info} Instructions",
                    self._md(exam.instructions),
                    border=self.t.border,
                    style="",
                ),
            ]
        return Panel(
            Group(*parts),
            title=title,
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
            box=self.t.banner_box,
            border_style=self.t.exam_accent or self.t.border,
            style=self.t.card_style,
            padding=(1, 2),
            width=self._card_width(),
        )

    def question_divider(self, index: int, question: models.ExamEntry) -> RenderableType:
        # Not a styled badge: the plain `Question N` is the contract (tests,
        # people searching their scrollback).
        accent = self.t.accents.get(getattr(question, "type", ""), self.t.exam_accent)
        label = Text(f" Question {index} ", style=f"bold {accent}" if accent else "bold")
        return Rule(label, style=self.t.muted, characters=self.t.rule_char)

    def placeholder(self, message: str) -> RenderableType:
        return Panel(
            Text(f"{self.g.include} {message}", style=f"italic {self.t.muted}".strip()),
            box=self.t.inner_box,
            border_style=self.t.border,
            style=self.t.card_style,
            width=self._card_width(),
        )

    def _card_width(self) -> int:
        return min(self.console.width, _MAX_CARD_WIDTH)

    #
    # Metadata chips
    #
    def _chip(self, value: str, *, glyph: str = "", label: str = "") -> Text:
        body = " ".join(part for part in (glyph, label, value) if part)
        return Text(f" {body} ", style=self.t.chip_style, no_wrap=False)

    def _chips(self, chips: list[Text]) -> Text:
        return Text(" ").join(chips)

    def _question_chips(self, question: models.Question) -> Text:
        g = self.g
        chips: list[Text] = []
        if question.weight != 1:
            chips.append(self._chip(_format_number(question.weight), label="weight"))
        inherited = self.exam
        if question.locale and not (inherited and question.locale == inherited.locale):
            chips.append(self._chip(question.locale, glyph=g.locale))
        if question.author and not (inherited and question.author == inherited.author):
            chips.append(self._chip(question.author, glyph=g.author))
        grading = getattr(question, "grading", "inherit")
        if grading != "inherit":
            chips.append(self._chip(str(grading), glyph=g.grading))
        if getattr(question, "shuffle", "inherit") is True:
            chips.append(self._chip("shuffle", glyph=g.shuffle))
        chips += [self._chip(f"#{tag}") for tag in question.tags or []]
        return self._chips(chips)

    def _exam_chips(self, exam: models.Exam) -> Text:
        g = self.g
        chips: list[Text] = []
        if exam.course:
            chips.append(self._chip(exam.course, glyph=g.course))
        if exam.author:
            chips.append(self._chip(exam.author, glyph=g.author))
        if exam.locale:
            chips.append(self._chip(exam.locale, glyph=g.locale))
        if exam.start is not None:
            chips.append(
                self._chip(_schedule.format_start(exam.start), glyph=g.start, label="start")
            )
        if exam.duration is not None:
            chips.append(
                self._chip(
                    _schedule.format_duration(exam.duration), glyph=g.duration, label="duration"
                )
            )
        chips.append(self._chip(exam.penalty, label="penalty"))
        chips.append(self._chip(str(len(exam.questions)), label="questions"))
        chips += [self._chip(f"#{tag}") for tag in exam.tags or []]
        return self._chips(chips)

    #
    # Small building blocks
    #
    def _md(self, text: str) -> Markdown:
        return Markdown(text, code_theme=self.t.code_theme)

    def _muted(self, text: str, *, italic: bool = True) -> Text:
        style = f"italic {self.t.muted}" if italic else self.t.muted
        return Text(text, style=style.strip())

    def _callout(
        self, title: str, content: RenderableType, *, border: str, style: str
    ) -> Panel:
        return Panel(
            content,
            title=Text(title, style=f"bold {border}".strip()),
            title_align="left",
            box=self.t.inner_box,
            border_style=border,
            style=style,
            padding=(0, 1),
            expand=False,
        )

    def _key_panel(self, content: RenderableType) -> Panel:
        return self._callout(
            f"{self.g.key} Answer key",
            content,
            border=self.t.correct,
            style=self.t.key_style,
        )

    def _hidden_key(self) -> Text:
        return self._muted(f"{self.g.lock} Answer key hidden.")

    def _feedback(self, label: str, markdown: str) -> RenderableType:
        header = self._muted(f"{self.g.feedback} {label}")
        return _LeftBar(Group(header, self._md(markdown)), self.g.bar, self.t.border)

    def _facts(self, rows: Iterable[tuple[str, str]]) -> Text:
        chips = [self._chip(value, label=label) for label, value in rows]
        return self._chips(chips)

    def _input_box(
        self, placeholder: str, *, unit: str | None = None, height: int | None = None
    ) -> RenderableType:
        field = Panel(
            self._muted(placeholder),
            box=self.t.inner_box,
            border_style=self.t.border,
            padding=(0, 1),
            width=_INPUT_WIDTH if height is None else None,
            height=height,
            expand=height is not None,
        )
        if unit is None:
            return field
        row = Table.grid(padding=(0, 1))
        row.add_column()
        row.add_column(vertical="middle")
        # `unit` is document content: `Text`, never markup.
        row.add_row(field, Text(unit, style="bold"))
        return row

    def _mark_blanks(self, text: str, question: models.Question) -> str:
        """Show each `[^id]` of a fill-in stem as an empty field."""
        if not isinstance(question, models.FillInQuestion):
            return text
        lines: list[str] = []
        in_fence = False
        for line in text.splitlines():
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
            elif not in_fence:
                # No-break spaces: CommonMark strips plain spaces at the ends
                # of a code span, and the padding is what makes it a chip.
                line = _BLANK_REF.sub(
                    lambda m: f"` {self.g.blank} {m.group(1)} `", line
                )
            lines.append(line)
        return "\n".join(lines)

    #
    # Body dispatch
    #
    def _body(self, question: models.Question) -> list[RenderableType]:
        if isinstance(question, models.MultipleChoiceQuestion):
            return [self._choices(question.choices, [self._radio(c.score) for c in question.choices])]
        if isinstance(question, models.MultipleSelectionQuestion):
            return [
                self._choices(question.choices, [self._checkbox(c.correct) for c in question.choices])
            ]
        if isinstance(question, models.TrueFalseQuestion):
            return [
                self._choices(question.choices, [self._true_false(c.correct) for c in question.choices])
            ]
        if isinstance(question, models.NumericQuestion):
            return self._numeric(
                answer=question.answer,
                unit=question.unit,
                domain=question.domain,
                decimal_places=question.decimal_places,
                tolerance=question.tolerance,
            )
        if isinstance(question, models.ShortAnswerQuestion):
            return self._short_answer(
                automation=question.automation,
                unmatched=question.unmatched,
                incorrect_feedback=question.incorrect_feedback,
                accept=question.accept,
                reject=question.reject,
            )
        if isinstance(question, models.EssayQuestion):
            return self._essay(question)
        if isinstance(question, models.OrderingQuestion):
            return self._ordering(question)
        if isinstance(question, models.FillInQuestion):
            return self._fill_in(question.blanks, unmatched=question.unmatched)
        raise AssertionError(f"unhandled question type: {question.type!r}")

    #
    # Choice-based bodies (multiple-choice, multiple-selection, true-false)
    #
    def _choices(
        self,
        choices: Iterable[models.ScoredChoice | models.BooleanChoice | models.Statement],
        marks: list[Text],
    ) -> RenderableType:
        grid = Table.grid(padding=(0, 1), expand=True)
        grid.add_column(width=_MARK_WIDTH, justify="left", no_wrap=True)
        grid.add_column(ratio=1)
        for choice, mark in zip(choices, marks):
            content: list[RenderableType] = [self._md(choice.text)]
            if self.show_key and choice.feedback:
                content.append(self._feedback("Feedback", choice.feedback))
            if self.show_key and choice.comment:
                content.append(self._feedback("Comment", choice.comment))
            grid.add_row(mark, Group(*content), style=self._row_style(choice))
        return grid

    def _row_style(
        self, choice: models.ScoredChoice | models.BooleanChoice | models.Statement
    ) -> str:
        if not self.show_key:
            return ""
        score = getattr(choice, "score", None)
        correct = getattr(choice, "correct", None)
        if correct is True or score == 1.0:
            return self.t.key_style
        return ""

    def _radio(self, score: float | None) -> Text:
        g, t = self.g, self.t
        if not self.show_key or score is None or score == 0.0:
            return Text(f" {g.radio_off}", style=t.muted)
        if score == 1.0:
            return Text(f" {g.radio_on}", style=f"bold {t.correct}")
        if score < 0:
            return Text(f" {g.radio_negative} {score:+.0%}", style=f"bold {t.wrong}")
        return Text(f" {g.radio_partial} {score:+.0%}", style=f"bold {t.partial}")

    def _checkbox(self, correct: bool) -> Text:
        g, t = self.g, self.t
        if self.show_key and correct:
            return Text(f" {g.check_on}", style=f"bold {t.correct}")
        return Text(f" {g.check_off}", style=t.muted)

    def _true_false(self, correct: bool) -> Text:
        g, t = self.g, self.t
        if not self.show_key:
            return Text(f" {g.radio_off}T {g.radio_off}F", style=t.muted)
        on, off = (f"{g.radio_on}", f"{g.radio_off}")
        right = f"bold {t.correct}"
        return Text.assemble(
            " ",
            (f"{on if correct else off}T", right if correct else t.muted),
            " ",
            (f"{off if correct else on}F", t.muted if correct else right),
        )

    #
    # Numeric bodies (numeric question, numeric blank)
    #
    def _numeric(
        self,
        *,
        answer: int | float | str,
        unit: str | None,
        domain: NumericDomain | None,
        decimal_places: int | None,
        tolerance: models.Tolerance | None,
    ) -> list[RenderableType]:
        rows: list[tuple[str, str]] = []
        if domain:
            rows.append(("domain", domain))
        if decimal_places is not None:
            rows.append(("decimal places", str(decimal_places)))
        parts: list[RenderableType] = []
        if rows:
            parts += [self._facts(rows), _GAP]
        parts.append(self._input_box("Your answer", unit=unit))
        parts.append(_GAP)
        if not self.show_key:
            parts.append(self._hidden_key())
            return parts
        # `text` embeds `unit`, which is document content: `Text`, never
        # a bare `str`, which Rich would markup-parse.
        text = Text(_format_numeric_answer(answer, unit, tolerance), style="bold")
        parts.append(self._key_panel(text))
        return parts

    #
    # Short-answer bodies (short-answer question, short-answer blank)
    #
    def _short_answer(
        self,
        *,
        automation: str,
        unmatched: str | None = None,
        incorrect_feedback: str | None = None,
        accept: list[models.AnswerPattern] | None = None,
        reject: list[models.AnswerPattern] | None = None,
    ) -> list[RenderableType]:
        rows: list[tuple[str, str]] = [("automation", automation)]
        if unmatched is not None:
            rows.append(("unmatched", unmatched))
        if incorrect_feedback is not None:
            rows.append(("incorrect feedback", incorrect_feedback))
        parts: list[RenderableType] = [
            self._facts(rows),
            _GAP,
            self._input_box("Your answer"),
            _GAP,
        ]

        if automation == "manual":
            parts.append(self._muted("No machine-checkable answer key -- grade this by hand."))
            return parts

        if not self.show_key:
            parts.append(self._hidden_key())
            return parts

        if accept is not None or reject is not None:
            sections = [_pattern_lines("Accepted", accept), _pattern_lines("Rejected", reject)]
            body = "\n\n".join("\n".join(s) for s in sections if s)
        else:
            body = "(no accepted answer declared)"
        parts.append(self._key_panel(self._md(body)))
        return parts

    #
    # Essay body
    #
    def _essay(self, question: models.EssayQuestion) -> list[RenderableType]:
        rows: list[tuple[str, str]] = []
        if question.input != "text":
            rows.append(("input", question.input))
        if question.highlight:
            rows.append(("highlight", question.highlight))
        parts: list[RenderableType] = []
        if rows:
            parts += [self._facts(rows), _GAP]
        parts.append(self._input_box(f"{self.g.edit} Write your answer here...", height=7))
        parts += [_GAP, self._muted("Manually graded (essay).")]
        if question.answer_key:
            parts.append(_GAP)
            parts.append(
                self._key_panel(self._md(question.answer_key)) if self.show_key else self._hidden_key()
            )
        return parts

    #
    # Ordering body
    #
    def _ordering(self, question: models.OrderingQuestion) -> list[RenderableType]:
        rows: list[tuple[str, str]] = [("content", question.content)]
        if question.highlight:
            rows.append(("highlight", question.highlight))
        if question.indentation != "fixed":
            rows.append(("indentation", question.indentation))
        unmatched: Unmatched = question.unmatched
        if unmatched != "manual":
            rows.append(("unmatched", unmatched))
        if question.normalizations:
            rows.append(("normalizations", ", ".join(question.normalizations)))
        parts: list[RenderableType] = [self._facts(rows), _GAP]

        if not self.show_key:
            # A real presentation layer shuffles randomly; this output is
            # tested, so it sorts instead -- deterministic, and it does not
            # reveal the answer key's order.
            shuffled = sorted(
                [*question.lines, *question.extra], key=lambda line: (line[1], line[0])
            )
            parts.append(
                self._ordering_panel(
                    "Drag the lines into order",
                    shuffled,
                    question,
                    border=self.t.border,
                    marker=self.g.handle,
                )
            )
            return parts

        parts.append(
            self._ordering_panel(
                f"{self.g.ok} Correct order", question.lines, question, border=self.t.correct
            )
        )
        if question.extra:
            parts.append(_GAP)
            parts.append(self._muted("Extra (distractor) lines:"))
            parts.append(
                self._ordering_panel(
                    "", question.extra, question, border=self.t.border, marker=self.g.bullet
                )
            )
        for label, glyph, alternatives in (
            ("Accepted", self.g.ok, question.accept),
            ("Rejected", self.g.no, question.reject),
        ):
            for alt in alternatives:
                parts.append(_GAP)
                parts.append(
                    self._ordering_panel(
                        f"{glyph} {label} alternative",
                        alt.lines,
                        question,
                        border=self.t.correct if label == "Accepted" else self.t.wrong,
                    )
                )
                if alt.feedback:
                    parts.append(self._feedback("Feedback", alt.feedback))
        return parts

    def _ordering_panel(
        self,
        title: str,
        lines: Iterable[models.OrderingLine],
        question: models.OrderingQuestion,
        *,
        border: str,
        marker: str | None = None,
    ) -> Panel:
        """
        A block of ordering lines.

        Text lines are rows of a list: `marker` in front of each one, or
        its position when `marker` is `None`. Code is a fenced block as
        `render` would write it, since a line of code has no position.
        """
        body: RenderableType
        if question.content == "text":
            grid = Table.grid(padding=(0, 1))
            grid.add_column(justify="right", no_wrap=True, min_width=3, style=self.t.muted)
            grid.add_column(ratio=1)
            for position, (level, text) in enumerate(lines, start=1):
                grid.add_row(
                    marker if marker is not None else f"{position}.",
                    Padding(self._md(text), (0, 0, 0, level * 2)),
                )
            body = grid
        else:
            source = "\n".join(
                _render.yield_ordering_content(lines, question.content, question.highlight)
            )
            body = self._md(source)
        return Panel(
            body,
            title=Text(title, style=f"bold {border}".strip()) if title else None,
            title_align="left",
            box=self.t.inner_box,
            border_style=border,
            padding=(0, 1),
            expand=False,
        )

    #
    # Fill-in body
    #
    def _fill_in(
        self, blanks: Iterable[models.Blank], *, unmatched: Unmatched | None
    ) -> list[RenderableType]:
        parts: list[RenderableType] = []
        for index, blank in enumerate(blanks):
            if index:
                parts.append(_GAP)
            # `blank.id` is document content: `Text`, never markup.
            parts.append(
                Rule(
                    Text(f" {self.g.blank} Blank [^{blank.id}] ", style=f"bold {self.t.muted}".strip()),
                    style=self.t.muted,
                    characters=self.t.rule_char,
                    align="left",
                )
            )
            if isinstance(blank, models.ChoiceBlank):
                marks = [self._radio(c.score) for c in blank.choices]
                parts.append(self._choices(blank.choices, marks))
            elif isinstance(blank, models.ShortAnswerBlank):
                parts += self._short_answer(
                    automation=blank.automation(unmatched),
                    accept=blank.accept,
                    reject=blank.reject,
                )
            elif isinstance(blank, models.NumericBlank):
                parts += self._numeric(
                    answer=blank.answer,
                    unit=blank.unit,
                    domain=blank.domain,
                    decimal_places=blank.decimal_places,
                    tolerance=blank.tolerance,
                )
            else:
                raise AssertionError(f"unhandled blank type: {blank.type!r}")
        return parts


#: A blank line between the sections of a card.
_GAP = Text("")


def _type_label(question_type: str) -> str:
    return question_type.replace("-", " ").upper()


def _format_numeric_answer(
    answer: int | float | str, unit: str | None, tolerance: models.Tolerance | None
) -> str:
    answer_text = _format_number(answer) if isinstance(answer, float) else str(answer)
    parts = [answer_text]
    if unit:
        parts.append(unit)
    text = " ".join(parts)

    tolerance_parts = []
    if tolerance is not None:
        if tolerance.absolute is not None:
            tolerance_parts.append(f"+/- {_format_number(tolerance.absolute)}")
        if tolerance.relative is not None:
            tolerance_parts.append(f"+/- {tolerance.relative:.0%}")
    if tolerance_parts:
        text += f" ({', '.join(tolerance_parts)})"
    return text


def _pattern_lines(label: str, patterns: list[models.AnswerPattern] | None) -> list[str]:
    """Render one accept/reject list as markdown lines, empty when absent."""
    if not patterns:
        return []
    lines = [f"**{label}:**"]
    for rule in patterns:
        suffix = f" -- {rule.feedback}" if rule.feedback else ""
        lines.append(f"- `{rule.pattern}`{suffix}")
    return lines


def _format_number(value: float) -> str:
    return f"{value:g}"


#
# CLI command
#
@app.command()
def show(
    file: Path = typer.Argument(
        ...,
        help="Path to a question or exam document (.mdq.md, .md or .mdq), or - for stdin.",
    ),
    no_answer_key: bool = typer.Option(
        False,
        "--no-answer-key",
        help=(
            "Hide anything that reveals the correct answer (correctness "
            "marks, an essay's answer key, a numeric answer, ...), as if "
            "previewing the question for a student."
        ),
    ),
    width: int | None = typer.Option(
        None,
        "--width",
        help="Console width to render at (default: the terminal's own width).",
    ),
    theme: ThemeName = typer.Option(
        ThemeName.auto,
        "--theme",
        help=(
            "Colors and symbols: dark, light, plain (ASCII, no colors), or "
            "auto (light if COLORFGBG says so, dark otherwise)."
        ),
    ),
) -> None:
    """
    Show the parsed representation of a question or exam document.

    Draws each question as a card: rich-text fields (preamble, stem,
    epilogue, choice text, feedback, ...) as Markdown, choices as radio
    buttons and checkboxes, typed answers as empty fields, and the rest
    as metadata chips, so the document's shape is easy to check at a glance.
    """

    # Color only on a terminal, so a pipe or a file gets no escape codes.
    # An explicit `--theme` is a request for the styled output: keep it.
    console = Console(
        file=sys.stdout,
        width=width,
        highlight=False,
        force_terminal=True if theme is not ThemeName.auto else None,
    )
    error_console = Console(
        file=sys.stderr,
        highlight=False,
        force_terminal=True,
    )

    # Everything below that can embed a path or an exception message is
    # printed as a `Text` object, never spliced into a markup `str` --
    # `file` and `exc` can both carry document/filesystem content with
    # square brackets, which Rich would otherwise parse as markup (and,
    # for a stray closing tag like `[/]`, raise instead of print).
    #
    # A `Path` source resolves an exam's include blocks against its own
    # directory (see `show_source` above); stdin has no directory to
    # resolve against, so it is read as plain text instead.
    source = sys.stdin.read() if str(file) == "-" else file

    try:
        show_source(source, console, show_answer_key=not no_answer_key, theme=theme)
    except OSError as exc:
        error_console.print("[b red]error:[/]", Text(f"could not read {file}: {exc}"))
        raise typer.Exit(code=2)
    except (ValueError, InvalidDocument) as exc:
        error_console.print("[b red]error:[/]", Text(str(exc)))
        raise typer.Exit(code=1)
