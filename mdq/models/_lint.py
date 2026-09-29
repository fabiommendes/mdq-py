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

One ``warning``-severity rule, ``unknown-frontmatter-key``, is not
implemented here: an already-parsed document has no way to see a
frontmatter key the parser dropped while building it. It is instead
emitted by ``mdq._parser`` (``parse_question``/``parse_exam``, via an
optional ``warnings`` sink) for every frontmatter key it does not
recognize -- a typo like ``auther:``, or a field that
never existed -- and merged into `mdq._loading`'s diagnostics ahead of
the ones `lint()` produces.
"""

from __future__ import annotations

import re
import unicodedata
from fractions import Fraction
from typing import TYPE_CHECKING, Sequence, Union

from markdown_it import MarkdownIt
from pygments.lexers import find_lexer_class_by_name
from pygments.util import ClassNotFound

from .._diagnostics import Diagnostic
from ._query import is_standard_query
from ._regex import IGNORED_FLAGS, InvalidRegexError, parse_regex

if TYPE_CHECKING:
    from ..types import NumericDomain
    from . import _choice, _numeric, _ordering, _text

#: Renders a single line's inline markdown to compare two ordering lines,
#: or two choices' texts, the way a student would see them
#: (`check_ordering_visually_identical_lines`,
#: `check_choices_visually_identical`), the same engine `mdq._parser` uses
#: to parse MDQ source.
_RENDER_MD = MarkdownIt("gfm-like")

# true-false.md: `T`, `V`, `S` and the CJK characters 对/真 always mean
# true; `F` and the CJK characters 错/偽 always mean false. Any other
# letter (besides the reserved `X`, rejected at the model layer) is
# PROVISIONAL -- it reads as true today, but the document says compliant
# implementations SHOULD warn, since a future revision of the spec may
# reassign it.
#
# Public (not `_`-prefixed): `mdq.models`'s TrueFalseQuestion validator
# (true-false.md:210, "marker agrees with correct") also classifies a
# marker by these sets, to raise a model error rather than a lint warning.
TRUE_MARKERS = frozenset("TVS对真")
FALSE_MARKERS = frozenset("F错偽")

# docs/references/true-false-spellings.md, keyed by primary language
# subtag: the letters an author writing in that language would reach for.
_LOCALE_MARKERS = {
    "en": ("T", "F"),  # true / false
    "pt": ("V", "F"),  # verdadeiro / falso
    "es": ("V", "F"),  # verdadero / falso
}

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

# A stem is meant to be a single paragraph of prose (generic.md: "the
# stem is a paragraph of text (and not other block elements such as
# tables, lists, etc)"). These openers say otherwise.
_NON_PARAGRAPH_STEM = (
    (re.compile(r"^#{1,6}\s"), "a heading"),
    (re.compile(r"^\s*[-*+]\s"), "a list"),
    (re.compile(r"^\s*[0-9]+[.)]\s"), "an ordered list"),
    (re.compile(r"^\s*>\s"), "a blockquote"),
    (re.compile(r"^\s*\|"), "a table"),
    (re.compile(r"^\s*(```|~~~)"), "a code fence"),
)

# generic.md: `uuid` MUST be `xxxxxxxx-xxxx-Mxxx-Nxxx-xxxxxxxxxxxx`, where
# M is the version and N the variant. The schema pattern checks the shape
# and the hyphens but lets any nibble through, so the two meaningful
# nibbles are checked here.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"(?P<version>[0-9a-fA-F])[0-9a-fA-F]{3}-"
    r"(?P<variant>[0-9a-fA-F])[0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_UUID_VERSIONS = frozenset("12345678")
_UUID_VARIANTS = frozenset("89abAB")


def _language_subtag(locale: str | None) -> str:
    if not isinstance(locale, str):
        return ""
    return locale.split("-")[0].lower()


# ----------------------------------------------------------------------
# common rules
# ----------------------------------------------------------------------
def check_blank_text_field(value: str | None, field_name: str) -> list[Diagnostic]:
    """
    A free-text field, if defined, must have at least one visible
    (non-whitespace) character.

    Only for the fields this stays a *warning* on (`title`, `author`,
    `comment`, `answerKey`) -- `preamble`/`epilogue`/`stem` raise
    `blank-text-field` as a model error instead (`mdq.models`).
    """
    if value is None or value.strip() != "":
        return []
    return [
        Diagnostic(
            severity="warning",
            code="blank-text-field",
            path=(field_name,),
            message=f"'{field_name}' is defined but has no visible characters",
        )
    ]


#: base.md:252, footnote [^2]: the url-safe shape a question `id` SHOULD have.
_URL_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*$")


def check_id_is_url_safe(id: str | None) -> list[Diagnostic]:
    """base.md:252: `id` SHOULD be url-safe (`[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*`)."""
    if id is None or _URL_SAFE_ID_RE.match(id):
        return []
    return [
        Diagnostic(
            severity="warning",
            code="unsafe-id",
            path=("id",),
            message=(
                f"{id!r} is not url-safe; expected only letters, digits, "
                f"'-' and '_', per the pattern "
                f"[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*"
            ),
        )
    ]


def check_id_and_title_defined(id: str | None, title: str | None) -> list[Diagnostic]:
    """base.md:255: `id` and `title` SHOULD both be defined."""
    warnings: list[Diagnostic] = []
    if id is None:
        warnings.append(
            Diagnostic(
                severity="info",
                code="missing-id",
                path=("id",),
                message="'id' is not defined",
            )
        )
    if title is None:
        warnings.append(
            Diagnostic(
                severity="info",
                code="missing-title",
                path=("title",),
                message="'title' is not defined",
            )
        )
    return warnings


def check_uuid_version_and_variant(uuid: str | None) -> list[Diagnostic]:
    """generic.md: the UUID's version and variant nibbles are meaningful."""
    if uuid is None:
        return []

    match = _UUID_RE.match(uuid)
    if match is None:
        # Malformed shape -- the schema pattern already reports that.
        return []

    warnings = []
    version = match.group("version")
    if version not in _UUID_VERSIONS:
        warnings.append(
            Diagnostic(
                severity="warning",
                code="uuid-unknown-version",
                path=("uuid",),
                message=(
                    f"UUID version nibble is {version!r}; expected one of "
                    f"1-8 (got the 13th character of {uuid!r})"
                ),
            )
        )

    variant = match.group("variant")
    if variant not in _UUID_VARIANTS:
        warnings.append(
            Diagnostic(
                severity="warning",
                code="uuid-unknown-variant",
                path=("uuid",),
                message=(
                    f"UUID variant nibble is {variant!r}; expected one of "
                    f"8, 9, a, b (got the 17th character of {uuid!r})"
                ),
            )
        )
    return warnings


