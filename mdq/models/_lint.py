"""
Helpers implementing the `lint()` methods of the models in `mdq.models`
(`mdq.models._render` is the same kind of helper module for `render()`).

These are the SHOULD/MAY-level rules the specification leaves to
implementations (see docs/question-types/): a compliant parser is free
to accept these documents, but an author almost never wants them. A
handful of rules serious enough that the specification calls them
critical stopped a document from *loading* instead -- those live as
pydantic validators in `mdq.models` now (see its module docstring and
dev/specs/to-do/lint-on-models.md), not here.

Every rule always runs, and each is tagged with the severity of what it
found:

* ``warning`` -- the document is probably wrong: a dead field, an
  ungradable answer key, a tolerance that can never match.
* ``info`` -- advisory/stylistic rules where the specification says an
  implementation MAY complain: redundant regex anchors, no-op fields,
  locale mismatches.

Every function here takes the already-validated field values (or
models) a `lint()` method has on hand, not a raw document: the shape
checks the old dict-based linter needed (`_iter_choices`, `_is_number`)
are the model layer's job now, so there is nothing left to guard against
here.

Two rules are not implemented here, because an already-parsed document
cannot show them: ``invalid-frontmatter-field`` (a frontmatter key the
parser dropped) and ``redundant-id`` (an ``id`` set in the frontmatter and
as a slug). ``mdq._parser`` emits them (``parse_question``/``parse_exam``,
via an optional ``warnings`` sink), and `mdq._loading` merges them ahead of
the diagnostics `lint()` produces.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Iterator, Sequence, Union

from markdown_it import MarkdownIt
from pygments.lexers import find_lexer_class_by_name
from pygments.util import ClassNotFound

from .. import _parser
from .._diagnostics import Diagnostic
from .._markdown import SLUG_PATTERN
from .._letters import (
    FALSE_LETTERS,
    LOCALE_ROWS,
    TRUE_LETTERS,
    nfkc,
    normalize_value,
)
from ._lint_codes import diag
from ._query import is_standard_query
from ._regex import (
    IGNORED_FLAGS,
    InvalidRegexError,
    escaped_code_points,
    normalize_text,
    parse_regex,
)

if TYPE_CHECKING:
    from ..types import NumericDomain
    from . import _choice, _numeric, _ordering, _text

#: Renders a single line's inline markdown to compare two ordering lines,
#: or two choices' texts, the way a student would see them
#: (`check_ordering_visually_identical_lines`,
#: `check_choices_visually_identical`), the same engine `mdq._parser` uses
#: to parse MDQ source.
_RENDER_MD = MarkdownIt("gfm-like")

# true-false.md, "Body": the TRUE and FALSE letter sets live in
# `mdq._letters`. Any other letter (besides the reserved `X`, rejected at
# the model layer) is in the WARNING category -- it is in neither list and
# reads as true, and compliant implementations SHOULD warn about it.
#
# Public (not `_`-prefixed): `mdq.models`'s TrueFalseQuestion validator
# ("marker agrees with correct") also classifies a marker by these sets, to
# raise a model error rather than a lint warning.
TRUE_MARKERS = TRUE_LETTERS
FALSE_MARKERS = FALSE_LETTERS

# Two-letter codes that look like a language but are not valid ISO 639-1;
# they are almost always a country code written where a language belongs.
# The generic.md `locale` pattern happily accepts them.
_LOOKALIKE_LANGUAGE_SUBTAGS = {
    "cn": "zh",
    "sp": "es",
    "jp": "ja",
    "gr": "el",
    "kr": "ko",
    "cz": "cs",
    "dk": "da",
    "ua": "uk",
}

# generic.md: the schema pattern and the model check the shape of a `uuid`
# (`mdq._markdown.UUID_RE`) but let any nibble through, so the two
# meaningful nibbles are checked here.
_UUID_VERSIONS = frozenset("12345678")
_UUID_VARIANTS = frozenset("89abAB")


def _language_subtag(locale: str | None) -> str:
    if locale is None:
        return ""
    return locale.split("-")[0].lower()


# ----------------------------------------------------------------------
# common rules
# ----------------------------------------------------------------------
def has_visible_character(value: str) -> bool:
    """
    Whether `value` has a visible character, as grammar.md "Visible
    characters" defines it: not white space, and not a control (`Cc`) or
    format (`Cf`) character such as U+200B.
    """
    return any(
        not (c.isspace() or unicodedata.category(c) in ("Cc", "Cf")) for c in value
    )


#: base.md:252, footnote [^2]: the url-safe shape a question `id` SHOULD have.
_URL_SAFE_ID_RE = re.compile(SLUG_PATTERN)


def check_id_is_url_safe(id: str | None) -> Iterator[Diagnostic]:
    """base.md:252: `id` SHOULD be url-safe (`[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*`)."""
    if id is None or _URL_SAFE_ID_RE.match(id):
        return
    yield diag(
        code="unsafe-id",
        path=("id",),
        message=(
            f"{id!r} is not url-safe; expected only letters, digits, "
            f"'-' and '_', per the pattern "
            f"[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*"
        ),
    )


def check_id_and_title_defined(
    id: str | None, title: str | None
) -> Iterator[Diagnostic]:
    """base.md:255: `id` and `title` SHOULD both be defined."""
    if id is None:
        yield diag(
            code="missing-id",
            path=("id",),
            message="'id' is not defined",
        )
    if title is None:
        yield diag(
            code="missing-title",
            path=("title",),
            message="'title' is not defined",
        )


def check_uuid_version_and_variant(uuid: str | None) -> Iterator[Diagnostic]:
    """generic.md: the UUID's version and variant nibbles are meaningful."""
    if uuid is None:
        return

    # The model has checked the shape: `xxxxxxxx-xxxx-Mxxx-Nxxx-xxxxxxxxxxxx`.
    version = uuid[14]
    if version not in _UUID_VERSIONS:
        yield diag(
            code="uuid-unknown-version",
            path=("uuid",),
            message=(
                f"UUID version nibble is {version!r}; expected one of "
                f"1-8 (got the 13th character of {uuid!r})"
            ),
        )

    variant = uuid[19]
    if variant not in _UUID_VARIANTS:
        yield diag(
            code="uuid-unknown-variant",
            path=("uuid",),
            message=(
                f"UUID variant nibble is {variant!r}; expected one of "
                f"8, 9, a, b (got the 17th character of {uuid!r})"
            ),
        )


