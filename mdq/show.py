"""
Human-readable console presentation of a parsed MDQ document.

`models.BaseQuestion.render()` is the round-trip serializer: it turns a
model back into MDQ Markdown, byte for byte close enough to parse back
into the same model. This module is a different concern entirely -- a
*view* for a human at a terminal, not a serializer. Scalar metadata (id,
type, title, author, locale, tags, weight, grading strategy, tolerances,
domain, ...) is laid out as small tables and panels; rich-text fields
(preamble, stem, epilogue, choice text, feedback, comment, an essay's
answer key) go through `rich.markdown.Markdown` since they are Markdown
themselves. The answer key -- whichever shape it takes for a given
question type -- is always set apart from the plain choices/blanks by
color and, where it stands alone, its own bordered panel.

The interface is small on purpose: `show_source` for a whole document (a
question or an exam -- told apart by content, via `mdq.load`/`mdq.parse`),
plus `render_question` and `render_exam` for callers that already hold a
model.
"""

from __future__ import annotations

from typing import Iterable

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import models, render, schedule
from .loaders import QuestionLoader
from .loading import Source, parse

__all__ = ["show_source", "render_question", "render_exam"]

_ANSWER_KEY_STYLE = "green"
_NOTE_STYLE = "dim italic"
_HIDDEN_ANSWER_TEXT = Text("Answer key hidden.", style=_NOTE_STYLE)


def show_source(
    src: Source,
    console: Console,
    *,
    show_answer_key: bool = True,
    loader: QuestionLoader | None = None,
) -> None:
    """
    Load an MDQ document and print a human-readable rendering of it.

    Dispatches on the document's own kind: an exam is rendered by
    `render_exam`, a single question by `render_question`.

    Args:
        src: Anything `mdq.parse` accepts -- MDQ source text, a `Path`,
            or an open file. A `Path` resolves an exam's `include:`
            references against its own directory unless `loader`
            overrides it; text has no directory to resolve against.
        console: Where to print the rendering.
        show_answer_key: When false, everything that would reveal the
            correct answer (correctness marks, an essay's answer key, a
            short answer's accepted values, a numeric answer, ...) is
            replaced by a note that it is hidden. Choices, statements
            and blanks themselves are still shown -- only the key is
            hidden, as when previewing a question for a student.
        loader: Resolves an exam's `include:` references, if given.
            Ignored for a question document.

    Raises:
        InvalidDocument: `src` is not a valid MDQ document.
    """
    document = parse(src, loader=loader, ids="fill")
    if isinstance(document, models.Exam):
        render_exam(document, console, show_answer_key=show_answer_key)
    else:
        render_question(document, console, show_answer_key=show_answer_key)


def render_question(
    question: models.Question,
    console: Console,
    *,
    show_answer_key: bool = True,
) -> None:
    """Print a human-readable rendering of a single question."""
    _render_header(console, question.title or question.id or question.type)
    _render_metadata(console, _question_metadata(question))
    console.print()
    _render_markdown(console, question.preamble)
    _render_markdown(console, question.stem)
    console.print()
    _render_body(console, question, show_answer_key=show_answer_key)
    if question.epilogue:
        console.print()
        _render_markdown(console, question.epilogue)
    if show_answer_key and question.comment:
        console.print()
        console.print(
            Panel(
                Markdown(question.comment),
                title="Instructor note",
                border_style="yellow",
                expand=False,
            )
        )


def render_exam(
    exam: models.Exam,
    console: Console,
    *,
    show_answer_key: bool = True,
) -> None:
    """Print a human-readable rendering of an exam and every question in it."""
    _render_header(console, exam.title or exam.id or "Exam", style="bold blue")
    _render_metadata(console, _exam_metadata(exam))
    if exam.instructions:
        console.print()
        _render_markdown(console, exam.instructions)

    for index, question in enumerate(exam.questions, start=1):
        console.print()
        console.rule(f"Question {index}", style="dim")
        render_question(question, console, show_answer_key=show_answer_key)


