"""
Hypothesis strategies for generating MDQ questions, exams, and the
Markdown fragments (paragraphs, lists, code blocks, ...) their
`preamble`/`epilogue`/`stem` fields are made of.

The markdown-related strategies at the bottom of this module *construct*
valid Markdown rather than generate arbitrary text and filter out what
doesn't parse: filtering throws away draws, which both slows generation
and hurts shrinking (a strategy that filters too much trips Hypothesis's
`filter_too_much`/`too_slow` health checks -- the fix is to construct
more precisely, not to relax the check). Each strategy's docstring
explains the specific CommonMark rule it is built around.

A generated block is "safe" when it survives render -> parse -> normalize
unchanged: rendering it into a document, parsing that document back with
`mdq._parser`, and normalizing both sides (`mdq.models.BaseQuestion.
normalize`) yields the same value it started from. `mdq._parser.
reconstruct_blocks` -- also used by `mdq.models.normalize_paragraphs` --
is what makes this a precise, checkable contract instead of a hand-wavy
one: it runs the same CommonMark parser MDQ uses and reconstructs each
top-level block exactly as `MDQParser.raw_text` would once it is
embedded in a full document and parsed back out.
"""

from typing import Any, Callable, Literal, get_args

from hypothesis import strategies as st

from .. import models
from ..types import EssayInput, QuestionType

# QUESTION_TYPES = get_args(QuestionType)
QUESTION_TYPES: tuple[QuestionType, ...] = ("essay",)
CODE_HIGHLIGHT_FORMATS = [
    "python",
    "javascript",
    "js",
    "py",
    "typescript",
    "java",
    "c",
    "c++",
    "cpp",
    "html",
    "css",
    "bash",
    "json",
    "yaml",
]


#
# Question strategies
#
def questions(
    *,
    type: QuestionType | None = None,
    normalize: bool = False,
) -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating questions of the given type.

    If `type` is `None`, any question type is allowed.
    """
    possible_types = (type,) if type is not None else QUESTION_TYPES
    question = st.sampled_from(possible_types).flatmap(
        lambda t: QUESTION_STRATEGIES[t]()
    )

    if normalize:
        question = question.map(lambda q: q.normalize())
    return question


def multiple_choice_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating questions of the given type.

    If `type` is `None`, any question type is allowed.
    """
    return st.builds(
        models.MultipleChoiceQuestion,
        **_base_question_kwargs(),
    )


def multiple_selection_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating questions of the given type.

    If `type` is `None`, any question type is allowed.
    """
    return st.builds(
        models.MultipleSelectionQuestion,
        **_base_question_kwargs(),
    )


def true_false_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating questions of the given type.

    If `type` is `None`, any question type is allowed.
    """
    return st.builds(
        models.TrueFalseQuestion,
        **_base_question_kwargs(),
    )