def check_tags(tags: Sequence[str]) -> Iterator[Diagnostic]:
    """
    generic.md accepts `tags` as a list or as a single comma-delimited
    string; a comma surviving inside a list entry means the string form
    was never split.
    """
    for index, tag in enumerate(tags):
        if "," in tag:
            yield diag(
                code="unsplit-tag-list",
                path=("tags", index),
                message=(
                    f"tag {tag!r} contains a comma; a comma-delimited "
                    f"string is only split when `tags` is written as a "
                    f"single string, not as a list"
                ),
            )


def check_setext_heading(
    text: str | None, path: tuple[str | int, ...]
) -> Iterator[Diagnostic]:
    """
    exam.md, "Questions": a `---` or `===` line right after text is a
    setext heading underline in CommonMark, not a block boundary, so a
    frontmatter or include block glued to a paragraph is swallowed into
    the text before it. One warning per field, at the first heading.
    The model only sees the exam's `instructions` verbatim; the question
    parser rewrites a setext heading in a question, so `parse_exam`
    reports those from the raw lines.
    """
    if not text:
        return
    for token in _RENDER_MD.parse(text):
        if (
            token.type == "heading_open"
            and token.level == 0
            and token.markup in ("-", "=")
        ):
            yield diag(
                code="setext-heading",
                path=path,
                message=(
                    f"a {token.markup * 3!r} line right after text is a "
                    "setext heading, not a block boundary; put a blank "
                    "line before the '---' that opens a block"
                ),
            )
            return


def check_unsafe_thematic_break(
    text: str | None, path: tuple[str | int, ...]
) -> Iterator[Diagnostic]:
    """
    exam.md, "Questions": a thematic break written with `-` (`---`,
    `- - -`, ...) changes meaning inside an exam, where a `---` line
    opens a block. One warning per field. A `---` right after text is a
    setext underline, which `check_setext_heading` reports instead.
    """
    if not text:
        return
    for token in _RENDER_MD.parse(text):
        if token.type == "hr" and token.markup.startswith("-"):
            yield diag(
                code="unsafe-thematic-break",
                path=path,
                message=(
                    "'---' is a thematic break here, but inside an exam a "
                    "'---' line opens a block; write '***' or '___'"
                ),
            )
            return


def check_stray_choice_markers(
    text: str | None, path: tuple[str | int, ...]
) -> Iterator[Diagnostic]:
    """
    question-base.md, "Forbidden elements": one warning per item of an
    unordered list in which only some items start with a choice marker,
    when the marker of the item is a choice value or is empty. The list
    is valid prose, but it is almost always a broken choice list.
    """
    if not text:
        return
    for marker in _parser.find_stray_choice_markers(text):
        yield diag(
            code="stray-choice-marker",
            path=path,
            message=(
                f"a list item starts with the choice marker {marker!r}, but "
                "other items of its list do not, so the list is not a choice list"
            ),
        )