#
# Metadata
#
def _question_metadata(question: models.Question) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [("Type", question.type)]
    rows.append(
        ("ID", question.id) if question.id else ("ID", "(none -- not addressable)")
    )
    if question.title:
        rows.append(("Title", question.title))
    if question.author:
        rows.append(("Author", question.author))
    if question.locale:
        rows.append(("Locale", question.locale))
    if question.tags:
        rows.append(("Tags", ", ".join(question.tags)))
    rows.append(("Weight", _format_number(question.weight)))
    grading = getattr(question, "grading", None)
    if grading is not None:
        rows.append(("Grading strategy", grading))
    if getattr(question, "shuffle", None):
        rows.append(("Shuffle", "yes"))
    return rows


def _exam_metadata(exam: models.Exam) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if exam.id:
        rows.append(("ID", exam.id))
    if exam.description:
        rows.append(("Description", exam.description))
    if exam.course:
        rows.append(("Course", exam.course))
    if exam.author:
        rows.append(("Author", exam.author))
    if exam.locale:
        rows.append(("Locale", exam.locale))
    if exam.tags:
        rows.append(("Tags", ", ".join(exam.tags)))
    if exam.start is not None:
        rows.append(("Start", schedule.format_start(exam.start)))
    if exam.duration is not None:
        rows.append(("Duration", schedule.format_duration(exam.duration)))
    rows.append(("Penalty policy", exam.penalty))
    rows.append(("Questions", str(len(exam.questions))))
    return rows


#
# Body dispatch
#
def _render_body(
    console: Console, question: models.Question, *, show_answer_key: bool
) -> None:
    if isinstance(question, models.MultipleChoiceQuestion):
        marks = [_score_mark(c.score, show_answer_key) for c in question.choices]
        _render_choices(console, question.choices, marks, show_answer_key)
    elif isinstance(question, models.MultipleSelectionQuestion):
        marks = [_bool_mark(c.correct, show_answer_key) for c in question.choices]
        _render_choices(console, question.choices, marks, show_answer_key)
    elif isinstance(question, models.TrueFalseQuestion):
        marks = [_bool_mark(c.correct, show_answer_key) for c in question.choices]
        _render_choices(console, question.choices, marks, show_answer_key)
    elif isinstance(question, models.NumericQuestion):
        _render_numeric(
            console,
            answer=question.answer,
            unit=question.unit,
            domain=question.domain,
            decimal_places=question.decimal_places,
            tolerance=question.tolerance,
            show_answer_key=show_answer_key,
        )
    elif isinstance(question, models.ShortAnswerQuestion):
        _render_short_answer(
            console,
            one_of=question.one_of,
            regex=question.regex,
            open_ended=question.open_ended,
            accept=question.accept,
            reject=question.reject,
            show_answer_key=show_answer_key,
        )
    elif isinstance(question, models.EssayQuestion):
        _render_essay(console, question, show_answer_key=show_answer_key)
    elif isinstance(question, models.OrderingQuestion):
        _render_ordering(console, question, show_answer_key=show_answer_key)
    elif isinstance(question, models.FillInQuestion):
        _render_fill_in(console, question.blanks, show_answer_key=show_answer_key)
    else:
        raise AssertionError(f"unhandled question type: {question.type!r}")


#
# Choice-based bodies (multiple-choice, multiple-selection, true-false)
#
def _render_choices(
    console: Console,
    choices: Iterable[models.ScoredChoice | models.BooleanChoice | models.Statement],
    marks: list[Text],
    show_answer_key: bool,
) -> None:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=5, justify="center", no_wrap=True)
    grid.add_column(ratio=1)
    for choice, mark in zip(choices, marks):
        content: list[RenderableType] = [Markdown(choice.text)]
        if show_answer_key and choice.feedback:
            content.append(Text("Feedback:", style="italic dim"))
            content.append(Markdown(choice.feedback))
        if show_answer_key and choice.comment:
            content.append(Text("Comment:", style="italic dim"))
            content.append(Markdown(choice.comment))
        grid.add_row(mark, Group(*content))
    console.print(grid)


def _score_mark(score: float | None, show_answer_key: bool) -> Text:
    if not show_answer_key:
        return Text("*", style="dim")
    if score is None or score == 0.0:
        return Text("o", style="dim")
    if score == 1.0:
        return Text("v", style="bold green")
    if score < 0:
        return Text(f"{score:+.0%}", style="bold red")
    return Text(f"{score:+.0%}", style="bold yellow")


