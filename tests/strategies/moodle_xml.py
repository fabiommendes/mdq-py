"""
Hypothesis strategies for `mdq.convert.moodle_xml` values, in "Brazil core"
flavored text.
"""

from __future__ import annotations

from typing import Literal

from hypothesis import strategies as st

from mdq import _markdown
from mdq.convert.moodle_xml import MoodleAnswer, MoodleCloze, MoodleXmlBlock

__all__ = [
    "moodle_text",
    "moodle_line_text",
    "moodle_fraction",
    "moodle_grade",
    "moodle_answers",
    "moodle_base_fields",
    "moodle_multichoice_block",
    "moodle_truefalse_block",
    "moodle_shortanswer_block",
    "moodle_numerical_block",
    "moodle_essay_block",
    "cloze_answer_text",
    "moodle_cloze",
    "mdq_text",
]


#: `characters()` needs the literal type it declares -- a bare
#: `tuple[str, ...]` loses it and fails mypy at every use site.
type CharCategory = Literal["Cc", "Cs"]
EXCLUDED_CATEGORIES: tuple[CharCategory, ...] = ("Cs",)


def moodle_text(max_size: int = 30) -> st.SearchStrategy[str]:
    """
    Unicode text safe to embed in a Moodle XML `<text>` node: control
    characters and lone surrogates excluded (both are invalid in XML
    1.0), `\\r` excluded (XML's mandatory CR normalization would break
    an equality round trip), stripped at both ends so `ET.indent`'s
    whitespace reformatting never touches it. Includes XML metacharacters
    (`<`, `&`, `"`), the CDATA terminator `]]>`, single newlines and
    non-ASCII text -- all of which `ElementTree` escapes on write and
    restores transparently on read.
    """
    alphabet = st.one_of(
        st.just("\n"),
        st.characters(
            min_codepoint=0x20,
            max_codepoint=0xFFFD,
            blacklist_categories=EXCLUDED_CATEGORIES,
        ),
    )
    return st.text(alphabet=alphabet, min_size=1, max_size=max_size).filter(
        lambda s: s == s.strip() and s != ""
    )


def moodle_line_text(max_size: int = 20) -> st.SearchStrategy[str]:
    """Single-line text, for fields (name, idnumber, tags, unit) that can't hold a newline."""
    alphabet = st.characters(
        min_codepoint=0x20,
        max_codepoint=0xFFFD,
        blacklist_categories=EXCLUDED_CATEGORIES,
    )
    return st.text(alphabet=alphabet, min_size=1, max_size=max_size).filter(
        lambda s: s == s.strip() and s != ""
    )


def moodle_fraction() -> st.SearchStrategy[float]:
    return st.floats(
        min_value=-100, max_value=100, allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 2))


def moodle_grade() -> st.SearchStrategy[float]:
    return st.floats(
        min_value=0.1, max_value=10, allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 2))


def moodle_answers(
    min_size: int = 1, max_size: int = 4, *, tolerance: bool = False
) -> st.SearchStrategy[list[MoodleAnswer]]:
    return st.lists(
        st.builds(
            MoodleAnswer,
            text=moodle_text(),
            fraction=moodle_fraction(),
            feedback=st.none() | moodle_text(),
            tolerance=(st.none() | moodle_fraction()) if tolerance else st.none(),
        ),
        min_size=min_size,
        max_size=max_size,
    )


def moodle_base_fields() -> dict[str, st.SearchStrategy]:
    """Fields every question type carries, shared by the per-type block strategies below."""
    return dict(
        questiontext=moodle_text(),
        name=st.none() | moodle_line_text(),
        idnumber=st.none() | moodle_line_text(),
        text_format=st.sampled_from(["html", "moodle", "plain_text", "markdown"]),
        general_feedback=st.none() | moodle_text(),
        default_grade=moodle_grade(),
        tags=st.lists(moodle_line_text(), max_size=3),
    )


def moodle_multichoice_block(
    single: st.SearchStrategy[bool | None] | None = None,
) -> st.SearchStrategy[MoodleXmlBlock]:
    return st.builds(
        MoodleXmlBlock,
        type=st.just("multichoice"),
        answers=moodle_answers(min_size=2, max_size=4),
        single=single if single is not None else (st.none() | st.booleans()),
        shuffle_answers=st.none() | st.booleans(),
        grader_info=st.none(),
        response_format=st.none(),
        unit=st.none(),
        **moodle_base_fields(),
    )