def check_locale_language_subtag(locale: str | None) -> Iterator[Diagnostic]:
    """
    A well-formed tag can still name the wrong thing: this catches
    country codes written where a language belongs.
    """
    subtag = _language_subtag(locale)
    suggestion = _LOOKALIKE_LANGUAGE_SUBTAGS.get(subtag)
    if suggestion is None:
        return
    yield diag(
        code="locale-lookalike-language",
        path=("locale",),
        message=(
            f"{subtag!r} is not a valid ISO 639-1 language code; "
            f"did you mean {suggestion!r}?"
        ),
    )


# ----------------------------------------------------------------------
# choice rules (multiple-choice, multiple-selection, true-false, and the
# choice blanks of a fill-in question)
# ----------------------------------------------------------------------


def check_choice_ids_defined(
    choices: Sequence[_choice.ScoredChoice | _choice.BooleanChoice | _choice.Statement],
    path: tuple[Union[str, int], ...],
) -> Iterator[Diagnostic]:
    """
    multiple-choice.md, "Choices": a choice SHOULD declare its own `id`
    rather than rely on one derived from its text -- a derived id is
    only as stable as the slugifier that produced it.
    """
    for index, choice in enumerate(choices):
        if choice.id is None:
            yield diag(
                code="missing-choice-id",
                path=path + (index, "id"),
                message=(
                    "choice has no explicit id; one will be derived from its text"
                ),
            )


def check_choices_visually_identical(
    choices: Sequence[_choice.ScoredChoice | _choice.BooleanChoice | _choice.Statement],
    path: tuple[Union[str, int], ...],
) -> Iterator[Diagnostic]:
    """
    multiple-choice.md, "Choices": two choices whose text renders alike
    but is written differently in source are indistinguishable to a
    reader -- the same comparison
    `check_ordering_visually_identical_lines` applies to ordering lines.
    """
    seen: dict[str, int] = {}
    for index, choice in enumerate(choices):
        key = _render_visual_key(choice.text)
        first_index = seen.setdefault(key, index)
        # An exact repeat is a `duplicate-choice-text` model error, so a
        # choice that renders like an earlier one is written differently.
        if first_index == index:
            continue
        yield diag(
            code="visually-identical-choices",
            path=path + (index, "text"),
            message=(
                f"choice text renders the same as choices[{first_index}] "
                f"but is written differently in source"
            ),
        )


def check_multiple_choice_answers(
    choices: Sequence[_choice.ScoredChoice],
    path: tuple[Union[str, int], ...],
) -> Iterator[Diagnostic]:
    """
    multiple-choice.md: a question MAY mark any number of choices as
    correct, and typically marks exactly one -- more than one is unusual
    enough to flag (`many-correct-choices`, `info`), but
    not a mistake. No correct choice at all more likely is one.

    Also used, via `mdq.models._fill_in.FillInQuestion.lint`, for a
    fill-in choice blank -- graded like multiple-choice, so the same
    rules apply (fill-in.md, "Additional Rules").
    """
    correct = [
        index for index, choice in enumerate(choices) if (choice.score or 0) >= 1
    ]

    if not correct:
        yield diag(
            code="no-correct-choice",
            path=path,
            message="no choice has a score >= 1; the question has no correct answer",
        )

    if len(correct) > 1:
        listed = ", ".join(str(index) for index in correct)
        yield diag(
            code="many-correct-choices",
            path=path,
            message=(
                f"choices {listed} all have a score >= 1; a question MAY "
                f"mark any number of choices as correct, but the student "
                f"still picks a single one"
            ),
        )

    if len(correct) == len(choices):
        yield diag(
            code="all-choices-correct",
            path=path,
            message="every choice has a score >= 1; the question has no wrong answer",
        )


def check_multiple_selection_answers(
    choices: Sequence[_choice.BooleanChoice],
    path: tuple[Union[str, int], ...],
) -> Iterator[Diagnostic]:
    """
    multiple-selection.md: a well-formed question mixes correct and
    incorrect choices -- one with none correct has nothing to select,
    and one where every choice is correct has nothing to leave unchecked.
    """
    correct = [index for index, choice in enumerate(choices) if choice.correct]

    if not correct:
        yield diag(
            code="no-correct-choice",
            path=path,
            message="no choice is correct; the question has nothing to select",
        )
    elif len(correct) == len(choices):
        yield diag(
            code="all-choices-correct",
            path=path,
            message="every choice is correct; the question has nothing to leave unchecked",
        )


