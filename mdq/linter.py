"""
Lint checks for MDQ question documents that go beyond what JSON Schema
can express -- cross-field constraints, "not just whitespace" checks, and
the like.

These implement the SHOULD/MAY-level rules the specification leaves to
implementations (see docs/question-types/): a compliant parser is free to
accept these documents, but an author almost never wants them. They run
on documents that have already been (or are being) validated against
their JSON Schema, so the checks here are defensive about malformed input
(wrong types, missing fields) -- reporting that is the schema validator's
job, not the linter's.

Every rule always runs, and each is tagged with the severity of what it
found:

* ``warning`` -- the document is probably wrong: a dead field, an
  ungradable answer key, a duplicate id, a tolerance that can never
  match.
* ``info`` -- advisory/stylistic rules where the specification says an
  implementation MAY complain: redundant regex anchors, no-op fields,
  locale mismatches.

One ``warning``-severity rule, ``unknown-frontmatter-key``, is not
implemented here: an already-parsed document has no way to see a
frontmatter key the parser dropped while building it. It is instead
emitted by ``mdq.parser`` (``parse_question``/``parse_exam``/
``parse_any``, via an optional ``warnings`` sink) for every frontmatter
key it does not recognize -- a typo like ``auther:``, or a field that
never existed -- and merged into `mdq.loading`'s diagnostics ahead of
the ones ``lint_document`` produces here.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterator, TypeIs, Union

from ._diagnostics import Diagnostic
from .regex import InvalidRegexError, RegexPattern

# question-base.yaml fields that are just `type: string` -- so an
# empty-but-technically-non-empty string like "   " (or even "" where
# minLength isn't set) passes JSON Schema but isn't a meaningful value.
_TEXT_FIELDS = (
    "title",
    "author",
    "preamble",
    "stem",
    "epilogue",
    "comment",
    "answerKey",
)

_CHOICE_QUESTION_TYPES = ("true-false", "multiple-choice", "multiple-selection")

# true-false.md: `T`, `V`, `S` and the CJK characters 对/真 always mean
# true; `F` and the CJK characters 错/偽 always mean false. Any other
# letter is PROVISIONAL -- it reads as true today, but the document says
# compliant implementations SHOULD warn, since a future revision of the
# spec may reassign it.
_TRUE_MARKERS = frozenset("TVS对真")
_FALSE_MARKERS = frozenset("F错偽")
# `X` is the multiple-selection marker and never appears in true-false.
_RESERVED_MARKERS = frozenset("X")

# docs/references/true-false-spellings.md, keyed by primary language
# subtag: the letters an author writing in that language would reach for.
_LOCALE_MARKERS = {
    "en": ("T", "F"),  # true / false
    "pt": ("V", "F"),  # verdadeiro / falso
    "es": ("V", "F"),  # verdadero / falso
}

# generic.md [^4]: `locale` must be a BCP 47 language tag. This is the
# common `language[-Script][-REGION]` shape, which is what questions
# actually use; a tag with private-use or extension subtags is rarer than
# a language *name* written where a tag belongs, which is what this
# catches.
_BCP47_RE = re.compile(r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?$")

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
    (re.compile(r"^\s*\d+[.)]\s"), "an ordered list"),
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

#: `[^blank-id]` markers, as written in a fill-in stem.
_BLANK_MARKER_RE = re.compile(r"\[\^([^\]]+)\]")

#: Runs of whitespace outside of a code span. Splitting on backticks
#: first keeps `foo bar` and `foo  bar` distinct while still collapsing
#: plain prose (multiple-choice.md, "Choices").
_CODE_SPAN_RE = re.compile(r"(`+[^`]*`+)")
_WHITESPACE_RE = re.compile(r"\s+")

__all__ = [
    "lint_document",
]


def lint_document(
    document: dict[str, Any],
    question_type: str,
) -> list[Diagnostic]:
    """
    Run every lint check applicable to `question_type` and return the
    resulting diagnostics (empty if none).

    Every rule always runs; what used to be the ``strict``-only rules
    (see the module docstring) simply report at ``info`` instead of
    ``warning`` rather than being skipped.
    """
    diagnostics: list[Diagnostic] = []

    # -- checks that apply to every question type ----------------------
    diagnostics.extend(_check_text_fields_not_blank(document))
    diagnostics.extend(_check_uuid_version_and_variant(document))
    diagnostics.extend(_check_tags(document))
    diagnostics.extend(_check_locale_is_well_formed(document))
    diagnostics.extend(_check_stem_is_a_paragraph(document))
    diagnostics.extend(_check_stem_ellipsis_expanded(document))
    diagnostics.extend(_check_locale_language_subtag(document))

    # -- per-type checks -----------------------------------------------
    if question_type in _CHOICE_QUESTION_TYPES:
        diagnostics.extend(_check_choices(document, ("choices",)))

    if question_type == "multiple-choice":
        diagnostics.extend(_check_multiple_choice_answers(document, ("choices",)))

    if question_type == "true-false":
        diagnostics.extend(_check_true_false_markers(document))

    if question_type == "essay":
        diagnostics.extend(_check_essay_highlight(document))

    if question_type == "short-answer":
        diagnostics.extend(_check_short_answer(document, ()))

    if question_type == "numeric":
        diagnostics.extend(_check_numeric(document, ()))

    if question_type == "fill-in":
        diagnostics.extend(_check_fill_in(document))

    if question_type == "exam":
        diagnostics.extend(_check_exam(document))

    return diagnostics


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _is_number(value: object) -> TypeIs[int | float]:
    """JSON numbers, excluding bools (which are ints in Python)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _visual_key(text: str) -> str:
    """
    Normalize `text` the way a Markdown renderer would, for the
    "visually identical when rendered to HTML" check in
    multiple-choice.md.

    Whitespace runs collapse to a single space in prose, but not inside
    code spans -- which is exactly what makes ``foo bar``/``foo  bar``
    equivalent while `` `foo bar` ``/`` `foo  bar` `` stay distinct.
    """
    parts = _CODE_SPAN_RE.split(text)
    # Odd indices are the captured code spans; leave those untouched.
    normalized = [
        part if index % 2 else _WHITESPACE_RE.sub(" ", part)
        for index, part in enumerate(parts)
    ]
    return unicodedata.normalize("NFC", "".join(normalized)).strip()


