"""
Hypothesis strategies for generating MDQ questions, exams, and the
Markdown fragments (paragraphs, lists, code blocks, ...) their
`stem`/`epilogue` fields are made of.

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
top-level block exactly as `BlockReader.raw_text` (in `mdq._parser._blocks`)
would once it is embedded in a full document and parsed back out.
"""

import unicodedata
from typing import Any, Callable, Literal, get_args

from hypothesis import strategies as st

from .. import models
from ..types import EssayContent, OrderingContent, QuestionType

QUESTION_TYPES: tuple[QuestionType, ...] = get_args(QuestionType)
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
    Return a strategy for generating valid questions of the given type.

    If `type` is `None`, any question type is allowed. With `normalize`,
    each question is passed through `normalize()` so it is the canonical
    form a render then parse keeps unchanged.
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
    Return a strategy for generating multiple-choice questions.

    Two to four choices, exactly one with score 1 and the others with
    score 0 or no score. Either every choice has an `id` or none has.
    """
    return st.builds(
        models.MultipleChoiceQuestion,
        choices=_scored_choices(),
        **_base_question_kwargs(answer_body=True),
    )


def multiple_selection_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating multiple-selection questions.

    Two to four choices, at least one correct and at least one incorrect.
    """
    return st.builds(
        models.MultipleSelectionQuestion,
        choices=_boolean_choices(),
        **_base_question_kwargs(answer_body=True),
    )


def true_false_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating true-false questions.

    Two to four statements, each true or false.
    """
    return st.builds(
        models.TrueFalseQuestion,
        choices=_statements(),
        **_base_question_kwargs(answer_body=True),
    )


def numeric_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating numeric questions.

    The `answer` comes from `numeric_answers`. No `unit` or `tolerance`.
    """
    return st.builds(
        lambda fields, base: models.NumericQuestion(**fields, **base),
        _numeric_key_fields(),
        st.fixed_dictionaries(_base_question_kwargs(answer_body=True)),
    )


def _numeric_key_fields() -> st.SearchStrategy[dict[str, Any]]:
    """
    The fields of a numeric question or blank: the `answer` only. `normalize()`
    fills `domain` and `decimalPlaces` as the parser does.
    """
    return numeric_answers().map(lambda answer: {"answer": answer})


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
    Return a strategy for generating short answer questions.

    One to three inexact literal patterns in `accept`, and optionally in
    `reject`. No regex, exact literal, `preAccept` or `preReject`.
    """
    return st.builds(
        models.ShortAnswerQuestion,
        accept=_pattern_lists(min_size=1),
        reject=st.none() | _pattern_lists(min_size=1),
        **_base_question_kwargs(answer_body=True),
    )


def essay_questions(
    *,
    content: EssayContent | None = None,
) -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating questions of the given type.

    If `type` is `None`, any question type is allowed.
    """
    if content is None:
        contents = get_args(EssayContent)
        return st.sampled_from(contents).flatmap(lambda t: essay_questions(content=t))

    return st.builds(
        models.EssayQuestion,
        highlight=code_highlight_formats() | st.none()
        if content == "code"
        else st.none(),
        content=st.just(content),
        **_base_question_kwargs(),
    )


def fill_in_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating fill-in questions.

    The stem is one paragraph of plain words with one `[^id]` marker per
    blank, in the order of the blanks. One to three blanks, each a short
    answer blank (inexact literal patterns), a numeric blank (a small
    integer answer) or a multiple-choice blank. The stem is not drawn
    from `md_safe_multi_blocks`: a marker must sit in a plain text run.
    """
    return _fill_in_questions()


def ordering_questions() -> st.SearchStrategy[models.Question]:
    """
    Return a strategy for generating ordering questions.

    Two to five distinct lines at indentation level 0 to 2, as plain
    `text` or as `code`. No `extra`, `accept` or `reject`.
    """
    return st.builds(
        models.OrderingQuestion,
        lines=_ordering_lines(),
        content=st.sampled_from(get_args(OrderingContent)),
        **_base_question_kwargs(answer_body=True),
    )


#
# Exam strategies
#
def exams(max_questions: int = 3) -> st.SearchStrategy[models.Exam]:
    """
    Create a strategy for generating an exam with one to `max_questions`
    questions of any type.

    The questions have distinct `id`s (or none), so the exam is valid.
    An exam has a `title` (a single line of text) and optional `tags`; the
    other fields keep their defaults. It has no `locale` or `author`: its
    questions would inherit them, and a render then parse would not
    return the same questions.
    """
    return st.builds(
        models.Exam,
        title=_safe_line().map(str.strip),
        tags=st.none() | st.lists(tags(), min_size=1, max_size=3, unique=True),
        questions=st.lists(
            questions(normalize=True),
            min_size=1,
            max_size=max_questions,
            unique_by=lambda q: q.id if q.id is not None else object(),
        ),
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
    `mdq._parser._blocks.BlockReader.raw_text`) -- so no punctuation used by an
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
    starting a different block. `mdq.models.normalize_stem` and
    `normalize_paragraphs` collapse the soft-wrapped newlines back to
    single spaces, exactly as a render/parse round trip does. A draw
    here is always a single Markdown block (no blank line ever appears
    in it).
    """
    return st.lists(_safe_line(), min_size=1, max_size=4).map("\n".join)