def check_true_false_markers(
    choices: Sequence[_choice.Statement],
    locale: str | None,
) -> Iterator[Diagnostic]:
    """
    true-false.md, "Locale": the marker rules, in this order, on the
    normalized value.

    1. A false friend of the locale row: only `false-friend-true-false-marker`.
    2. A letter the row accepts (even a WARNING letter): no warning.
    3. A WARNING letter: only `unlisted-true-false-marker`.
    4. A locale without a row: no locale warning.
    5. Any other TRUE or FALSE letter: `locale-mismatched-true-false-marker`.

    The reserved `X`/`x` marker is rejected at the model layer
    (`reserved-true-false-marker`), so it never reaches here.
    """
    row = LOCALE_ROWS.get(_language_subtag(locale))

    for index, choice in enumerate(choices):
        marker = choice.marker
        if marker is None:
            continue

        value = normalize_value(marker)
        path = ("choices", index, "marker")
        if row is not None and value in row.false_friends:
            yield diag(
                code="false-friend-true-false-marker",
                path=path,
                message=(
                    f"{marker!r} reads as true (see true-false.md), but "
                    f"it can mean false in the language of locale "
                    f"{locale!r}; if this choice was meant to be false, "
                    f"use 'F' instead"
                ),
            )
        elif row is not None and (value in row.true or value in row.false):
            continue
        elif value not in TRUE_MARKERS and value not in FALSE_MARKERS:
            yield diag(
                code="unlisted-true-false-marker",
                path=path,
                message=(
                    f"{marker!r} is in neither the true nor the false "
                    f"marker list: it reads as true"
                ),
            )
        elif row is not None:
            yield diag(
                code="locale-mismatched-true-false-marker",
                path=path,
                message=(
                    f"{marker!r} does not fit locale {locale!r}: use "
                    f"'T'/'F' or a letter of the locale table"
                ),
            )


def check_true_false_marker_nfkc(
    choices: Sequence[_choice.Statement],
) -> Iterator[Diagnostic]:
    """
    true-false.md, "Additional Rules": a marker that is not its own NFKC
    form (`non-nfkc-true-false-marker`, info), for example U+FF26
    FULLWIDTH LATIN CAPITAL LETTER F or U+212B ANGSTROM SIGN. The letter
    is valid and keeps its written form in `marker`, but it is read as
    its NFKC form, and it renders differently than intended.
    """
    for index, choice in enumerate(choices):
        marker = choice.marker
        if marker is None:
            continue
        form = nfkc(marker)
        if form != marker:
            yield diag(
                code="non-nfkc-true-false-marker",
                path=("choices", index, "marker"),
                message=(f"{marker!r} is not its own NFKC form; read as {form!r}"),
            )


def check_true_false_uniform_answers(
    choices: Sequence[_choice.Statement],
) -> Iterator[Diagnostic]:
    """
    true-false.md:218: a question whose statements are all true or all
    false is usually an authoring mistake -- a well-formed question
    presents a mix for the student to judge.
    """
    if not choices:
        return
    values = {choice.correct for choice in choices}
    if len(values) > 1:
        return
    yield diag(
        code="uniform-true-false-answers",
        path=("choices",),
        message=(
            f"every statement is {'true' if choices[0].correct else 'false'}; "
            f"a true/false question should mix true and false statements"
        ),
    )


# ----------------------------------------------------------------------
# per-type rules
# ----------------------------------------------------------------------
def check_highlight_language(highlight: str | None) -> Iterator[Diagnostic]:
    """
    essay.md, ordering.md: `highlight` SHOULD name a language a
    highlighter can recognize. Any alias of a Pygments lexer is
    accepted as the reference list (`pygments.lexers.
    find_lexer_class_by_name`) -- `pygments` is a direct dependency for
    exactly this check.
    """
    if highlight is None:
        return
    try:
        find_lexer_class_by_name(highlight)
    except ClassNotFound:
        yield diag(
            code="unknown-highlight-language",
            path=("highlight",),
            message=(
                f"{highlight!r} is not a recognized Pygments lexer "
                f"alias, so a highlighter would not know this language"
            ),
        )