def _iter_choices(container: Any) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(index, choice)`` for every dict in a choices list."""
    if not isinstance(container, list):
        return
    for index, choice in enumerate(container):
        if isinstance(choice, dict):
            yield index, choice


def _language_subtag(document: dict[str, Any]) -> str:
    locale = document.get("locale")
    if not isinstance(locale, str):
        return ""
    return locale.split("-")[0].lower()


# ----------------------------------------------------------------------
# common rules
# ----------------------------------------------------------------------
def _check_text_fields_not_blank(document: dict[str, Any]) -> list[Diagnostic]:
    """
    Free-text fields, if defined, must have at least one visible
    (non-whitespace) character.
    """
    warnings = []
    for field_name in _TEXT_FIELDS:
        value = document.get(field_name)
        if value is None or not isinstance(value, str):
            # Missing is fine (they're optional, except stem which the
            # schema already requires); wrong type is the schema's job to
            # flag, not the linter's.
            continue
        if value.strip() == "":
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="blank-text-field",
                    path=(field_name,),
                    message=f"'{field_name}' is defined but has no visible characters",
                )
            )
    return warnings


def _check_uuid_version_and_variant(document: dict[str, Any]) -> list[Diagnostic]:
    """generic.md: the UUID's version and variant nibbles are meaningful."""
    value = document.get("uuid")
    if not isinstance(value, str):
        return []

    match = _UUID_RE.match(value)
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
                    f"1-8 (got the 13th character of {value!r})"
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
                    f"8, 9, a, b (got the 17th character of {value!r})"
                ),
            )
        )
    return warnings


def _check_tags(document: dict[str, Any]) -> list[Diagnostic]:
    """
    generic.md accepts `tags` as a list or as a single comma-delimited
    string; a comma surviving inside a list entry means the string form
    was never split.
    """
    tags = document.get("tags")
    if not isinstance(tags, list):
        return []

    warnings = []
    for index, tag in enumerate(tags):
        if not isinstance(tag, str):
            continue
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


def _check_stem_is_a_paragraph(document: dict[str, Any]) -> list[Diagnostic]:
    """generic.md: implementations SHOULD require the stem to be a paragraph."""
    stem = document.get("stem")
    if not isinstance(stem, str) or not stem.strip():
        return []

    for pattern, description in _NON_PARAGRAPH_STEM:
        if pattern.match(stem.lstrip("\n")):
            return [
                Diagnostic(
                    severity="info",
                    code="stem-not-a-paragraph",
                    path=("stem",),
                    message=(
                        f"stem starts with what looks like {description}; "
                        f"it should be a paragraph of text"
                    ),
                )
            ]
    return []