def md_headings() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating ATX headings, `##` through `######`.

    H1 (a single `#`) is excluded: `docs/question-types/generic.md`
    forbids one in a stem or epilogue outright, since that syntax is
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

    The first line starts with a letter. `normalize_stem` strips the
    stem's leading whitespace, so an indented block drawn as the first
    block of a stem loses its indent; with any other first character
    (`#`, `[`, `>`, `-`) the remaining text would become a different
    block, such as an empty H1 heading, forbidden in a stem.
    """
    line = (
        st.text(alphabet=_LINE_ALPHABET, min_size=1, max_size=40)
        .filter(lambda s: s.strip(" \t") != "")
        .map(lambda s: "    " + s)
    )
    first = _safe_line().map(lambda s: "    " + s)
    return st.builds(
        lambda head, tail: "\n".join([head, *tail]),
        first,
        st.lists(line, max_size=3),
    )


def md_safe_blocks() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating a single "safe" Markdown block --
    one that survives render -> parse -> normalize unchanged (see the
    module docstring) -- suitable for any position in a stem or
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
    joined the way `mdq.models._render` joins a stem or epilogue's blocks: two
    newlines apart.

    `mdq._parser.reconstruct_blocks` (and so `mdq.models.
    normalize_paragraphs`) reconstructs the result exactly, even when two
    adjacent blocks of the same kind parse back as a single, merged
    CommonMark node -- see `md_list`.
    """
    return st.lists(md_safe_blocks(), min_size=min_size, max_size=max_size).map(
        "\n\n".join
    )


def _has_visible_character(text: str) -> bool:
    """Whether `text` has a character that is not white space, a control or a format character."""
    return any(not (c.isspace() or unicodedata.category(c) in ("Cc", "Cf")) for c in text)


def safe_texts(multiline: bool = False) -> st.SearchStrategy[str]:
    """
    Somewhat safe text for use in tests. It excludes control characters, line
    separators, and paragraph separators. It also excludes the empty string and
    text with no visible character, which is `blank-text`.
    """
    alphabet = (
        st.characters(blacklist_categories=_TEXT_BLACKLIST_CATEGORIES)
        if multiline
        else _LINE_ALPHABET
    )
    return st.text(alphabet=alphabet, min_size=1).filter(_has_visible_character)