def numeric_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating questions of the given type.

    If `type` is `None`, any question type is allowed.
    """
    return st.builds(
        models.NumericQuestion,
        answer=numeric_answers(),
        **_base_question_kwargs(),
    )


_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1


def numeric_answers() -> st.SearchStrategy[int | float | str]:
    """
    Return a strategy for generating a numeric `answer` in the
    representation the parser gives it (numeric.md, "Answer
    representation"): an `int` in the 32-bit signed range, a string for
    a larger integer or for a fraction, a non-whole float, or a string
    for a decimal that a float cannot reproduce digit by digit.

    Rendering such an answer and parsing it back gives the same value
    in the same representation.
    """
    signs = st.sampled_from(["", "-"])
    naturals = st.integers(min_value=0, max_value=10**30)
    digits = st.text(alphabet="0123456789", min_size=1, max_size=25)
    small_ints = st.integers(min_value=_INT32_MIN, max_value=_INT32_MAX)
    large_ints = (
        st.integers(max_value=_INT32_MIN - 1) | st.integers(min_value=_INT32_MAX + 1)
    ).map(str)
    fractions = st.builds(
        lambda sign, num, den: f"{sign}{num}/{den}",
        signs,
        naturals,
        st.integers(min_value=1, max_value=10**30),
    )
    floats = st.floats(
        min_value=-1e15, max_value=1e15, allow_nan=False, allow_infinity=False
    ).filter(lambda x: not x.is_integer())
    # A trailing zero keeps a significant digit a float drops, and 18 or
    # more significant digits ending in a nonzero digit are more than the
    # shortest repr of any float has.
    trailing_zero = st.builds(
        lambda sign, whole, frac: f"{sign}{whole}.{frac}0", signs, naturals, digits
    )
    long_decimals = st.builds(
        lambda sign, whole, frac, last: f"{sign}{whole}.{frac}{last}",
        signs,
        st.integers(min_value=1, max_value=10**30),
        st.text(alphabet="0123456789", min_size=18, max_size=30),
        st.sampled_from("123456789"),
    )
    return small_ints | large_ints | fractions | floats | trailing_zero | long_decimals


def short_answer_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating questions of the given type.

    If `type` is `None`, any question type is allowed.
    """
    return st.builds(
        models.ShortAnswerQuestion,
        **_base_question_kwargs(),
    )


def essay_questions(
    *,
    input: EssayInput | None = None,
) -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating questions of the given type.

    If `type` is `None`, any question type is allowed.
    """
    if input is None:
        inputs = get_args(EssayInput)
        return st.sampled_from(inputs).flatmap(lambda t: essay_questions(input=t))

    return st.builds(
        models.EssayQuestion,
        highlight=code_highlight_formats() | st.none()
        if input == "code"
        else st.none(),
        **_base_question_kwargs(),
    )


def fill_in_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating questions of the given type.

    If `type` is `None`, any question type is allowed.
    """
    return st.builds(
        models.FillInQuestion,
        **_base_question_kwargs(),
    )


#
# Exam strategies
#
def exams(max_questions: int) -> st.SearchStrategy[models.Exam]:
    """
    Create a strategy for generating an exam with up to `max_questions`
    questions.
    """
    return st.builds(
        models.Exam,
        # id=st.none() | st.text(),
        # uuid=st.none() | st.text(),
        # title=st.none() | st.text(),
        # course=st.none() | st.text(),
        # author=st.none() | st.text(),
        # locale=st.none() | st.text(),
        # instructions=st.none() | st.text(),
        # tags=st.none() | st.lists(st.text(), min_size=1),
        # meta=st.none() | st.dictionaries(st.text(), st.just(None) | st.text()),
        # penalty=st.just("none"),
        # questions=st.lists(question(), min_size=1, max_size=max_questions),
    )


#
# Auxiliary strategies
#
def code_highlight_formats() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating code formats for highlighting.
    """
    return st.sampled_from(CODE_HIGHLIGHT_FORMATS)


#: Subset of `hypothesis.strategies.characters`'s category names used by
#: the Markdown-safe text strategies below. Spelled out so
#: `_TEXT_BLACKLIST_CATEGORIES` keeps the precise `Literal` type
#: `characters()` expects -- a bare `tuple[str, ...]` loses it and fails
#: mypy at every use site.
_CharCategory = Literal["Cs", "Cc", "Zl", "Zp"]

#: Categories excluded from every Markdown-safe text strategy below:
#: surrogates (never valid standalone text), other control characters,
#: and the two Unicode line/paragraph separators, which behave like line
#: breaks CommonMark does not expect inside a single logical line.
_TEXT_BLACKLIST_CATEGORIES: tuple[_CharCategory, ...] = ("Cs", "Cc", "Zl", "Zp")

#: A single physical line's worth of Markdown-safe text: any character
#: outside `_TEXT_BLACKLIST_CATEGORIES` except a literal newline.
_LINE_ALPHABET = st.characters(
    blacklist_categories=_TEXT_BLACKLIST_CATEGORIES,
    blacklist_characters="\n",
)

#: A Unicode letter -- safe as the first character of a line that must
#: not be misread as the start of a different block. See `_safe_line`.
_LETTER = st.characters(whitelist_categories=("Ll", "Lu", "Lt", "Lm", "Lo"))


def _safe_line(max_size: int = 40) -> st.SearchStrategy[str]:
    """
    Return a strategy for one physical line of Markdown-safe text.

    CommonMark decides a line's block type from its first character: `#`
    opens a heading, `>` a blockquote, `-`/`+`/`*`/a digit marker opens a
    list, three or more `` ` ``/`~` opens a fenced code block, a run of
    `-`/`=`/`_`/`*` is a thematic break or a setext underline, and `[`
    can be read as a link reference definition or (for a question's
    first intro block) the `[id]` slug prefix. Forcing the line to start
    with a Unicode letter rules out all of these at once -- for every
    physical line of a block, not just its first.

    What comes after the first character needs no such care: markdown-it
    exposes a paragraph or heading's inline content as `.content`, the
    *raw source text before inline parsing* -- emphasis, code spans,
    links, autolinks, entities and raw HTML all leave it untouched (see
    `mdq._parser._question.MDQParser.raw_text`) -- so no punctuation used by an
    inline construct can corrupt the round trip; only where a line
    begins matters.
    """
    return st.builds(
        lambda first, rest: first + rest,
        _LETTER,
        st.text(alphabet=_LINE_ALPHABET, max_size=max_size),
    )


def md_paragraphs() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating Markdown paragraphs.

    Safe = survives render -> parse -> normalize unchanged (see the
    module docstring). A draw is one or more `_safe_line`s joined by a
    single newline, so this also exercises multi-line, soft-wrapped
    paragraphs -- every line, not just the first, is guarded against
    starting a different block. `mdq.models.normalize_intro` and
    `normalize_paragraphs` collapse the soft-wrapped newlines back to
    single spaces, exactly as a render/parse round trip does. A draw
    here is always a single Markdown block (no blank line ever appears
    in it), so used as `stem` it never triggers `normalize_intro`'s
    block-migration into `preamble` -- that only matters for a stem
    constructed by hand, spanning more than one block.
    """
    return st.lists(_safe_line(), min_size=1, max_size=4).map("\n".join)


def md_headings() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating ATX headings, `##` through `######`.

    H1 (a single `#`) is excluded: `docs/question-types/generic.md`
    forbids one in a preamble/epilogue outright, since that syntax is
    reserved for an exam's title.
    """
    return st.builds(
        lambda level, text: f"{'#' * level} {text}",
        level=st.integers(min_value=2, max_value=6),
        text=_safe_line(),
    )


def md_blockquotes() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating a (possibly multi-line) blockquote.

    Every line is prefixed with `> `, so -- unlike a paragraph -- its
    block type can never be ambiguous, and the quoted text itself may
    start with anything `_safe_line` allows.
    """
    return st.lists(_safe_line(), min_size=1, max_size=3).map(
        lambda lines: "\n".join(f"> {line}" for line in lines)
    )


def md_lists(max_depth: int = 1) -> st.SearchStrategy[str]:
    """
    Return a strategy for generating a tight bullet or ordered list, with
    up to `max_depth` levels of nesting.

    A list always uses one marker throughout a given level -- `- ` for a
    bullet list, `1. ` for every item of an ordered one, since CommonMark
    never requires increasing numbers -- and is tight (no blank line
    between items). A *loose* list, or two adjacent lists that happen to
    share a marker and so parse back as a single, merged CommonMark node,
    would still reconstruct correctly (`mdq._parser.reconstruct_blocks`
    is verbatim for list blocks, merged or not); tight just keeps the
    generated source simple.
    """
    return _list_lines(max_depth).map("\n".join)


def _list_lines(depth_remaining: int) -> st.SearchStrategy[list[str]]:
    """Return a strategy for one list's raw source lines."""
    marker = st.sampled_from(["- ", "1. "])
    return marker.flatmap(
        lambda m: st.lists(
            _list_item_lines(m, depth_remaining), min_size=1, max_size=3
        ).map(lambda items: [line for item_lines in items for line in item_lines])
    )


def _list_item_lines(marker: str, depth_remaining: int) -> st.SearchStrategy[list[str]]:
    """
    Return a strategy for one list item's raw source lines: its own text
    line, plus -- while `depth_remaining` allows -- a nested sub-list
    indented to the column where this item's own content starts
    (`len(marker)`), which is what CommonMark requires for a sub-list to
    belong to the item rather than close it.
    """
    item_line = _safe_line().map(lambda text: f"{marker}{text}")
    if depth_remaining <= 0:
        return item_line.map(lambda line: [line])

    indent = " " * len(marker)

    def combine(line: str, sublist: list[str] | None) -> list[str]:
        if sublist is None:
            return [line]
        return [line] + [indent + subline for subline in sublist]

    return st.builds(combine, item_line, st.none() | _list_lines(depth_remaining - 1))


def md_code_blocks() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating Markdown code blocks: fenced (with
    ``` ``` ``` or `~~~`, with or without an info string) or indented.
    """
    return _md_fenced_code_block() | _md_indented_code_block()


def md_inlines() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating inline Markdown content.
    """
    return safe_texts(multiline=False)


def _md_fenced_code_block() -> st.SearchStrategy[str]:
    """
    A fenced code block's body never contains its own fence character --
    constructed that way, rather than filtered -- so no body line can
    ever be mistaken for the closing fence, however long a run of it
    would otherwise appear.
    """
    return st.tuples(
        st.sampled_from(["`", "~"]),
        st.integers(min_value=3, max_value=5),
        st.none() | code_highlight_formats(),
    ).flatmap(_build_fenced_code_block)


def _build_fenced_code_block(
    params: tuple[str, int, str | None],
) -> st.SearchStrategy[str]:
    fence_char, fence_len, info = params
    fence = fence_char * fence_len
    header = f"{fence}{info}" if info else fence
    body_alphabet = st.characters(
        blacklist_categories=_TEXT_BLACKLIST_CATEGORIES,
        blacklist_characters="\n" + fence_char,
    )
    body = st.lists(st.text(alphabet=body_alphabet, max_size=40), max_size=4)
    return body.map(lambda lines: "\n".join([header, *lines, fence]))


def _md_indented_code_block() -> st.SearchStrategy[str]:
    """
    An indented code block needs no fence-collision guard: every line is
    just prefixed with four spaces, and CommonMark treats everything
    past the indent as literal text. Lines are kept non-blank, since a
    blank line inside one needs a following indented line to still
    belong to the block -- simpler to just never generate one. The same
    goes for a line of only spaces/tabs, which CommonMark reads as blank;
    other Unicode whitespace (NBSP) is not blank and stays possible.
    """
    line = (
        st.text(alphabet=_LINE_ALPHABET, min_size=1, max_size=40)
        .filter(lambda s: s.strip(" \t") != "")
        .map(lambda s: "    " + s)
    )
    return st.lists(line, min_size=1, max_size=4).map("\n".join)


def md_safe_blocks() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating a single "safe" Markdown block --
    one that survives render -> parse -> normalize unchanged (see the
    module docstring) -- suitable for any position in a preamble or
    epilogue.

    Composes a paragraph, a fenced or indented code block, a bullet or
    ordered list (possibly nested), a blockquote, and a heading (H2-H6).
    No table: see the module docstring.
    """
    return (
        md_paragraphs()
        | md_code_blocks()
        | md_lists()
        | md_blockquotes()
        | md_headings()
    )


def md_safe_multi_blocks(
    min_size: int = 1, max_size: int = 3
) -> st.SearchStrategy[str]:
    """
    Return a strategy for generating a sequence of safe Markdown blocks,
    joined the way `mdq.models._render` joins a preamble/epilogue's blocks: two
    newlines apart.

    `mdq._parser.reconstruct_blocks` (and so `mdq.models.
    normalize_paragraphs`) reconstructs the result exactly, even when two
    adjacent blocks of the same kind parse back as a single, merged
    CommonMark node -- see `md_list`.
    """
    return st.lists(md_safe_blocks(), min_size=min_size, max_size=max_size).map(
        "\n\n".join
    )


def safe_texts(multiline: bool = False) -> st.SearchStrategy[str]:
    """
    Somewhat safe text for use in tests. It excludes control characters, line
    separators, and paragraph separators. It also excludes the empty string.
    """
    alphabet = (
        st.characters(blacklist_categories=_TEXT_BLACKLIST_CATEGORIES)
        if multiline
        else _LINE_ALPHABET
    )
    return st.text(alphabet=alphabet, min_size=1)


def slugs() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating slugs: ASCII alphanumeric groups
    joined by a single `-`, matching `mdq._parser`'s `SLUG_BODY_RE`.

    A question's `id` is only ever recovered from the inline `[id]`
    prefix (`docs/question-types/generic.md`) when it matches that
    regex, which is ASCII-only. Drawing from the full Unicode `Ll`
    category -- as this used to -- can produce a lowercase letter like
    "µ" that `SLUG_BODY_RE` rejects, silently turning a rendered `[id]
    stem` back into plain stem text with no id at all.
    """
    ascii_alnum = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789")
    group = st.text(alphabet=ascii_alnum, min_size=1, max_size=8)
    return st.lists(group, min_size=1, max_size=3).map("-".join)


def uuids() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating UUIDs.
    """
    return st.uuids().map(str)


def locales() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating locale strings.
    """
    # TODO: generalize this to any valid locale string, not just a few common ones.
    return st.sampled_from(["en", "es", "fr", "de", "pt", "zh", "ja", "ko"])


def tags() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating tags.
    """
    return st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Nd"),
            blacklist_characters="-",
        ),
        min_size=1,
    )


def weights() -> st.SearchStrategy[float]:
    """
    Return a strategy for generating weights (non-negative floats).
    """
    return st.floats(min_value=0.0, allow_nan=False, allow_infinity=False).map(
        lambda x: round(x, 3)
    ) | st.just(1.0)  # default weight is 1.0


#
# Utility functions
#
def _base_question_kwargs() -> dict[str, st.SearchStrategy[Any]]:
    """
    Return a dict of strategies to build question fields.

    We can't be very type-safe here due to Python's limitations on the type
    system.
    """
    return {
        "id": st.none() | slugs(),
        "uuid": st.none() | uuids(),
        "title": st.none() | safe_texts(),
        "author": st.none() | safe_texts(),
        "stem": md_paragraphs(),
        "preamble": st.none() | md_safe_multi_blocks(),
        "epilogue": st.none() | md_safe_multi_blocks(),
        "comment": st.none() | safe_texts(multiline=True),
        "locale": st.none() | locales(),
        "tags": st.lists(tags(), min_size=1),
        "weight": weights(),
        # "meta": st.none() | st.dictionaries(st.text(), st.just(None) | st.text()),
    }


QUESTION_STRATEGIES: dict[
    QuestionType, Callable[[], st.SearchStrategy[models.Question]]
] = {
    "essay": essay_questions,
    # "multiple-choice": multiple_choice_question,
    # "multiple-selection": multiple_selection_question,
    # "true-false": true_false_question,
    # "numeric": numeric_question,
    # "short-answer": short_answer_question,
    # "fill-in": fill_in_question,
}