def _check_stem_ellipsis_expanded(document: dict[str, Any]) -> list[Diagnostic]:
    """
    generic.md: a stem of a single ellipsis MAY be replaced by a default
    statement for the question type -- flag the ones that never were.
    """
    stem = document.get("stem")
    if not isinstance(stem, str):
        return []
    if stem.strip() in ("...", "…"):
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
    return []


def _check_locale_is_well_formed(document: dict[str, Any]) -> list[Diagnostic]:
    """generic.md [^4]: `locale` must be a valid BCP 47 language tag."""
    locale = document.get("locale")
    if not isinstance(locale, str) or _BCP47_RE.match(locale):
        return []
    return [
        Diagnostic(
            severity="warning",
            code="malformed-locale",
            path=("locale",),
            message=(
                f"{locale!r} is not a BCP 47 language tag; expected a form "
                f"like 'en', 'pt-BR', or 'zh-Hans-CN'"
            ),
        )
    ]


def _check_locale_language_subtag(document: dict[str, Any]) -> list[Diagnostic]:
    """
    A well-formed tag can still name the wrong thing: this catches
    country codes written where a language belongs.
    """
    subtag = _language_subtag(document)
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


def _check_choices(
    document: dict[str, Any],
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    multiple-choice.md, "Choices": ids and texts must each be unique, no
    text may be empty, and implementations MAY reject texts that differ
    in source but render identically.
    """
    warnings: list[Diagnostic] = []
    # `document` is the question, or one blank of a fill-in question;
    # either way the choices live under "choices". `path` only says where
    # to point the warnings.
    choices = document.get("choices")
    if not isinstance(choices, list):
        return warnings

    seen_ids: dict[str, int] = {}
    seen_texts: dict[str, int] = {}
    seen_visuals: dict[str, int] = {}

    for index, choice in _iter_choices(choices):
        choice_id = choice.get("id")
        if isinstance(choice_id, str):
            first_index = seen_ids.get(choice_id)
            if first_index is not None:
                warnings.append(
                    Diagnostic(
                        severity="warning",
                        code="duplicate-choice-id",
                        path=path + (index, "id"),
                        message=(
                            f"choice id {choice_id!r} is already used by "
                            f"choices[{first_index}]"
                        ),
                    )
                )
            else:
                seen_ids[choice_id] = index

        text = choice.get("text")
        if not isinstance(text, str):
            continue

        if text.strip() == "":
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="blank-choice-text",
                    path=path + (index, "text"),
                    message="choice text has no visible characters",
                )
            )
            continue

        first_index = seen_texts.get(text)
        if first_index is not None:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="duplicate-choice-text",
                    path=path + (index, "text"),
                    message=(
                        f"choice text {text!r} is already used by "
                        f"choices[{first_index}]"
                    ),
                )
            )
            continue
        seen_texts[text] = index

        visual = _visual_key(text)
        first_index = seen_visuals.get(visual)
        if first_index is not None:
            warnings.append(
                Diagnostic(
                    severity="info",
                    code="visually-identical-choice-text",
                    path=path + (index, "text"),
                    message=(
                        f"choice text {text!r} differs from choices"
                        f"[{first_index}] only in whitespace, so the two "
                        f"render identically"
                    ),
                )
            )
        else:
            seen_visuals[visual] = index

    return warnings


def _check_multiple_choice_answers(
    document: dict[str, Any],
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    multiple-choice.md: exactly one choice should carry full credit --
    the student picks a single radio button.
    """
    choices = document.get("choices")
    if not isinstance(choices, list):
        return []

    correct = [
        index
        for index, choice in _iter_choices(choices)
        if _is_number(choice.get("score")) and choice["score"] >= 1
    ]

    if not correct:
        return [
            Diagnostic(
                severity="warning",
                code="multiple-choice-no-correct-choice",
                path=path,
                message="no choice has a score >= 1; the question has no correct answer",
            )
        ]

    if len(correct) > 1:
        listed = ", ".join(str(index) for index in correct)
        return [
            Diagnostic(
                severity="warning",
                code="multiple-choice-many-correct-choices",
                path=path,
                message=(
                    f"choices {listed} all have a score >= 1, but only one "
                    f"can be selected; use multiple-selection instead"
                ),
            )
        ]
    return []


def _check_true_false_markers(
    document: dict[str, Any],
) -> list[Diagnostic]:
    """
    true-false.md: PROVISIONAL letters SHOULD warn, since a later
    revision may reassign them; implementations MAY warn when the letter
    doesn't match the question's locale; and `S` under `locale: id`
    SHOULD get an escalated warning, since it reads as true globally but
    is the initial letter of Indonesian "salah" (false) -- a document
    that meant false there is silently graded true, not just mismatched.
    """
    choices = document.get("choices")
    if not isinstance(choices, list):
        return []

    warnings: list[Diagnostic] = []
    language = _language_subtag(document)
    expected = _LOCALE_MARKERS.get(language)

    for index, choice in _iter_choices(choices):
        marker = choice.get("marker")
        if not isinstance(marker, str) or len(marker) != 1:
            continue

        upper = marker.upper()
        if upper in _RESERVED_MARKERS:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="reserved-true-false-marker",
                    path=("choices", index, "marker"),
                    message=(
                        f"{marker!r} marks a selected multiple-selection "
                        f"choice and has no true/false meaning"
                    ),
                )
            )
            continue

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

        if upper not in _TRUE_MARKERS and upper not in _FALSE_MARKERS:
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
        wanted = expected_true if upper in _TRUE_MARKERS else expected_false
        if upper != wanted:
            warnings.append(
                Diagnostic(
                    severity="info",
                    code="locale-mismatched-true-false-marker",
                    path=("choices", index, "marker"),
                    message=(
                        f"{marker!r} is unusual for locale "
                        f"{document.get('locale')!r}, which normally writes "
                        f"{expected_true!r}/{expected_false!r}"
                    ),
                )
            )

    return warnings