def check_tags(tags: Sequence[str]) -> list[Diagnostic]:
    """
    generic.md accepts `tags` as a list or as a single comma-delimited
    string; a comma surviving inside a list entry means the string form
    was never split.
    """
    warnings = []
    for index, tag in enumerate(tags):
        if tag.strip() == "":
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="blank-tag",
                    path=("tags", index),
                    message="tag is empty or whitespace only",
                )
            )
        elif "," in tag:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="unsplit-tag-list",
                    path=("tags", index),
                    message=(
                        f"tag {tag!r} contains a comma; a comma-delimited "
                        f"string is only split when `tags` is written as a "
                        f"single string, not as a list"
                    ),
                )
            )
    return warnings


def check_stem_is_a_paragraph(stem: str) -> list[Diagnostic]:
    """generic.md: implementations SHOULD require the stem to be a paragraph."""
    if not stem.strip():
        return []

    for pattern, description in _NON_PARAGRAPH_STEM:
        if pattern.match(stem.lstrip("\n")):
            return [
                Diagnostic(
                    severity="warning",
                    code="stem-not-a-paragraph",
                    path=("stem",),
                    message=(
                        f"stem starts with what looks like {description}; "
                        f"it should be a paragraph of text"
                    ),
                )
            ]
    return []


def check_stem_ellipsis_expanded(stem: str) -> list[Diagnostic]:
    """
    generic.md: a stem of a single ellipsis MAY be replaced by a default
    statement for the question type -- flag the ones that never were.
    """
    if stem.strip() not in ("...", "…"):
        return []
    return [
        Diagnostic(
            severity="info",
            code="unexpanded-stem-ellipsis",
            path=("stem",),
            message=(
                "stem is a bare ellipsis; it was never replaced by a "
                "default statement for the question type"
            ),
        )
    ]


def check_locale_language_subtag(locale: str | None) -> list[Diagnostic]:
    """
    A well-formed tag can still name the wrong thing: this catches
    country codes written where a language belongs.
    """
    subtag = _language_subtag(locale)
    suggestion = _LOOKALIKE_LANGUAGE_SUBTAGS.get(subtag)
    if suggestion is None:
        return []
    return [
        Diagnostic(
            severity="info",
            code="locale-lookalike-language",
            path=("locale",),
            message=(
                f"{subtag!r} is not a valid ISO 639-1 language code; "
                f"did you mean {suggestion!r}?"
            ),
        )
    ]


