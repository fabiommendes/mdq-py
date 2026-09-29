"""
Exam-level parsing: splitting an exam document below its H1 title into
question blocks (`_split_exam_blocks`), turning each block into an
inline question, `include` or `include-all` entry (`_parse_exam_block`),
and applying exam-to-question inheritance (`_inherit_from_exam`).

`parse_exam` is the public entry point; it never resolves `include`s
itself (see `mdq.models.Exam.resolve`) and calls back into
`mdq._parser._question.parse_question` for each inline question block.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, cast

import yaml

from .. import _schedule
from .._markdown import md, split_lines
from .._diagnostics import Diagnostic
from ..errors import MissingField, ParseError
from ..types import ExamDict, ExamEntryDict, IncludeAllDict, IncludeDict, QuestionDict
from ._choices import SLUG_PREFIX_RE
from ._frontmatter import _load_frontmatter_yaml, _normalize_tags, _split_frontmatter
from ._frontmatter import _unknown_frontmatter_warnings
from ._question import BRACKET_ITEM_RE, _matches_tag, parse_question

__all__ = ["parse_exam", "is_exam", "INHERITED_FIELDS", "SEPARATOR"]

#: An exam's questions are separated by a line of exactly three equals
#: signs. It must be preceded by a blank line -- without one, CommonMark
#: reads it as a setext underline and turns the paragraph above into an
#: H1, which is the exam-title syntax.
SEPARATOR = "==="

#: `# Title` or `# [slug] Title`.
H1_RE = re.compile(r"^#[ \t]+(?P<rest>.*?)[ \t]*$")

#: Fields a question inherits from the exam when it declares none itself.
#: `tags` is deliberately absent -- tags classify a question individually.
INHERITED_FIELDS = ("locale", "author")

#: Simple frontmatter fields copied verbatim into the exam document by
#: `parse_exam`; the frontmatter wins over the H1 for `id`/`title`.
#: `tags`, `start` and `duration` need their own normalization/parsing and
#: are handled separately there.
EXAM_PASSTHROUGH_KEYS = (
    "id",
    "title",
    "uuid",
    "course",
    "description",
    "author",
    "locale",
    "meta",
    "penalty",
    "grading",
)

#: Every frontmatter key an exam accepts. `type` has no effect of its own
#: -- an exam is recognized by its H1 title, not by declaring `type:
#: exam` (docs/exam.md) -- but is accepted, not flagged as a mistake.
EXAM_FRONTMATTER_KEYS = frozenset(EXAM_PASSTHROUGH_KEYS) | {"tags", "start", "duration", "type"}

#: A block with no `include:`/`include-all:` is an inline question
#: instead, and its frontmatter is checked against `COMMON_QUESTION_KEYS`/
#: `TYPE_QUESTION_KEYS` like any other question's, by `parse_question`. An
#: include/include-all block's own frontmatter is passed through
#: verbatim instead (see `_parse_exam_block`): an extra field there is a
#: model error (`unknown-include-field`), not a dropped-and-warned key.


def parse_exam(
    text: str,
    *,
    warnings: list[Diagnostic] | None = None,
) -> ExamDict:
    """
    Parse an exam document.

    `include:` and `include-all:` blocks are left as they are written, as
    `{"include": id}` and `{"include-all": query}` entries. See
    `mdq.models.Exam.resolve`.

    Args:
        text: MDQ source text for an exam (i.e. one with an H1 title).
        warnings: When given, an `unknown-frontmatter-key` `Diagnostic`
            is appended for every frontmatter key the parser does not
            consume -- at the exam's own top level (`path=(key,)`) and
            inside each question block (`path=("questions", i, key)`,
            0-based). Parsing never fails because of them.

    Returns:
        The parsed exam document, in the shape validated by
        `mdq.validator.validate_document`.

    Raises:
        MissingField: If the exam has no title.
        ParseError: If a question block is not valid MDQ.
        IncompleteQuestion: If a question's type cannot be inferred.

    Example:
        >>> exam = parse_exam(
        ...     "# Sample Exam\\n\\n===\\n\\nWhat is 2 + 2?\\n\\n"
        ...     "* [x] 4\\n* [ ] 5\\n"
        ... )
        >>> exam["title"]
        'Sample Exam'
        >>> len(exam["questions"])
        1
    """

    # FIXME: move this logic to the MDQParser and reuse their methods
    frontmatter_text, body = _split_frontmatter(text)
    front: dict[str, Any] = {}
    if frontmatter_text is not None:
        front = _load_frontmatter_yaml(frontmatter_text)

    if warnings is not None:
        warnings.extend(_unknown_frontmatter_warnings(front, EXAM_FRONTMATTER_KEYS))

    doc: dict[str, Any] = {"type": "exam"}

    lines = split_lines(body)
    heading: str | None = None
    title_index = 0
    code_lines = _code_line_indices(lines)
    for title_index, line in enumerate(lines):
        if title_index in code_lines:
            continue
        if m := H1_RE.match(line):
            heading = m.group("rest")
            break
    if heading is None:
        raise MissingField("title")

    slug_match = SLUG_PREFIX_RE.match(heading)
    if slug_match:
        doc["id"] = slug_match.group("slug")
        heading = heading[slug_match.end() :].strip(" \t")
    if heading:
        doc["title"] = heading

    # The frontmatter wins over the H1 for both fields it can also carry.
    for key in EXAM_PASSTHROUGH_KEYS:
        if key in front:
            doc[key] = str(front[key]) if key == "id" else front[key]
    if "tags" in front:
        doc["tags"] = _normalize_tags(front["tags"])
    if "start" in front:
        try:
            doc["start"] = _schedule.format_start(_schedule.parse_start(front["start"]))
        except ValueError as exc:
            raise ParseError(f"exam start: {exc}") from exc
    if "duration" in front:
        try:
            doc["duration"] = _schedule.format_duration(
                _schedule.parse_duration(front["duration"])
            )
        except ValueError as exc:
            raise ParseError(f"exam duration: {exc}") from exc

    instructions, blocks = _split_exam_blocks(lines[title_index + 1 :])
    if instructions:
        doc["instructions"] = instructions

    questions: list[ExamEntryDict] = []
    for index, block in enumerate(blocks):
        questions.append(
            _parse_exam_block(block, doc, warnings=warnings, index=index)
        )
    doc["questions"] = questions

    return cast(ExamDict, doc)


def is_exam(text: str) -> bool:
    """
    Report whether `text` is an exam rather than a single question.

    An exam is recognized by its H1 title, which a question document can
    never carry: generic.md lists H1 headings among the block elements a
    question's preamble rejects.

    Args:
        text: MDQ source text, with or without YAML frontmatter.

    Returns:
        True if `text` has a top-level (H1) heading, False otherwise.

    Example:
        >>> is_exam("# Sample Exam\\n\\nWhat is 2 + 2?")
        True
        >>> is_exam("What is 2 + 2?\\n\\n* [x] 4\\n* [ ] 5")
        False
    """

    _, body = _split_frontmatter(text)
    lines = split_lines(body)
    code_lines = _code_line_indices(lines)
    return any(i not in code_lines and H1_RE.match(line) for i, line in enumerate(lines))


def _code_line_indices(lines: list[str]) -> set[int]:
    """
    Indices of the lines inside a fenced or indented code block.

    Code lines never count as MDQ structure (title, separator, fence, body
    tag). Parses the joined lines with the parser's own markdown-it
    config, so indices match `lines`.
    """
    covered: set[int] = set()
    for token in md.parse("\n".join(lines)):
        if token.type in ("fence", "code_block") and token.map:
            covered.update(range(token.map[0], token.map[1]))
    return covered


def _split_exam_blocks(lines: list[str]) -> tuple[str | None, list[list[str]]]:
    """
    Split the text below the title into (instructions, question blocks).

    A block starts at a `===` separator -- always, unconditionally -- or
    at a bare `---` frontmatter fence. Telling a fence-that-opens-a-new-
    question apart from a thematic break sitting in some other question's
    own preamble/epilogue prose (which generic.md allows outright) can't
    be done by content alone: an entirely ordinary prose line like "Nota:
    leia com atenção." parses as a YAML mapping just as readily as real
    frontmatter fields do, so a bare `---` only opens a *new* question
    when position says it structurally could:

    * it is the very first one found at all -- there is nothing yet to
      confuse it with, and exam.md's Body rule already forbids ordinary
      instructions prose from using a `---`-fenced block, so whatever
      fence is found first, however much instructions prose precedes it,
      is trustworthy; or
    * nothing but blank lines separates it from the line right after a
      *previous bare fence's own closing* `---` (exam.md's worked example
      chains two bare-frontmatter questions exactly this way, back to
      back, with no `===` between them); or
    * the current question (opened by `===` or a previous fence) has
      already shown a recognizable body -- a body tag (`[essay]`,
      `[short-answer]: ...`, `[numeric]: ...`, a `[^blank]:` line) or the
      first item of a bracket-choice list -- since its own frontmatter
      closed. Once that has happened the question is structurally
      complete (only optional epilogue prose can still follow), so a
      further bare fence safely opens the next question even with
      arbitrary epilogue text in between, no `===` required -- this is
      exactly what lets a duplicate-id check span two bare-frontmatter
      essay questions with real bodies, not just empty `include`s.

    A fence immediately after a `===`, with nothing but blank lines
    before it, is none of those: it is simply that question's own
    frontmatter (any question may have one, `===`-opened or not), not a
    second, separate start -- so it is consumed like normal content, not
    recorded as a new block, though a further fence chaining off *its*
    close is fair game again.

    Before any body tag has appeared for the current question, a bare
    `---` is necessarily still inside its own preamble/stem, and no
    signal available from raw lines can tell a thematic break there from
    a genuine fence -- so it is never treated as one.
    """

    starts: list[int] = []
    code_lines = _code_line_indices(lines)
    index = 0
    #: Position right after the most recently accepted block boundary.
    boundary = 0
    #: Whether that boundary was a `===` (as opposed to a previous bare
    #: fence's own closing `---`, or the still-unresolved start of the
    #: instructions region).
    boundary_is_separator = False
    #: Whether the current question has shown a recognizable body tag or
    #: bracket-choice list item since its own frontmatter (if any) closed.
    body_seen = False
    while index < len(lines):
        if index in code_lines:
            index += 1
            continue
        line = lines[index].rstrip(" \t")
        stripped = line.strip(" \t")
        blank_before = index == 0 or not lines[index - 1].strip(" \t")

        if not body_seen and (
            _matches_tag(stripped) or BRACKET_ITEM_RE.match(stripped)
        ):
            body_seen = True

        if line == SEPARATOR and blank_before:
            starts.append(index)
            boundary = index + 1
            boundary_is_separator = True
            body_seen = False
            index += 1
            continue

        if line == "---" and blank_before:
            adjacent = all(not gap.strip(" \t") for gap in lines[boundary:index])
            is_own_frontmatter = boundary_is_separator and adjacent
            is_new_start = not is_own_frontmatter and (
                not starts or adjacent or body_seen
            )
            if is_own_frontmatter or is_new_start:
                # Positionally this candidate is allowed to open a fence;
                # still require the enclosed text to actually look like
                # YAML frontmatter (a cheap secondary guard, never the
                # primary test) before committing to it.
                closing = next(
                    (
                        j
                        for j in range(index + 1, len(lines))
                        if j not in code_lines
                        and lines[j].rstrip(" \t") == "---"
                        and _looks_like_frontmatter(lines[index + 1 : j])
                    ),
                    None,
                )
                if closing is not None:
                    if is_new_start:
                        starts.append(index)
                    boundary = closing + 1
                    boundary_is_separator = False
                    body_seen = False
                    index = closing + 1
                    continue
            if body_seen:
                # docs/exam.md, "Question and include blocks": after the
                # body, a `---` can only start the next block.
                raise ParseError(
                    f"line {index + 1}: a question's epilogue cannot use '---' "
                    "as a thematic break inside an exam; use '***' or '___'"
                )

        index += 1

    if not starts:
        return _clean_block("\n".join(lines)), []

    instructions = _clean_block("\n".join(lines[: starts[0]]))
    bounds = starts + [len(lines)]
    blocks = [lines[bounds[i] : bounds[i + 1]] for i in range(len(starts))]
    return instructions, blocks


def _looks_like_frontmatter(lines: list[str]) -> bool:
    """
    Report whether the lines between a candidate `---` pair parse as a
    YAML mapping, or nothing at all (an empty frontmatter block).

    A cheap secondary guard only: `_split_exam_blocks` decides whether a
    `---` is even eligible to open a fence by *position* first (see its
    docstring); this just keeps a positionally-eligible candidate from
    being treated as frontmatter when its enclosed text plainly isn't
    YAML at all (e.g. a malformed document, or two coincidentally close
    thematic breaks).
    """

    try:
        loaded = yaml.safe_load("\n".join(lines))
    except yaml.YAMLError:
        return False
    return loaded is None or isinstance(loaded, dict)


def _clean_block(text: str) -> str | None:
    stripped = text.strip(" \t\n")
    return stripped or None


def _parse_exam_block(
    lines: list[str],
    exam: dict[str, Any],
    *,
    warnings: list[Diagnostic] | None = None,
    index: int = 0,
) -> ExamEntryDict:
    """
    Turn one question block into an entry of the exam's `questions`.

    `index` is the block's 0-based position, used only to path-prefix any
    `unknown-frontmatter-key` warning as `("questions", index, key)`.

    A block with no explicit `id` gets none here -- the implicit,
    position-based id (`q<position>`, exam.md "Question ids") is
    `Exam.with_ids()`'s job, not the parser's
    (dev/specs/to-do/derived-ids.md).
    """

    # Drop a leading `===`; what follows is ordinary question source.
    has_separator = bool(lines) and lines[0].rstrip(" \t") == SEPARATOR
    if has_separator:
        lines = lines[1:]

    source = "\n".join(lines).strip("\n")
    frontmatter_text, _ = _split_frontmatter(source + "\n")
    front = _load_frontmatter_yaml(frontmatter_text) if frontmatter_text else {}

    is_include = "include" in front or "include-all" in front
    if has_separator and is_include and warnings is not None:
        warnings.append(
            Diagnostic(
                severity="warning",
                code="separator-before-include",
                path=("questions", index),
                message="an include block needs no '===' separator before it",
            )
        )

    if "include-all" in front:
        # Every key the block's frontmatter wrote is kept, not just the
        # known ones: an extra field is now an `unknown-include-field`
        # model error (exam.md, "No other field is allowed"), raised by
        # `mdq.models.IncludeAll` once this reaches it -- the same error
        # the dict/YAML path raises directly, so dropping the key here
        # instead would let the Markdown path silently lose it.
        entry: dict[str, Any] = dict(front)
        entry["include-all"] = str(front["include-all"])
        return cast(IncludeAllDict, entry)

    if "include" in front:
        entry = dict(front)
        entry["include"] = str(front["include"])
        return cast(IncludeDict, entry)

    block_warnings: list[Diagnostic] = []
    parsed_question: dict[str, Any] = dict(
        parse_question(source, warnings=block_warnings if warnings is not None else None)
    )
    if warnings is not None:
        warnings.extend(
            replace(w, path=("questions", index) + w.path) for w in block_warnings
        )
    _inherit_from_exam(parsed_question, exam)
    return cast(QuestionDict, parsed_question)


def _inherit_from_exam(question: dict[str, Any], exam: dict[str, Any]) -> None:
    """A question takes the exam's locale and author when it names none."""
    for field in INHERITED_FIELDS:
        if field not in question and field in exam:
            question[field] = exam[field]