# ----------------------------------------------------------------------
# per-type rules
# ----------------------------------------------------------------------
def _check_essay_highlight(document: dict[str, Any]) -> list[Diagnostic]:
    """essay.md: `highlight` is ignored unless the input is `code`."""
    highlight = document.get("highlight")
    input_kind = document.get("input", "text")

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
                severity="warning",
                code="code-input-without-highlight",
                path=("input",),
                message=(
                    "input is 'code' but no 'highlight' language is given, "
                    "so the editor cannot highlight the answer"
                ),
            )
        ]
    return []


def _check_short_answer(
    document: dict[str, Any],
    path: tuple[Union[str, int], ...],
) -> list[Diagnostic]:
    """
    short-answer.md: `regex` takes precedence over the body's answers, is
    applied as a full match, and must actually compile. A question with
    none of `regex`/`oneOf` and no `openEnded` flag cannot be graded
    either way.
    """
    warnings: list[Diagnostic] = []
    regex = document.get("regex")
    accepted = document.get("oneOf")
    open_ended = document.get("openEnded", False)

    for key in ("accept", "reject", "preAccept", "preReject"):
        warnings.extend(_check_patterns(document.get(key), path + (key,)))

    if isinstance(regex, str):
        try:
            re.compile(regex)
        except re.error as exc:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="invalid-regex",
                    path=path + ("regex",),
                    message=f"regex does not compile: {exc}",
                )
            )

        if isinstance(accepted, list) and accepted:
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

        if regex.startswith("^") or regex.endswith("$"):
            warnings.append(
                Diagnostic(
                    severity="info",
                    code="redundant-regex-anchor",
                    path=path + ("regex",),
                    message=(
                        "matching is a full match, so a leading '^' or "
                        "trailing '$' is redundant"
                    ),
                )
            )

    if (
        not open_ended
        and not isinstance(regex, str)
        and not accepted
        and not document.get("accept")
    ):
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

    return warnings


def _check_patterns(
    patterns: Any, path: tuple[Union[str, int], ...]
) -> list[Diagnostic]:
    """
    short-answer.md: every delimited pattern in an accept/reject list must
    parse as an MDQ regex.
    """
    if not isinstance(patterns, list):
        return []

    warnings: list[Diagnostic] = []
    for index, entry in enumerate(patterns):
        pattern = entry.get("pattern") if isinstance(entry, dict) else entry
        if not isinstance(pattern, str) or not pattern.strip().startswith("/"):
            continue
        try:
            RegexPattern(pattern)
        except InvalidRegexError as exc:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="invalid-regex",
                    path=path + (index,),
                    message=f"regex does not compile: {exc}",
                )
            )
    return warnings


def _check_numeric(
    document: dict[str, Any],
    path: tuple[str | int, ...],
) -> list[Diagnostic]:
    """
    numeric.md: the domain is inferred from the answer's representation
    when not declared, so a declared domain that contradicts the answer
    is a mistake; and a relative tolerance around zero can never widen
    the accepted range.
    """
    warnings: list[Diagnostic] = []
    answer = document.get("answer")
    domain = document.get("domain")
    decimal_places = document.get("decimalPlaces")
    tolerance = document.get("tolerance")

    if domain == "integer" and _is_number(answer) and float(answer) != int(answer):
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

    if isinstance(tolerance, dict):
        relative = tolerance.get("relative")
        if _is_number(relative) and relative > 0 and answer == 0:
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

        if _is_number(relative) and relative > 1:
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

    if decimal_places is not None and domain in ("integer", "fraction"):
        warnings.append(
            Diagnostic(
                severity="info",
                code="ignored-decimal-places",
                path=path + ("decimalPlaces",),
                message=f"'decimalPlaces' is ignored when domain is {domain!r}",
            )
        )

    return warnings