def check_code_highlight(content: str, highlight: str | None) -> Iterator[Diagnostic]:
    """
    essay.md, ordering.md: `content: code` with no `highlight` is an
    info (`code-content-without-highlight`); with one, the language is
    checked (`unknown-highlight-language`). A `highlight` with any other
    content is a `schema-error` the models already reject.
    """
    if content != "code":
        return
    if highlight is None:
        yield diag(
            code="code-content-without-highlight",
            path=("highlight",),
            message=(
                "content is 'code' but no 'highlight' language is given, "
                "so a highlighter cannot color the code"
            ),
        )
        return
    yield from check_highlight_language(highlight)


def check_missing_answer_key(answer_key: str | None) -> Iterator[Diagnostic]:
    """essay.md:91: `answerKey` SHOULD be defined, for a human grader's benefit."""
    if answer_key is not None:
        return
    yield diag(
        code="missing-answer-key",
        path=("answerKey",),
        message="'answerKey' is not defined",
    )


def check_short_answer(
    *,
    accept: "list[_text.AnswerPattern] | None",
    reject: "list[_text.AnswerPattern] | None" = None,
    pre_accept: "list[_text.AnswerPattern] | None" = None,
    pre_reject: "list[_text.AnswerPattern] | None" = None,
    path: tuple[Union[str, int], ...],
) -> Iterator[Diagnostic]:
    """
    short-answer.md, "Additional Rules": the regex lints
    (`redundant-regex-anchor`, `ignored-regex-flag`,
    `unmatchable-regex-escape`) over the four
    pattern lists.

    Diagnostics use the frontmatter key: `path + ("preAccept", index)`.

    Whether every `/`-delimited pattern in `accept`/`reject`/
    `preAccept`/`preReject` compiles is a model error
    (`invalid-regex` -- dev/specs/to-do/lint-on-models.md), not checked
    here.
    """
    yield from _check_pattern_list(accept, "accept", path=path)
    yield from _check_pattern_list(pre_accept, "preAccept", path=path)
    yield from _check_pattern_list(reject, "reject", path=path)
    yield from _check_pattern_list(pre_reject, "preReject", path=path)


def check_no_correct_answer(
    *,
    accept: "list[_text.AnswerPattern] | None",
    unmatched: str,
    path: tuple[Union[str, int], ...],
) -> Iterator[Diagnostic]:
    """
    short-answer.md, "Additional Rules": `unmatched` is `"incorrect"`
    but there is no `accept` pattern, so no response can be correct
    (`no-correct-answer`). `unmatched` is the effective value.
    """
    if unmatched != "incorrect" or accept:
        return
    yield diag(
        code="no-correct-answer",
        path=path,
        message=(
            "'unmatched' is 'incorrect' but no 'accept' pattern is given: "
            "no response can be correct"
        ),
    )


def _check_pattern_list(
    patterns: "list[_text.AnswerPattern] | None",
    key: str,
    *,
    path: tuple[Union[str, int], ...],
) -> Iterator[Diagnostic]:
    """Lints one pattern list, named by its frontmatter `key`: the regex lints of every entry."""
    for index, pattern in enumerate(patterns or []):
        # Not `AnswerPattern.kind`: this check strips every Unicode space
        # (`str.strip()`) before testing for the opening `/`, while the
        # matcher strips only spaces and tabs.
        if not pattern.pattern.strip().startswith("/"):
            continue
        try:
            body, raw_flags = parse_regex(pattern.pattern)
        except InvalidRegexError:
            continue
        item_path = path + (key, index)
        yield from _check_redundant_regex_anchor(body, raw_flags, item_path)
        yield from _check_ignored_regex_flags(raw_flags, item_path)
        yield from _check_unmatchable_regex_escape(body, raw_flags, item_path)


def _check_redundant_regex_anchor(
    body: str, raw_flags: str, path: tuple[Union[str, int], ...]
) -> Iterator[Diagnostic]:
    """
    short-answer.md, "Regex flags": a leading `^` is implicit unless the
    `f` flag is set, and a trailing `$` is implicit unless `f` or `b` is
    set. A `$` preceded by an odd number of backslashes is a literal.
    """
    leading = body.startswith("^") and "f" not in raw_flags
    trailing = False
    if body.endswith("$") and not {"f", "b"} & set(raw_flags):
        backslashes = len(body) - 1 - len(body[:-1].rstrip("\\"))
        trailing = backslashes % 2 == 0
    if not (leading or trailing):
        return
    yield diag(
        code="redundant-regex-anchor",
        path=path,
        message=(
            "matching is already anchored here, so a leading '^' or "
            "trailing '$' is redundant"
        ),
    )