# ----------------------------------------------------------------------
# choice rules (multiple-choice, multiple-selection, true-false, and the
# choice blanks of a fill-in question)
# ----------------------------------------------------------------------


def check_choice_feedback_and_comment(
    choices: Sequence[_choice.ScoredChoice | _choice.BooleanChoice | _choice.Statement],
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    multiple-choice.md, "Choices" (shared by multiple-selection and
    true-false): a choice's `feedback`/`comment`, if defined, must have
    at least one visible character -- the same rule
    `check_blank_text_field` applies to a question's own free-text
    fields, applied per choice instead.
    """
    warnings: list[Diagnostic] = []
    for index, choice in enumerate(choices):
        for field_name, code in (
            ("feedback", "blank-choice-feedback"),
            ("comment", "blank-choice-comment"),
        ):
            value = getattr(choice, field_name)
            if value is not None and value.strip() == "":
                warnings.append(
                    Diagnostic(
                        severity="warning",
                        code=code,
                        path=path + (index, field_name),
                        message=(
                            f"choice {field_name} is defined but has no "
                            f"visible characters"
                        ),
                    )
                )
    return warnings


def check_choice_ids_defined(
    choices: Sequence[_choice.ScoredChoice | _choice.BooleanChoice | _choice.Statement],
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    multiple-choice.md, "Choices": a choice SHOULD declare its own `id`
    rather than rely on one derived from its text -- a derived id is
    only as stable as the slugifier that produced it.
    """
    warnings: list[Diagnostic] = []
    for index, choice in enumerate(choices):
        if choice.id is None:
            warnings.append(
                Diagnostic(
                    severity="info",
                    code="missing-choice-id",
                    path=path + (index, "id"),
                    message=(
                        "choice has no explicit id; one will be derived "
                        "from its text"
                    ),
                )
            )
    return warnings


def check_choices_visually_identical(
    choices: Sequence[_choice.ScoredChoice | _choice.BooleanChoice | _choice.Statement],
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    multiple-choice.md, "Choices": two choices whose text renders alike
    but is written differently in source are indistinguishable to a
    reader -- the same comparison
    `check_ordering_visually_identical_lines` applies to ordering lines.
    """
    warnings: list[Diagnostic] = []
    seen: dict[str, tuple[int, str]] = {}
    for index, choice in enumerate(choices):
        key = _render_visual_key(choice.text)
        first = seen.get(key)
        if first is None:
            seen[key] = (index, choice.text)
            continue
        first_index, first_text = first
        if choice.text == first_text:
            continue  # an intentional repeat, not a same-render pair.
        warnings.append(
            Diagnostic(
                severity="info",
                code="visually-identical-choices",
                path=path + (index, "text"),
                message=(
                    f"choice text renders the same as choices[{first_index}] "
                    f"but is written differently in source"
                ),
            )
        )
    return warnings


def check_multiple_choice_answers(
    choices: Sequence[_choice.ScoredChoice],
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    multiple-choice.md: a question MAY mark any number of choices as
    correct, and typically marks exactly one -- more than one is unusual
    enough to flag (`multiple-choice-many-correct-choices`, `info`), but
    not a mistake. No correct choice at all more likely is one.

    Also used, via `mdq.models._fill_in.FillInQuestion.lint`, for a
    fill-in choice blank -- graded like multiple-choice, so the same
    rules apply (fill-in.md, "Additional Rules").
    """
    correct = [index for index, choice in enumerate(choices) if (choice.score or 0) >= 1]

    if not correct:
        return [
            Diagnostic(
                severity="info",
                code="multiple-choice-no-correct-choice",
                path=path,
                message="no choice has a score >= 1; the question has no correct answer",
            )
        ]

    warnings: list[Diagnostic] = []
    if len(correct) > 1:
        listed = ", ".join(str(index) for index in correct)
        warnings.append(
            Diagnostic(
                severity="info",
                code="multiple-choice-many-correct-choices",
                path=path,
                message=(
                    f"choices {listed} all have a score >= 1; a question MAY "
                    f"mark any number of choices as correct, but the student "
                    f"still picks a single one"
                ),
            )
        )

    if len(correct) == len(choices):
        warnings.append(
            Diagnostic(
                severity="info",
                code="all-choices-correct",
                path=path,
                message="every choice has a score >= 1; the question has no wrong answer",
            )
        )
    return warnings


def check_multiple_selection_answers(
    choices: Sequence[_choice.BooleanChoice],
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    multiple-selection.md: a well-formed question mixes correct and
    incorrect choices -- one with none correct has nothing to select,
    and one where every choice is correct has nothing to leave unchecked.
    """
    warnings: list[Diagnostic] = []
    correct = [index for index, choice in enumerate(choices) if choice.correct]

    if not correct:
        warnings.append(
            Diagnostic(
                severity="info",
                code="no-correct-choice",
                path=path,
                message="no choice is correct; the question has nothing to select",
            )
        )
    elif len(correct) == len(choices):
        warnings.append(
            Diagnostic(
                severity="info",
                code="all-choices-correct",
                path=path,
                message="every choice is correct; the question has nothing to leave unchecked",
            )
        )
    return warnings


def check_true_false_markers(
    choices: Sequence[_choice.Statement],
    locale: str | None,
) -> list[Diagnostic]:
    """
    true-false.md: PROVISIONAL letters SHOULD warn, since a later
    revision may reassign them; implementations MAY warn when the letter
    doesn't match the question's locale; and `S` under `locale: id`
    SHOULD get an escalated warning, since it reads as true globally but
    is the initial letter of Indonesian "salah" (false) -- a document
    that meant false there is silently graded true, not just mismatched.

    The reserved `X`/`x` marker is rejected at the model layer
    (`reserved-true-false-marker`), so it never reaches here.
    """
    warnings: list[Diagnostic] = []
    language = _language_subtag(locale)
    expected = _LOCALE_MARKERS.get(language)

    for index, choice in enumerate(choices):
        marker = choice.marker
        if marker is None:
            continue

        upper = marker.upper()
        if language == "id" and upper == "S":
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="false-friend-true-false-marker",
                    path=("choices", index, "marker"),
                    message=(
                        f"{marker!r} means true (see true-false.md), but is "
                        f"the initial letter of Indonesian \"salah\" "
                        f"(false); if this choice was meant to be false, "
                        f"use 'F' instead"
                    ),
                )
            )
            continue

        if upper not in TRUE_MARKERS and upper not in FALSE_MARKERS:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="provisional-true-false-marker",
                    path=("choices", index, "marker"),
                    message=(
                        f"{marker!r} is a PROVISIONAL letter: it reads as "
                        f"true today, but a future revision of the spec may "
                        f"reassign it"
                    ),
                )
            )
            continue

        if expected is None:
            continue

        expected_true, expected_false = expected
        wanted = expected_true if upper in TRUE_MARKERS else expected_false
        if upper != wanted:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="locale-mismatched-true-false-marker",
                    path=("choices", index, "marker"),
                    message=(
                        f"{marker!r} is unusual for locale {locale!r}, which "
                        f"normally writes {expected_true!r}/{expected_false!r}"
                    ),
                )
            )

    return warnings


def check_true_false_marker_nfc(choices: Sequence[_choice.Statement]) -> list[Diagnostic]:
    """
    true-false.md:219: a marker is one code point by the field's own
    shape, but that code point should also be its own NFC form -- one
    that normalizes to something else (e.g. U+212B ANGSTROM SIGN, which
    NFC turns into U+00C5) is easy to type by mistake and renders
    differently than intended.
    """
    warnings: list[Diagnostic] = []
    for index, choice in enumerate(choices):
        marker = choice.marker
        if marker is None:
            continue
        if unicodedata.normalize("NFC", marker) != marker:
            warnings.append(
                Diagnostic(
                    severity="info",
                    code="non-nfc-true-false-marker",
                    path=("choices", index, "marker"),
                    message=(
                        f"{marker!r} is not its own NFC form "
                        f"({unicodedata.normalize('NFC', marker)!r})"
                    ),
                )
            )
    return warnings


def check_true_false_uniform_answers(choices: Sequence[_choice.Statement]) -> list[Diagnostic]:
    """
    true-false.md:218: a question whose statements are all true or all
    false is usually an authoring mistake -- a well-formed question
    presents a mix for the student to judge.
    """
    if not choices:
        return []
    values = {choice.correct for choice in choices}
    if len(values) > 1:
        return []
    return [
        Diagnostic(
            severity="info",
            code="uniform-true-false-answers",
            path=("choices",),
            message=(
                f"every statement is {'true' if choices[0].correct else 'false'}; "
                f"a true/false question should mix true and false statements"
            ),
        )
    ]


# ----------------------------------------------------------------------
# per-type rules
# ----------------------------------------------------------------------
def check_highlight_language(highlight: str | None) -> list[Diagnostic]:
    """
    essay.md:89, ordering.md:343: `highlight` SHOULD name a language a
    highlighter can recognize. Any alias of a Pygments lexer is
    accepted as the reference list (`pygments.lexers.
    find_lexer_class_by_name`) -- `pygments` is a direct dependency for
    exactly this check.
    """
    if highlight is None:
        return []
    try:
        find_lexer_class_by_name(highlight)
    except ClassNotFound:
        return [
            Diagnostic(
                severity="info",
                code="unknown-highlight-language",
                path=("highlight",),
                message=(
                    f"{highlight!r} is not a recognized Pygments lexer "
                    f"alias, so a highlighter would not know this language"
                ),
            )
        ]
    return []


def check_essay_highlight(input_kind: str, highlight: str | None) -> list[Diagnostic]:
    """essay.md: `highlight` is ignored unless the input is `code`."""
    if highlight is not None and input_kind != "code":
        return [
            Diagnostic(
                severity="warning",
                code="ignored-highlight",
                path=("highlight",),
                message=(
                    f"'highlight' is ignored because input is "
                    f"{input_kind!r}, not 'code'"
                ),
            )
        ]

    if input_kind == "code" and highlight is None:
        return [
            Diagnostic(
                severity="info",
                code="code-input-without-highlight",
                path=("input",),
                message=(
                    "input is 'code' but no 'highlight' language is given, "
                    "so the editor cannot highlight the answer"
                ),
            )
        ]
    if input_kind == "code" and highlight is not None:
        return check_highlight_language(highlight)
    return []


def check_missing_answer_key(answer_key: str | None) -> list[Diagnostic]:
    """essay.md:91: `answerKey` SHOULD be defined, for a human grader's benefit."""
    if answer_key is not None:
        return []
    return [
        Diagnostic(
            severity="info",
            code="missing-answer-key",
            path=("answerKey",),
            message="'answerKey' is not defined",
        )
    ]


def check_short_answer(
    *,
    regex: str | None,
    one_of: list[str] | None,
    accept: "list[_text.AnswerPattern] | None",
    reject: "list[_text.AnswerPattern] | None" = None,
    open_ended: bool,
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    short-answer.md: `regex` takes precedence over the body's answers.
    A question with none of `regex`/`oneOf`/`accept` and no `openEnded`
    flag cannot be graded either way.

    Whether `regex` and every `/`-delimited pattern in `accept`/`reject`/
    `preAccept`/`preReject` compile is a model error now
    (`invalid-regex` -- dev/specs/to-do/lint-on-models.md), not checked
    here.
    """
    warnings: list[Diagnostic] = []

    if regex is not None:
        if one_of:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="shadowed-answers",
                    path=path + ("oneOf",),
                    message=(
                        "'regex' takes precedence, so these accepted "
                        "answers are never used"
                    ),
                )
            )

        warnings.extend(_check_redundant_regex_anchor(regex, path + ("regex",)))
        warnings.extend(_check_ignored_regex_flags(regex, path + ("regex",)))

    if not open_ended and regex is None and not one_of and not accept:
        warnings.append(
            Diagnostic(
                severity="warning",
                code="short-answer-not-gradable",
                path=path,
                message=(
                    "no 'accept' patterns, no 'oneOf' answers and no 'regex' "
                    "are given, but the question is not marked 'openEnded'; "
                    "nothing can grade it"
                ),
            )
        )

    for index, pattern in enumerate(accept or []):
        if pattern.pattern.strip() == "*":
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="accept-wildcard",
                    path=path + ("accept", index),
                    message=(
                        "'*' accepts every response, defeating the purpose "
                        "of an answer key"
                    ),
                )
            )
        warnings.extend(_check_redundant_regex_anchor(pattern.pattern, path + ("accept", index)))
        warnings.extend(_check_ignored_regex_flags(pattern.pattern, path + ("accept", index)))

    reject_list = reject or []
    last_index = len(reject_list) - 1
    for index, pattern in enumerate(reject_list):
        if pattern.pattern.strip() == "*" and index != last_index:
            warnings.append(
                Diagnostic(
                    severity="info",
                    code="unreachable-reject",
                    path=path + ("reject", index),
                    message=(
                        f"'*' rejects every response; reject[{index + 1}:] "
                        f"is never reached"
                    ),
                )
            )
        warnings.extend(_check_redundant_regex_anchor(pattern.pattern, path + ("reject", index)))
        warnings.extend(_check_ignored_regex_flags(pattern.pattern, path + ("reject", index)))

    return warnings


def _check_redundant_regex_anchor(
    pattern: str, path: tuple[Union[str, int], ...]
) -> list[Diagnostic]:
    """
    short-answer.md, "Regex flags": a leading `^` is implicit unless the
    `f` flag is set, and a trailing `$` is implicit unless `f` or `b` is
    set. A `$` preceded by an odd number of backslashes is a literal.
    Only a `/`-delimited entry is a regex; the `regex` field may be raw.
    """
    is_field = path[-1] == "regex"
    if not is_field and not pattern.strip().startswith("/"):
        return []
    try:
        body, raw_flags = parse_regex(pattern)
    except InvalidRegexError:
        return []
    leading = body.startswith("^") and "f" not in raw_flags
    trailing = False
    if body.endswith("$") and not {"f", "b"} & set(raw_flags):
        backslashes = len(body) - 1 - len(body[:-1].rstrip("\\"))
        trailing = backslashes % 2 == 0
    if not (leading or trailing):
        return []
    return [
        Diagnostic(
            severity="info",
            code="redundant-regex-anchor",
            path=path,
            message=(
                "matching is already anchored here, so a leading '^' or "
                "trailing '$' is redundant"
            ),
        )
    ]


def _check_ignored_regex_flags(
    pattern: str, path: tuple[Union[str, int], ...]
) -> list[Diagnostic]:
    """
    short-answer.md:385: `m`, `g`, `s`, `u`, `v`, `y` and `d` are accepted
    for compatibility but have no effect (see [regex flags](regex-flags)).
    Only a delimited (`/.../flags`) pattern carries flags at all.
    """
    if not pattern.strip().startswith("/"):
        return []
    try:
        _, raw_flags = parse_regex(pattern)
    except InvalidRegexError:
        return []
    ignored = sorted(set(raw_flags) & IGNORED_FLAGS)
    if not ignored:
        return []
    flags_text = ", ".join(repr(flag) for flag in ignored)
    return [
        Diagnostic(
            severity="info",
            code="ignored-regex-flag",
            path=path,
            message=f"flag(s) {flags_text} are accepted but have no effect on matching",
        )
    ]


_DOMAIN_RANK: dict[str, int] = {"integer": 0, "fraction": 1, "decimal": 2}


def _accepted_numeric_domains(
    answer: int | float | str, tolerance: "_numeric.Tolerance | None"
) -> set[str]:
    """
    numeric.md, "Number type/domain": the declared domains that do not
    contradict the answer. That is the higher of the answer's domain and
    the absolute tolerance's (integer < fraction < decimal).

    An integer answer also agrees with `fraction` (numeric.md, "Answer
    representation": with `domain: fraction`, the answer is a fraction
    string or an integer). A number that is not whole is a decimal only.
    """
    own: set[str] = {_infer_numeric_domain(answer)}
    if own == {"integer"}:
        own.add("fraction")
    if tolerance is None or tolerance.absolute is None:
        return own
    tolerance_domain = _infer_numeric_domain(tolerance.absolute)
    if _DOMAIN_RANK[tolerance_domain] > min(_DOMAIN_RANK[d] for d in own):
        return {tolerance_domain}
    return own


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
    holds a `/` (a fraction) or a `.` (a decimal) or neither (an
    integer); a number is an integer when it has no fractional part,
    decimal otherwise. The parser keeps a whole decimal such as `2.0`
    as a string, so a whole number here was not written as a decimal
    in Markdown.
    """
    if isinstance(answer, str):
        text = answer.strip()
        if "/" in text:
            return "fraction"
        if "." in text:
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
) -> list[Diagnostic]:
    """
    numeric.md: the domain is inferred from the answer's representation
    when not declared, so a declared domain that contradicts the answer
    is a mistake; and a relative tolerance around zero can never widen
    the accepted range.
    """
    warnings: list[Diagnostic] = []
    inferred_domain = _infer_numeric_domain(answer)
    accepted_domains = _accepted_numeric_domains(answer, tolerance)
    # A string answer is already grammar-validated, so `Fraction` accepts it.
    value: Fraction | float = Fraction(answer) if isinstance(answer, str) else answer

    if domain == "integer" and value != int(value):
        warnings.append(
            Diagnostic(
                severity="warning",
                code="answer-outside-domain",
                path=path + ("answer",),
                message=(
                    f"domain is 'integer' but the answer {answer!r} is not a "
                    f"whole number"
                ),
            )
        )

    if domain is not None and domain not in accepted_domains:
        warnings.append(
            Diagnostic(
                severity="info",
                code="domain-mismatch",
                path=path + ("domain",),
                message=(
                    f"domain is {domain!r}, but the answer {answer!r} is "
                    f"written as a {' or '.join(sorted(accepted_domains))} value"
                ),
            )
        )

    if tolerance is None and inferred_domain in ("decimal", "fraction"):
        warnings.append(
            Diagnostic(
                severity="info",
                code="missing-tolerance",
                path=path + ("tolerance",),
                message=(
                    f"the answer {answer!r} is a {inferred_domain} value, but "
                    f"no tolerance is given; an exact comparison rarely "
                    f"matches a typed response"
                ),
            )
        )

    if tolerance is not None:
        relative = tolerance.relative
        if relative is not None and relative > 0 and value == 0:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="relative-tolerance-around-zero",
                    path=path + ("tolerance", "relative"),
                    message=(
                        "a relative tolerance is computed as answer x "
                        "relative, which is 0 when the answer is 0; only an "
                        "exact 0 would be accepted"
                    ),
                )
            )

        if relative is not None and relative > 1:
            warnings.append(
                Diagnostic(
                    severity="info",
                    code="relative-tolerance-over-one",
                    path=path + ("tolerance", "relative"),
                    message=(
                        f"a relative tolerance of {relative!r} means "
                        f"{relative * 100:g}%; it is written as a fraction, "
                        f"not a percentage"
                    ),
                )
            )

    effective_domain = _effective_numeric_domain(answer, domain, tolerance)
    if decimal_places is not None and effective_domain != "decimal":
        source = "" if domain is not None else " (inferred from the answer)"
        warnings.append(
            Diagnostic(
                severity="info",
                code="ignored-decimal-places",
                path=path + ("decimalPlaces",),
                message=(
                    f"'decimalPlaces' is ignored when domain is "
                    f"{effective_domain!r}{source}"
                ),
            )
        )

    return warnings


def check_exam_without_questions(
    questions: Sequence[object], path: tuple[Union[str, int], ...]
) -> list[Diagnostic]:
    """
    exam.md: an exam MAY contain zero questions, but SHOULD warn -- an
    exam with nothing to answer is a draft, not an assessment.
    """
    if questions:
        return []
    return [
        Diagnostic(
            severity="warning",
            code="exam-without-questions",
            path=path,
            message="the exam contains no questions, so it cannot be answered",
        )
    ]


def check_include_query(
    query: str, path: tuple[Union[str, int], ...]
) -> list[Diagnostic]:
    """exam.md, "Include all": a query should follow the recommended language."""
    if is_standard_query(query):
        return []
    return [
        Diagnostic(
            severity="warning",
            code="nonstandard-include-query",
            path=path,
            message=f"the query {query!r} does not follow the recommended query language",
        )
    ]


def check_undeclared_id_after_include_all(
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    exam.md, "Question ids": the derived id of a question after an
    `include-all` changes with the questions the query adds.
    """
    return [
        Diagnostic(
            severity="warning",
            code="undeclared-id-after-include-all",
            path=path,
            message=(
                "the derived id of a question after an 'include-all' changes "
                "with the questions the query adds; declare an 'id'"
            ),
        )
    ]


# ----------------------------------------------------------------------
# ordering
# ----------------------------------------------------------------------


def check_ordering_highlight(question: _ordering.OrderingQuestion) -> list[Diagnostic]:
    """ordering.md: `highlight` must be omitted unless `content` is 'code'."""
    if question.highlight is not None and question.content != "code":
        return [
            Diagnostic(
                severity="warning",
                code="ignored-highlight",
                path=("highlight",),
                message=(
                    f"'highlight' is ignored because content is "
                    f"{question.content!r}, not 'code'"
                ),
            )
        ]
    if question.content == "code" and question.highlight is not None:
        return check_highlight_language(question.highlight)
    return []


def check_ordering_duplicate_alternatives(
    question: _ordering.OrderingQuestion,
) -> list[Diagnostic]:
    """
    ordering.md#acceptedrejected-answers: a question SHOULD NOT declare
    two `accept` sections, or two `reject` sections, whose lines are the
    same once fully normalized -- every entry of `normalizations`, plus
    whatever `indentation` implies. An accept/reject pair is a model
    error (`accept-reject-overlap`) and never reaches this check.
    """
    warnings: list[Diagnostic] = []
    for section in ("accept", "reject"):
        seen: dict[tuple, tuple[str, int]] = {}
        for index, alt in enumerate(getattr(question, section)):
            key = question.comparison_key(alt.lines)
            first = seen.get(key)
            if first is not None:
                first_section, first_index = first
                warnings.append(
                    Diagnostic(
                        severity="warning",
                        code="duplicate-alternative-lines",
                        path=(section, index, "lines"),
                        message=(
                            f"{section}[{index}] holds the same lines as "
                            f"{first_section}[{first_index}], once fully "
                            f"normalized"
                        ),
                    )
                )
            else:
                seen[key] = (section, index)
    return warnings


def check_ordering_accept_repeats_answer_key(
    question: _ordering.OrderingQuestion,
) -> list[Diagnostic]:
    """ordering.md#acceptedrejected-answers: `accept` SHOULD NOT repeat `lines`."""
    answer_key = question.comparison_key(question.lines)
    warnings = []
    for index, alt in enumerate(question.accept):
        if question.comparison_key(alt.lines) == answer_key:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="accept-repeats-answer-key",
                    path=("accept", index, "lines"),
                    message=(
                        f"accept[{index}] repeats the [ordering] block's own "
                        f"lines, once fully normalized"
                    ),
                )
            )
    return warnings