def _check_fill_in(document: dict[str, Any]) -> list[Diagnostic]:
    """
    fill-in.md: every blank is referenced from the stem by its id, so the
    two sides must line up; and each blank is graded like the question
    type it names, so it inherits that type's checks.
    """
    blanks = document.get("blanks")
    if not isinstance(blanks, list):
        return []

    warnings: list[Diagnostic] = []
    seen_ids: dict[str, int] = {}
    blank_ids: list[str] = []

    for index, blank in enumerate(blanks):
        if not isinstance(blank, dict):
            continue

        blank_id = blank.get("id")
        if isinstance(blank_id, str):
            blank_ids.append(blank_id)
            first_index = seen_ids.get(blank_id)
            if first_index is not None:
                warnings.append(
                    Diagnostic(
                        severity="warning",
                        code="duplicate-blank-id",
                        path=("blanks", index, "id"),
                        message=(
                            f"blank id {blank_id!r} is already used by "
                            f"blanks[{first_index}]; the stem's [^{blank_id}] "
                            f"marker is ambiguous"
                        ),
                    )
                )
            else:
                seen_ids[blank_id] = index

        blank_type = blank.get("type")
        blank_path: tuple[Union[str, int], ...] = ("blanks", index)

        if blank_type == "multiple-choice":
            warnings.extend(_check_choices(blank, blank_path + ("choices",)))
            warnings.extend(
                _check_multiple_choice_answers(blank, blank_path + ("choices",))
            )
        elif blank_type == "short-answer":
            warnings.extend(_check_short_answer(blank, blank_path))
        elif blank_type == "numeric":
            warnings.extend(_check_numeric(blank, blank_path))

    warnings.extend(_check_blank_markers(document, blank_ids))
    return warnings


def _check_blank_markers(
    document: dict[str, Any],
    blank_ids: list[str],
) -> list[Diagnostic]:
    """Cross-check the stem's `[^id]` markers against the declared blanks."""
    stem = document.get("stem")
    if not isinstance(stem, str):
        return []

    # `[^size/numeric]` states the blank's type inline; the id is the
    # part before the slash.
    referenced = [
        marker.split("/", 1)[0].strip() for marker in _BLANK_MARKER_RE.findall(stem)
    ]

    warnings: list[Diagnostic] = []
    declared = set(blank_ids)

    for name in dict.fromkeys(referenced):
        if name not in declared:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="undefined-blank",
                    path=("stem",),
                    message=(
                        f"the stem references [^{name}] but no blank with "
                        f"that id is defined"
                    ),
                )
            )

    seen = set(referenced)
    for index, blank_id in enumerate(blank_ids):
        if blank_id not in seen:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="unreferenced-blank",
                    path=("blanks", index, "id"),
                    message=(
                        f"blank {blank_id!r} is never referenced by a "
                        f"[^{blank_id}] marker in the stem"
                    ),
                )
            )

    return warnings


def _check_exam(document: dict[str, Any]) -> list[Diagnostic]:
    """
    exam.md: an exam MAY contain zero questions, but SHOULD warn -- an
    exam with nothing to answer is a draft, not an assessment. Duplicate
    question ids are also flagged: the ids are what results and
    cross-links refer to.
    """
    questions = document.get("questions")
    if not isinstance(questions, list):
        return []

    if not questions:
        return [
            Diagnostic(
                severity="warning",
                code="exam-without-questions",
                path=("questions",),
                message="the exam contains no questions, so it cannot be answered",
            )
        ]

    warnings: list[Diagnostic] = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(questions):
        if not isinstance(entry, dict):
            continue
        # An unresolved `include` is identified by its target, a question
        # written inline by its own id.
        identifier = entry.get("include") or entry.get("id")
        if not isinstance(identifier, str):
            continue
        first = seen.get(identifier)
        if first is not None:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="duplicate-question-id",
                    path=("questions", index),
                    message=(
                        f"question id {identifier!r} is already used by "
                        f"questions[{first}]"
                    ),
                )
            )
        else:
            seen[identifier] = index
    return warnings