def _check_ignored_regex_flags(
    raw_flags: str, path: tuple[Union[str, int], ...]
) -> Iterator[Diagnostic]:
    """
    short-answer.md:385: `m`, `g`, `s`, `u`, `v`, `y` and `d` are accepted
    for compatibility but have no effect (see [regex flags](regex-flags)).
    """
    ignored = sorted(set(raw_flags) & IGNORED_FLAGS)
    if not ignored:
        return
    flags_text = ", ".join(repr(flag) for flag in ignored)
    yield diag(
        code="ignored-regex-flag",
        path=path,
        message=f"flag(s) {flags_text} are accepted but have no effect on matching",
    )


def _check_unmatchable_regex_escape(
    body: str, raw_flags: str, path: tuple[Union[str, int], ...]
) -> Iterator[Diagnostic]:
    """
    patterns.md, "Regex flags": under `n`, an escape that denotes a code
    point is never stripped. If the strip changes that code point, the
    stripped response cannot contain it. One diagnostic per pattern.
    """
    if "n" not in raw_flags:
        return
    if not any(_stripped_by_n(code_point) for code_point in escaped_code_points(body)):
        return
    yield diag(
        code="unmatchable-regex-escape",
        path=path,
        message=(
            "the 'n' flag strips diacritics from the response, so an escape "
            "for a code point that the strip changes cannot match"
        ),
    )


def _stripped_by_n(code_point: int) -> bool:
    """True if the `n` strip changes the code point."""
    char = chr(code_point)
    return normalize_text(char) != char


_DOMAIN_RANK: dict[str, int] = {"integer": 0, "fraction": 1, "decimal": 2}


def _effective_numeric_domain(
    answer: int | float | str,
    domain: "NumericDomain | None",
    tolerance: "_numeric.Tolerance | None",
) -> "NumericDomain":
    """
    The declared `domain`, else the one inferred from the answer and the
    absolute tolerance (numeric.md, "Number type/domain": the wider of
    the two).
    """
    if domain is not None:
        return domain
    inferred = _infer_numeric_domain(answer)
    if tolerance is not None and tolerance.absolute is not None:
        tolerance_domain = _infer_numeric_domain(tolerance.absolute)
        if _DOMAIN_RANK[tolerance_domain] > _DOMAIN_RANK[inferred]:
            return tolerance_domain
    return inferred


def _infer_numeric_domain(answer: int | float | str) -> "NumericDomain":
    """
    numeric.md, "Number type/domain": infer the domain an `answer` is
    written in, ranking integer < fraction < decimal. A `str` answer
    holds a `/` (a fraction) or a `.` or an exponent (a decimal) or
    neither (an integer); a number is an integer when it has no fractional part,
    decimal otherwise. The parser keeps a whole decimal such as `2.0`
    as a string, so a whole number here was not written as a decimal
    in Markdown.
    """
    if isinstance(answer, str):
        text = answer.strip()
        if "/" in text:
            return "fraction"
        if "." in text or "e" in text or "E" in text:
            return "decimal"
        return "integer"
    return "integer" if float(answer) == int(answer) else "decimal"


def check_numeric(
    *,
    answer: int | float | str,
    domain: "NumericDomain | None",
    decimal_places: int | None,
    tolerance: "_numeric.Tolerance | None",
    path: tuple[Union[str, int], ...],
) -> Iterator[Diagnostic]:
    """
    numeric.md: the domain is inferred from the answer's representation
    when not declared, so a declared domain that contradicts the answer
    is a mistake; and a relative tolerance around zero can never widen
    the accepted range.
    """
    effective_domain = _effective_numeric_domain(answer, domain, tolerance)
    # A string answer is already grammar-validated, so `Fraction` accepts it.
    value: Fraction | float = Fraction(answer) if isinstance(answer, str) else answer
    # numeric.md, "Additional Rules": under `integer` the answer must be
    # whole; under `fraction` it must be whole or a fraction string.
    is_fraction_string = isinstance(answer, str) and "/" in answer
    if (domain == "integer" or (domain == "fraction" and not is_fraction_string)) and (
        value != int(value)
    ):
        yield diag(
            code="answer-outside-domain",
            path=path + ("answer",),
            message=(
                f"domain is {domain!r} but the answer {answer!r} is not "
                + (
                    "a whole number"
                    if domain == "integer"
                    else "a whole number or a fraction"
                )
            ),
        )

    if (
        domain in ("integer", "fraction")
        and tolerance is not None
        and tolerance.absolute is not None
        and _infer_numeric_domain(tolerance.absolute) == "decimal"
    ):
        yield diag(
            code="domain-mismatch",
            path=path + ("domain",),
            message=(
                f"domain is {domain!r}, but the absolute tolerance "
                f"{tolerance.absolute!r} is a decimal"
            ),
        )

    if tolerance is None and effective_domain == "decimal":
        yield diag(
            code="missing-tolerance",
            path=path + ("tolerance",),
            message=(
                f"the answer {answer!r} is in a decimal domain, but "
                f"no tolerance is given; an exact comparison rarely "
                f"matches a typed response"
            ),
        )

    if tolerance is not None:
        relative = tolerance.relative
        if relative is not None and relative > 0 and value == 0:
            yield diag(
                code="relative-tolerance-around-zero",
                path=path + ("tolerance", "relative"),
                message=(
                    "a relative tolerance is computed as answer x "
                    "relative, which is 0 when the answer is 0; only an "
                    "exact 0 would be accepted"
                ),
            )

        if relative is not None and relative > 1:
            yield diag(
                code="relative-tolerance-over-one",
                path=path + ("tolerance", "relative"),
                message=(
                    f"a relative tolerance of {relative!r} is "
                    f"{relative * 100:g}%: a tolerance above 100% accepts "
                    f"responses of the opposite sign to the answer"
                ),
            )

    if decimal_places is not None and effective_domain != "decimal":
        source = "" if domain is not None else " (inferred from the answer)"
        yield diag(
            code="ignored-decimal-places",
            path=path + ("decimalPlaces",),
            message=(
                f"'decimalPlaces' is ignored when domain is "
                f"{effective_domain!r}{source}"
            ),
        )