def check_ordering_redundant_strict_indentation(
    question: _ordering.OrderingQuestion,
) -> list[Diagnostic]:
    """
    ordering.md#indentation[^8]: `dedent` flattens every line to level 0,
    so `indentation: "strict"` has nothing left to compare.
    `indentation: "lenient"` implies `dedent` and therefore never
    combines with `"strict"` in the first place, so only an explicit
    `dedent` in `normalizations` can trigger this.
    """
    if question.indentation != "strict":
        return []
    if "dedent" not in question.effective_normalizations():
        return []
    return [
        Diagnostic(
            severity="warning",
            code="redundant-strict-indentation",
            path=("indentation",),
            message=(
                "indentation is 'strict' but 'dedent' is normalized, which "
                "flattens every line to level 0, so there is nothing left "
                "for 'strict' to compare"
            ),
        )
    ]


def check_ordering_blank_lines(question: _ordering.OrderingQuestion) -> list[Diagnostic]:
    """
    ordering.md#additional-rules: a blank `lines`/`extra` entry should
    only appear when `skip-blanks` is normalized -- otherwise it counts
    when comparing a response.
    """
    if "skip-blanks" in question.effective_normalizations():
        return []

    warnings = []
    for field_name in ("lines", "extra"):
        for index, (_, text) in enumerate(getattr(question, field_name)):
            if text.strip() == "":
                warnings.append(
                    Diagnostic(
                        severity="info",
                        code="blank-ordering-line",
                        path=(field_name, index),
                        message=(
                            "line is blank, and 'skip-blanks' is not "
                            "normalized, so it counts when comparing a "
                            "response"
                        ),
                    )
                )
    return warnings


