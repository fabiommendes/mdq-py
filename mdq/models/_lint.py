"""
Lint rules shared by several models in `mdq.models`: the common
document fields (`id`, `uuid`, `tags`, `locale`), text checks, and the
`highlight` rules. The rules of one question family live next to its
model (`_choice`, `_numeric`, `_ordering`, `_text`, `_fill_in`, `_exam`);
`mdq.models._lint_codes` holds the code registry they all report through.

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
from typing import Iterator, Sequence

from markdown_it import MarkdownIt
from pygments.lexers import find_lexer_class_by_name
from pygments.util import ClassNotFound

from .. import _parser
from .._diagnostics import Diagnostic
from .._markdown import SLUG_PATTERN
from ._lint_codes import diag

#: Renders a single line's inline markdown to compare two ordering lines,
#: or two choices' texts, the way a student would see them
#: (`check_ordering_visually_identical_lines`,
#: `check_choices_visually_identical`), the same engine `mdq._parser` uses
#: to parse MDQ source.
_RENDER_MD = MarkdownIt("gfm-like")

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


def language_subtag(locale: str | None) -> str:
    if locale is None:
        return ""
    return locale.split("-")[0].lower()


# ----------------------------------------------------------------------
# common rules
# ----------------------------------------------------------------------


#: base.md:252, footnote [^2]: the url-safe shape a question `id` SHOULD have.
_URL_SAFE_ID_RE = re.compile(SLUG_PATTERN)


def check_id_is_url_safe(id: str | None) -> Iterator[Diagnostic]:
    """base.md:252: `id` SHOULD be url-safe (`[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*`)."""
    if id is None or _URL_SAFE_ID_RE.fullmatch(id):
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
    A `===` underline gives an H1, which `instructions` and the stem and
    epilogue of a question forbid (`forbidden-block-element`), so a field
    that passed validation only reports `---` there.
    """
    if not text:
        return
    for token in _RENDER_MD.parse(text):
        if (
            token.type == "heading_open"
            and token.level == 0
            and token.markup in ("-", "=")
        ):
            underline = token.markup * 3
            role = "opens a block" if token.markup == "-" else "separates questions"
            yield diag(
                code="setext-heading",
                path=path,
                message=(
                    f"a {underline!r} line right after text is a setext "
                    "heading, not a block boundary; put a blank line "
                    f"before the {underline!r} that {role}"
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
    subtag = language_subtag(locale)
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


# ----------------------------------------------------------------------
# ordering
# ----------------------------------------------------------------------


def render_visual_key(text: str) -> str:
    """How `text` renders, for comparing lines/choices as a reader would."""
    return str(_RENDER_MD.renderInline(text)).strip()