def moodle_truefalse_block() -> st.SearchStrategy[MoodleXmlBlock]:
    return st.builds(
        MoodleXmlBlock,
        type=st.just("truefalse"),
        answers=moodle_answers(min_size=2, max_size=2),
        single=st.none(),
        shuffle_answers=st.none(),
        grader_info=st.none(),
        response_format=st.none(),
        unit=st.none(),
        **moodle_base_fields(),
    )


def moodle_shortanswer_block() -> st.SearchStrategy[MoodleXmlBlock]:
    return st.builds(
        MoodleXmlBlock,
        type=st.just("shortanswer"),
        answers=moodle_answers(min_size=1, max_size=3),
        single=st.none(),
        shuffle_answers=st.none(),
        grader_info=st.none(),
        response_format=st.none(),
        unit=st.none(),
        **moodle_base_fields(),
    )


def moodle_numerical_block() -> st.SearchStrategy[MoodleXmlBlock]:
    return st.builds(
        MoodleXmlBlock,
        type=st.just("numerical"),
        answers=moodle_answers(min_size=1, max_size=2, tolerance=True),
        single=st.none(),
        shuffle_answers=st.none(),
        grader_info=st.none(),
        response_format=st.none(),
        unit=st.none() | moodle_line_text(max_size=10),
        **moodle_base_fields(),
    )


def moodle_essay_block() -> st.SearchStrategy[MoodleXmlBlock]:
    return st.builds(
        MoodleXmlBlock,
        type=st.just("essay"),
        answers=st.just([]),
        single=st.none(),
        shuffle_answers=st.none(),
        grader_info=st.none() | moodle_text(),
        response_format=st.none() | st.sampled_from(["editor", "plain", "monospaced"]),
        unit=st.none(),
        **moodle_base_fields(),
    )


#: Characters `parse_cloze`/`render_cloze` treat as syntactically meaningful
#: inside a `{weight:KIND:...}` blank (entry prefix, credit tag, feedback
#: separator, numerical tolerance separator, blank delimiters) and that
#: this format has no escape mechanism for -- an answer's `text` genuinely
#: cannot represent them. Generating one and weakening the round-trip
#: assertion instead would paper over that gap, so the strategy excludes
#: them outright (see `test_render_cloze_then_parse_recovers_kind_and_texts`).
CLOZE_UNSAFE_CHARS = "={}~#:%"


def cloze_answer_text(max_size: int = 10) -> st.SearchStrategy[str]:
    return moodle_line_text(max_size=max_size).filter(
        lambda s: not any(ch in CLOZE_UNSAFE_CHARS for ch in s)
    )


def moodle_cloze() -> st.SearchStrategy[MoodleCloze]:
    return st.builds(
        MoodleCloze,
        kind=st.sampled_from(["SHORTANSWER", "NUMERICAL", "MULTICHOICE"]),
        answers=st.lists(
            st.builds(
                MoodleAnswer,
                text=cloze_answer_text(),
                fraction=st.just(100.0),
                feedback=st.none(),
                tolerance=st.none(),
            ),
            min_size=1,
            max_size=1,
        ),
        weight=st.integers(min_value=1, max_value=5),
    )


def mdq_text(max_size: int = 30) -> st.SearchStrategy[str]:
    """Unicode text safe for an MDQ question field, mirroring `moodle_text`."""
    alphabet = st.one_of(
        st.just("\n"),
        st.characters(
            min_codepoint=0x20,
            max_codepoint=0xFFFD,
            blacklist_categories=EXCLUDED_CATEGORIES,
        ),
    )
    return st.text(alphabet=alphabet, min_size=1, max_size=max_size).filter(
        lambda s: (
            s == s.strip()
            and s != ""
            and "\n\n" not in s
            and "[^" not in s
            # base.md, "Forbidden elements": an H1 heading, a heading or
            # paragraph starting with '[', or a '['-led list, is now a
            # model error (dev/specs/to-do/rule-conformance.md, section
            # D) wherever it lands as a stem/preamble, so a generated
            # value that happens to look like one is excluded rather
            # than producing a document that can never be built.
            and not _markdown.find_forbidden_elements(
                s, allow_first_paragraph_bracket=True
            )
        )
    )