def check_exam_without_questions(
    questions: Sequence[object], path: tuple[Union[str, int], ...]
) -> Iterator[Diagnostic]:
    """
    exam.md: an exam MAY contain zero questions, but SHOULD warn -- an
    exam with nothing to answer is a draft, not an assessment.
    """
    if questions:
        return
    yield diag(
        code="exam-without-questions",
        path=path,
        message="the exam contains no questions, so it cannot be answered",
    )


def check_include_query(
    query: str, path: tuple[Union[str, int], ...]
) -> Iterator[Diagnostic]:
    """exam.md, "Include all": a query should follow the recommended language."""
    if is_standard_query(query):
        return
    yield diag(
        code="nonstandard-include-query",
        path=path,
        message=f"the query {query!r} does not follow the recommended query language",
    )


def check_undeclared_id_after_include_all(
    path: tuple[Union[str, int], ...],
) -> Iterator[Diagnostic]:
    """
    exam.md, "Question ids": the derived id of a question after an
    `includeAll` changes with the questions the query adds.
    """
    yield diag(
        code="undeclared-id-after-include-all",
        path=path,
        message=(
            "the derived id of a question after an 'includeAll' changes "
            "with the questions the query adds; declare an 'id'"
        ),
    )


# ----------------------------------------------------------------------
# ordering
# ----------------------------------------------------------------------