def slugs() -> st.SearchStrategy[str]:
    """
    Return a strategy for generating slugs: ASCII alphanumeric groups
    joined by a single `-`, matching `mdq._markdown.SLUG_BODY_RE`.

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
def _paragraph_first_blocks() -> st.SearchStrategy[str]:
    """
    Blocks that start with a paragraph.
    """
    return st.builds(
        lambda first, rest: "\n\n".join([first, *rest]),
        md_paragraphs(),
        st.lists(md_safe_blocks(), max_size=2),
    )


def _base_question_kwargs(
    *, answer_body: bool = False
) -> dict[str, st.SearchStrategy[Any]]:
    """
    Return a dict of strategies to build question fields.

    With `answer_body`, the body after the stem is an answer key (choices,
    patterns, a blank definition, ordering lines), so the epilogue starts
    with a paragraph: an indented code block or a list would continue the
    key instead.

    We can't be very type-safe here due to Python's limitations on the type
    system.
    """
    return {
        "id": st.none() | slugs(),
        "uuid": st.none() | uuids(),
        "title": st.none() | safe_texts(),
        "author": st.none() | safe_texts(),
        "stem": md_safe_multi_blocks(),
        "epilogue": st.none()
        | (_paragraph_first_blocks() if answer_body else md_safe_multi_blocks()),
        # The Markdown frontmatter strips the comment string, so a comment
        # with outer whitespace would not round-trip.
        "comment": st.none() | safe_texts(multiline=True).map(str.strip).filter(bool),
        "locale": st.none() | locales(),
        "tags": st.lists(tags(), min_size=1, unique=True),
        "weight": weights(),
        # "meta": st.none() | st.dictionaries(st.text(), st.just(None) | st.text()),
    }


def _words() -> st.SearchStrategy[str]:
    """Letters only: no character can start a block or an inline construct."""
    return st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu")),
        min_size=1,
        max_size=10,
    )


def _unique_lines(
    min_size: int, max_size: int
) -> st.SearchStrategy[list[str]]:
    """Distinct single-line texts, without outer space, for choices and lines."""
    return st.lists(
        _safe_line(20).map(str.strip), min_size=min_size, max_size=max_size, unique=True
    )


def _optional_ids(count: int) -> st.SearchStrategy[list[str | None]]:
    """Either `count` distinct slugs or `count` times `None`."""
    ids: st.SearchStrategy[list[str | None]] = st.lists(
        slugs(), min_size=count, max_size=count, unique=True
    ).map(list)
    return ids | st.just([None] * count)


def _scored_choices() -> st.SearchStrategy[list[models.ScoredChoice]]:
    """Choices of a multiple-choice question: exactly one has score 1."""

    def build(
        texts: list[str], ids: list[str | None], correct: int, wrong: list[float | None]
    ) -> list[models.ScoredChoice]:
        scores = iter(wrong)
        return [
            models.ScoredChoice(
                id=id_,
                text=text,
                score=1.0 if index == correct % len(texts) else next(scores),
            )
            for index, (text, id_) in enumerate(zip(texts, ids))
        ]

    return _unique_lines(2, 4).flatmap(
        lambda texts: st.builds(
            build,
            st.just(texts),
            _optional_ids(len(texts)),
            st.integers(min_value=0),
            st.lists(
                st.sampled_from([None, 0.0]),
                min_size=len(texts),
                max_size=len(texts),
            ),
        )
    )


def _boolean_choices() -> st.SearchStrategy[list[models.BooleanChoice]]:
    """Choices of a multiple-selection question: some correct, some not."""

    def build(
        texts: list[str], ids: list[str | None], correct: int
    ) -> list[models.BooleanChoice]:
        # `correct` of the choices, from 1 to len - 1, are the first ones.
        count = 1 + correct % (len(texts) - 1)
        return [
            models.BooleanChoice(id=id_, text=text, correct=index < count)
            for index, (text, id_) in enumerate(zip(texts, ids))
        ]

    return _unique_lines(2, 4).flatmap(
        lambda texts: st.builds(
            build,
            st.just(texts),
            _optional_ids(len(texts)),
            st.integers(min_value=0),
        )
    )


def _statements() -> st.SearchStrategy[list[models.Statement]]:
    """Statements of a true-false question."""
    return _unique_lines(2, 4).flatmap(
        lambda texts: st.builds(
            lambda ids, flags: [
                models.Statement(id=id_, text=text, correct=flag)
                for text, id_, flag in zip(texts, ids, flags)
            ],
            _optional_ids(len(texts)),
            st.lists(st.booleans(), min_size=len(texts), max_size=len(texts)),
        )
    )


def _pattern_lists(min_size: int) -> st.SearchStrategy[list[models.AnswerPattern]]:
    """Distinct inexact literal patterns."""
    return st.lists(
        _words().map(lambda w: models.AnswerPattern(pattern=w)),
        min_size=min_size,
        max_size=3,
        unique_by=lambda p: p.pattern.casefold(),
    )


@st.composite
def _ordering_lines(draw: st.DrawFn) -> list[tuple[int, str]]:
    """Lines whose level is at most one deeper than the previous line."""
    texts = draw(_unique_lines(2, 5))
    lines = [(0, texts[0])]
    level = 0
    for text in texts[1:]:
        level = draw(st.integers(min_value=0, max_value=min(level + 1, 2)))
        lines.append((level, text))
    return lines


@st.composite
def _fill_in_questions(draw: st.DrawFn) -> models.Question:
    """Draw the blanks, then a stem that references each one once."""
    blank_ids = draw(st.lists(slugs(), min_size=1, max_size=3, unique=True))
    blanks: list[models.Blank] = []
    for blank_id in blank_ids:
        kind = draw(st.sampled_from(["short-answer", "numeric", "choice"]))
        if kind == "short-answer":
            blanks.append(
                models.ShortAnswerBlank(id=blank_id, accept=draw(_pattern_lists(1)))
            )
        elif kind == "numeric":
            blanks.append(models.NumericBlank(id=blank_id, **draw(_numeric_key_fields())))
        else:
            blanks.append(
                models.ChoiceBlank(id=blank_id, choices=draw(_scored_choices()))
            )
    pieces = [draw(_words())]
    for blank_id in blank_ids:
        pieces.extend([f"[^{blank_id}]", draw(_words())])
    fields = _base_question_kwargs(answer_body=True) | {"stem": st.just(" ".join(pieces))}
    base = draw(st.fixed_dictionaries(fields))
    return models.FillInQuestion(blanks=blanks, **base)


QUESTION_STRATEGIES: dict[
    QuestionType, Callable[[], st.SearchStrategy[models.Question]]
] = {
    "multiple-choice": multiple_choice_questions,
    "multiple-selection": multiple_selection_questions,
    "true-false": true_false_questions,
    "numeric": numeric_questions,
    "short-answer": short_answer_questions,
    "essay": essay_questions,
    "fill-in": fill_in_questions,
    "ordering": ordering_questions,
}