def _bool_mark(correct: bool, show_answer_key: bool) -> Text:
    if not show_answer_key:
        return Text("*", style="dim")
    return Text("v", style="bold green") if correct else Text("x", style="dim red")


#
# Numeric bodies (numeric question, numeric blank)
#
def _render_numeric(
    console: Console,
    *,
    answer: float | str,
    unit: str | None,
    domain: models.NumericDomain | None,
    decimal_places: int | None,
    tolerance: models.Tolerance | None,
    show_answer_key: bool,
) -> None:
    rows: list[tuple[str, str]] = []
    if domain:
        rows.append(("Domain", domain))
    if unit:
        rows.append(("Unit", unit))
    if decimal_places is not None:
        rows.append(("Decimal places", str(decimal_places)))
    if rows:
        _render_metadata(console, rows)

    if not show_answer_key:
        console.print(_HIDDEN_ANSWER_TEXT)
        return

    text = _format_numeric_answer(answer, unit, tolerance)
    # `text` embeds `unit`, which is document content -- wrap it in `Text`
    # rather than handing `Panel()` a bare `str`, which Rich would
    # markup-parse.
    console.print(
        Panel(
            Text(text), title="Answer key", border_style=_ANSWER_KEY_STYLE, expand=False
        )
    )


def _format_numeric_answer(
    answer: float | str, unit: str | None, tolerance: models.Tolerance | None
) -> str:
    answer_text = _format_number(answer) if isinstance(answer, float) else answer
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


#
# Short-answer bodies (short-answer question, short-answer blank)
#
def _pattern_lines(label: str, patterns: list[models.AnswerPattern] | None) -> list[str]:
    """Render one accept/reject list as markdown lines, empty when absent."""
    if not patterns:
        return []
    lines = [f"**{label}:**"]
    for rule in patterns:
        suffix = f" -- {rule.feedback}" if rule.feedback else ""
        lines.append(f"- `{rule.pattern}`{suffix}")
    return lines


def _render_short_answer(
    console: Console,
    *,
    one_of: list[str] | None,
    regex: str | None,
    open_ended: bool,
    show_answer_key: bool,
    accept: list[models.AnswerPattern] | None = None,
    reject: list[models.AnswerPattern] | None = None,
) -> None:
    rows: list[tuple[str, str]] = []
    if open_ended:
        rows.append(("Grading", "manual (open-ended)"))
    if rows:
        _render_metadata(console, rows)

    if open_ended:
        console.print(
            Text(
                "No machine-checkable answer key -- grade this by hand.",
                style=_NOTE_STYLE,
            )
        )
        return

    if not show_answer_key:
        console.print(_HIDDEN_ANSWER_TEXT)
        return

    if accept is not None or reject is not None:
        sections = [_pattern_lines("Accepted", accept), _pattern_lines("Rejected", reject)]
        body = "\n\n".join("\n".join(s) for s in sections if s)
    elif regex is not None:
        body = f"Matches pattern: `/{regex}/`"
    elif one_of:
        body = "\n".join(f"- {answer}" for answer in one_of)
    else:
        body = "(no accepted answer declared)"
    console.print(
        Panel(
            Markdown(body),
            title="Answer key",
            border_style=_ANSWER_KEY_STYLE,
            expand=False,
        )
    )


#
# Essay body
#
def _render_essay(
    console: Console, question: models.EssayQuestion, *, show_answer_key: bool
) -> None:
    rows: list[tuple[str, str]] = []
    if question.input != "text":
        rows.append(("Input", question.input))
    if question.highlight:
        rows.append(("Highlight", question.highlight))
    if rows:
        _render_metadata(console, rows)

    console.print(Text("Manually graded (essay).", style=_NOTE_STYLE))
    if not show_answer_key:
        if question.answer_key:
            console.print(_HIDDEN_ANSWER_TEXT)
        return
    if question.answer_key:
        console.print(
            Panel(
                Markdown(question.answer_key),
                title="Answer key",
                border_style=_ANSWER_KEY_STYLE,
                expand=False,
            )
        )