def check_ordering_duplicate_alternatives(
    question: _ordering.OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#acceptedrejected-answers: a question SHOULD NOT declare
    two `accept` sections, or two `reject` sections, whose lines are the
    same once fully normalized -- every entry of `normalizations`, plus
    whatever `indentation` implies. An accept/reject pair is a model
    error (`accept-reject-overlap`) and never reaches this check.
    """
    for section in ("accept", "reject"):
        seen: dict[tuple[Any, ...], tuple[str, int]] = {}
        for index, alt in enumerate(getattr(question, section)):
            key = question.comparison_key(alt.lines)
            first = seen.get(key)
            if first is not None:
                first_section, first_index = first
                yield diag(
                    code="duplicate-alternative-lines",
                    path=(section, index, "lines"),
                    message=(
                        f"{section}[{index}] holds the same lines as "
                        f"{first_section}[{first_index}], once fully "
                        f"normalized"
                    ),
                )
            else:
                seen[key] = (section, index)


def check_ordering_accept_repeats_answer_key(
    question: _ordering.OrderingQuestion,
) -> Iterator[Diagnostic]:
    """ordering.md#acceptedrejected-answers: `accept` SHOULD NOT repeat `lines`."""
    answer_key = question.comparison_key(question.lines)
    for index, alt in enumerate(question.accept):
        if question.comparison_key(alt.lines) == answer_key:
            yield diag(
                code="accept-repeats-answer-key",
                path=("accept", index, "lines"),
                message=(
                    f"accept[{index}] repeats the [ordering] block's own "
                    f"lines, once fully normalized"
                ),
            )


def check_ordering_unreachable_reject(
    question: _ordering.OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#acceptedrejected-answers: a `reject` entry that uses a
    line, or more copies of a line, than the presented pool (`lines`
    plus `extra`) offers can never match a response. Lines are identified
    as in `OrderingQuestion.identity_key`.
    """
    pool = Counter(question.identity_key(question.lines))
    pool.update(question.identity_key(question.extra))
    for index, alt in enumerate(question.reject):
        if Counter(question.identity_key(alt.lines)) - pool:
            yield diag(
                code="unreachable-alternative",
                path=("reject", index, "lines"),
                message=(
                    f"reject[{index}] uses a line, or more copies of a "
                    f"line, than the lines and extra blocks offer, so no "
                    f"response can match it"
                ),
            )


def check_ordering_redundant_strict_indentation(
    question: _ordering.OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#indentation[^8]: `dedent` flattens every line to level 0,
    so `indentation: "strict"` has nothing left to compare.
    `indentation: "lenient"` implies `dedent` and therefore never
    combines with `"strict"` in the first place, so only an explicit
    `dedent` in `normalizations` can trigger this.
    """
    if question.indentation != "strict":
        return
    if "dedent" not in question.effective_normalizations():
        return
    yield diag(
        code="redundant-strict-indentation",
        path=("indentation",),
        message=(
            "indentation is 'strict' but 'dedent' is normalized, which "
            "flattens every line to level 0, so there is nothing left "
            "for 'strict' to compare"
        ),
    )


def check_ordering_blank_lines(
    question: _ordering.OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#additional-rules: a blank `lines`/`extra` entry should
    only appear when `skip-blanks` is normalized -- otherwise it counts
    when comparing a response.
    """
    if "skip-blanks" in question.effective_normalizations():
        return

    for field_name in ("lines", "extra"):
        for index, (_, text) in enumerate(getattr(question, field_name)):
            if text.strip() == "":
                yield diag(
                    code="blank-ordering-line",
                    path=(field_name, index),
                    message=(
                        "line is blank, and 'skip-blanks' is not "
                        "normalized, so it counts when comparing a "
                        "response"
                    ),
                )


def check_case_variant_blank_ids(blank_ids: Sequence[str]) -> Iterator[Diagnostic]:
    """
    fill-in.md, "Blank definitions": blank ids are compared exactly, so two
    ids that differ only in ASCII case are two blanks. CommonMark would
    merge them, so warn (`case-variant-blank-id`).
    """
    first_by_folded: dict[str, str] = {}
    for index, blank_id in enumerate(blank_ids):
        folded = blank_id.lower()
        first = first_by_folded.setdefault(folded, blank_id)
        if first != blank_id:
            yield diag(
                code="case-variant-blank-id",
                path=("blanks", index, "id"),
                message=(
                    f"blank id {blank_id!r} differs from {first!r} only in "
                    f"case; blank ids are case-sensitive, but CommonMark "
                    f"labels are not"
                ),
            )


def check_ordering_reject_without_feedback(
    question: _ordering.OrderingQuestion,
) -> Iterator[Diagnostic]:
    """ordering.md#feedback: a `reject` section SHOULD declare feedback."""
    for index, alt in enumerate(question.reject):
        if alt.feedback is None:
            yield diag(
                code="reject-without-feedback",
                path=("reject", index),
                message=(
                    f"reject[{index}] declares no feedback, so it explains "
                    f"nothing to the student"
                ),
            )


def _render_visual_key(text: str) -> str:
    """How `text` renders, for comparing lines/choices as a reader would."""
    return str(_RENDER_MD.renderInline(text)).strip()


def check_ordering_visually_identical_lines(
    question: _ordering.OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#body: two `lines`/`extra` entries at the same
    indentation level should not render alike while differing in their
    raw markdown source -- a student ordering the rendered text cannot
    tell such a pair apart. Only meaningful for `content: "text"`: a
    code block's content is shown verbatim, never rendered.
    """
    if question.content != "text":
        return

    seen: dict[tuple[int, str], tuple[str, int, str]] = {}
    for field_name in ("lines", "extra"):
        for index, (level, text) in enumerate(getattr(question, field_name)):
            key = (level, _render_visual_key(text))
            first = seen.get(key)
            if first is None:
                seen[key] = (field_name, index, text)
                continue

            first_field, first_index, first_text = first
            if text == first_text:
                continue  # an intentional repeat, not a same-render pair.
            yield diag(
                code="visually-identical-lines",
                path=(field_name, index),
                message=(
                    f"line renders the same as {first_field}[{first_index}] "
                    f"but is written differently in source; a student "
                    f"ordering the rendered text cannot tell them apart"
                ),
            )