def check_ordering_reject_without_feedback(
    question: _ordering.OrderingQuestion,
) -> list[Diagnostic]:
    """ordering.md#feedback: a `reject` section SHOULD declare feedback."""
    warnings = []
    for index, alt in enumerate(question.reject):
        if not alt.feedback or not alt.feedback.strip():
            warnings.append(
                Diagnostic(
                    severity="info",
                    code="reject-without-feedback",
                    path=("reject", index),
                    message=(
                        f"reject[{index}] declares no feedback, which is its "
                        f"whole purpose"
                    ),
                )
            )
    return warnings


def _render_visual_key(text: str) -> str:
    """How `text` renders, for comparing lines/choices as a reader would."""
    return _RENDER_MD.renderInline(text).strip()


def check_ordering_visually_identical_lines(
    question: _ordering.OrderingQuestion,
) -> list[Diagnostic]:
    """
    ordering.md#body: two `lines`/`extra` entries at the same
    indentation level should not render alike while differing in their
    raw markdown source -- a student ordering the rendered text cannot
    tell such a pair apart. Only meaningful for `content: "text"`: a
    code block's content is shown verbatim, never rendered.
    """
    if question.content != "text":
        return []

    warnings: list[Diagnostic] = []
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
            warnings.append(
                Diagnostic(
                    severity="info",
                    code="visually-identical-lines",
                    path=(field_name, index),
                    message=(
                        f"line renders the same as {first_field}[{first_index}] "
                        f"but is written differently in source; a student "
                        f"ordering the rendered text cannot tell them apart"
                    ),
                )
            )
    return warnings