#
# Ordering body
#
def _render_ordering(
    console: Console, question: models.OrderingQuestion, *, show_answer_key: bool
) -> None:
    rows: list[tuple[str, str]] = [("Content", question.content)]
    if question.highlight:
        rows.append(("Highlight", question.highlight))
    if question.indentation != "fixed":
        rows.append(("Indentation", question.indentation))
    if question.unmatched != "manual":
        rows.append(("Unmatched", question.unmatched))
    if question.normalizations:
        rows.append(("Normalizations", ", ".join(question.normalizations)))
    _render_metadata(console, rows)

    if not show_answer_key:
        # A real presentation layer shuffles randomly; this output is
        # tested, so it sorts instead -- deterministic, and it does not
        # reveal the answer key's order.
        shuffled = sorted(
            [*question.lines, *question.extra], key=lambda line: (line[1], line[0])
        )
        _render_ordering_lines(console, shuffled, question.content, question.highlight)
        return

    _render_ordering_lines(console, question.lines, question.content, question.highlight)
    if question.extra:
        console.print()
        console.print(Text("Extra (distractor) lines:", style="italic dim"))
        _render_ordering_lines(console, question.extra, question.content, question.highlight)
    for label, alternatives in (("Accepted", question.accept), ("Rejected", question.reject)):
        for alt in alternatives:
            console.print()
            console.print(Text(f"{label} alternative:", style="italic dim"))
            _render_ordering_lines(console, alt.lines, question.content, question.highlight)
            if alt.feedback:
                console.print(Text("Feedback:", style="italic dim"))
                console.print(Markdown(alt.feedback))


def _render_ordering_lines(
    console: Console,
    lines: Iterable[models.OrderingLine],
    content: str,
    highlight: str | None,
) -> None:
    """Print a block of ordering lines the way `render` would write them."""
    source = "\n".join(render.yield_ordering_content(lines, content, highlight))
    console.print(Markdown(source))


#
# Fill-in body
#
def _render_fill_in(
    console: Console, blanks: Iterable[models.Blank], *, show_answer_key: bool
) -> None:
    for blank in blanks:
        console.print()
        # `blank.id` is document content; wrap the whole label in `Text`
        # (never markup-parsed) rather than handing `console.rule()` a
        # bare `str` -- see `_render_header`.
        console.rule(Text(f"Blank [^{blank.id}]"), style="dim")
        if isinstance(blank, models.ChoiceBlank):
            marks = [_score_mark(c.score, show_answer_key) for c in blank.choices]
            _render_choices(console, blank.choices, marks, show_answer_key)
        elif isinstance(blank, models.ShortAnswerBlank):
            _render_short_answer(
                console,
                one_of=blank.one_of,
                regex=blank.regex,
                open_ended=False,
                show_answer_key=show_answer_key,
            )
        elif isinstance(blank, models.NumericBlank):
            _render_numeric(
                console,
                answer=blank.answer,
                unit=blank.unit,
                domain=blank.domain,
                decimal_places=blank.decimal_places,
                tolerance=blank.tolerance,
                show_answer_key=show_answer_key,
            )
        else:
            raise AssertionError(f"unhandled blank type: {blank.type!r}")


#
# Small rendering primitives
#
def _render_header(console: Console, label: str, style: str = "bold") -> None:
    # `label` is document content (a title, id, or question type) and must
    # never be markup-parsed -- see the module note on Text vs markup.
    # `Text(...)` never parses markup, unlike a plain `str` handed to
    # `console.rule()`, so the style is carried via `style=` instead of
    # being spliced into the string as `[style]...[/style]`.
    console.rule(Text(label, style=style), style=style)


def _render_metadata(console: Console, rows: Iterable[tuple[str, str]]) -> None:
    table = Table.grid(padding=(0, 1, 0, 0))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    for label, value in rows:
        # `label` is always one of our own static strings (never document
        # content); `value` can be, so it goes through `Text` rather than
        # a bare `str` to avoid Rich parsing it as markup.
        table.add_row(f"{label}:", Text(value))
    console.print(table)


def _render_markdown(console: Console, text: str | None) -> None:
    if text:
        console.print(Markdown(text))


def _format_number(value: float) -> str:
    return f"{value:g}"
