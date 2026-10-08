"""
Parser and render side of `unmatched`, `incorrectFeedback` and the
questions with no pattern (docs/question-types/short-answer.md "Frontmatter",
"Block with no pattern", "Grading"/"Examples"; fill-in.md "Frontmatter").
"""

from __future__ import annotations

from typing import Any

import pytest
from _corpus import EXAMPLES_ROOT, INVALID_DIR, parsed_sibling

import mdq
from mdq import models

VALID = EXAMPLES_ROOT / "valid"


def _load(source: str) -> mdq.Loaded:
    return mdq.load(source, kind="question")


def _errors(loaded: mdq.Loaded) -> list[mdq.Diagnostic]:
    return [d for d in loaded.diagnostics if d.severity == "error"]


def _codes(loaded: mdq.Loaded) -> list[str]:
    return [d.code for d in loaded.diagnostics]


def _roundtrip(question: Any) -> Any:
    loaded = _load(str(question))
    assert _errors(loaded) == []
    return loaded.document


def _frontmatter_block(text: str) -> str:
    return text.split("\n---\n", 1)[0] if text.startswith("---\n") else ""


#
# AC1: parser
#
@pytest.mark.parametrize("value", ["manual", "incorrect"])
def test_unmatched_in_frontmatter_loads(value: str) -> None:
    loaded = _load(
        f"---\nunmatched: {value}\n---\n\nQual é a capital?\n\n[short-answer]: Brasília\n"
    )
    assert _errors(loaded) == []
    assert "unknown-frontmatter-key" not in _codes(loaded)
    assert loaded.document.unmatched == value


def test_incorrect_feedback_in_frontmatter_loads() -> None:
    source = "---\nincorrectFeedback: Tente de novo.\n---\n\nQual é a capital?\n\n[short-answer]: Brasília\n"
    loaded = _load(source)
    assert _errors(loaded) == []
    assert "unknown-frontmatter-key" not in _codes(loaded)
    assert loaded.document.incorrect_feedback == "Tente de novo."


def test_unmatched_and_incorrect_feedback_default_to_none() -> None:
    document = _load("Qual é a capital?\n\n[short-answer]: Brasília\n").document
    assert document.unmatched is None
    assert document.incorrect_feedback is None


def test_open_ended_in_markdown_frontmatter_is_an_unknown_key() -> None:
    """Like any unknown key of a Markdown frontmatter: a warning, and it is dropped."""
    source = (
        "---\nopenEnded: true\n---\n\nQual é a capital?\n\n[short-answer]: Brasília\n"
    )
    loaded = _load(source)
    assert _errors(loaded) == []
    assert ("unknown-frontmatter-key", ("openEnded",)) in [
        (d.code, tuple(d.path)) for d in loaded.diagnostics
    ]
    assert "openEnded" not in loaded.document.to_dict()


@pytest.mark.parametrize("tag", ["[short-answer]:", "[short-answer/accept]:"])
def test_block_with_no_pattern_gives_no_accept_and_no_open_ended(tag: str) -> None:
    source = f"Descreva o bioma Cerrado.\n\n{tag}\n"
    loaded = _load(source)
    assert _errors(loaded) == []
    assert loaded.document.accept is None
    document = loaded.document.to_dict()
    assert "accept" not in document
    assert "openEnded" not in document


FILL_STEM = "O bioma [^bioma] cobre o Brasil central e o rio [^rio] banha Manaus.\n\n"


def test_fill_in_unmatched_in_frontmatter_loads() -> None:
    source = (
        "---\nunmatched: manual\n---\n\n"
        + FILL_STEM
        + "[^bioma/short-answer]: Cerrado\n\n[^rio/short-answer]: Negro\n"
    )
    loaded = _load(source)
    assert _errors(loaded) == []
    assert "unknown-frontmatter-key" not in _codes(loaded)
    assert loaded.document.unmatched == "manual"


def test_fill_in_blank_with_no_pattern_has_no_accept() -> None:
    source = FILL_STEM + "[^bioma/short-answer]:\n\n[^rio/short-answer]: Negro\n"
    loaded = _load(source)
    assert _errors(loaded) == []
    blank = loaded.document.blanks[0]
    assert blank.accept is None
    assert "openEnded" not in loaded.document.to_dict()["blanks"][0]


#
# The six examples of short-answer.md "Examples" (Grading)
#
_STEM = "What is the capital of Brazil?\n\n"
EXAMPLES = {
    "automatic": ("[short-answer]: Brasília\n", "automatic"),
    "incorrect-feedback": (
        "---\nincorrectFeedback: This city was never the capital.\n---\n\n"
        + _STEM
        + "[short-answer]: Brasília\n\n[short-answer/reject]:\n"
        "* Rio de Janeiro\n  > It was the capital until 1960.\n",
        "automatic",
    ),
    "semi-accept-reject": (
        "---\nunmatched: manual\n---\n\nName a biome of central Brazil.\n\n"
        "[short-answer]:\n* Cerrado\n* Pantanal\n\n[short-answer/reject]:\n"
        "* Savana\n  > Savanna is the general term. Name the Brazilian biome.\n",
        "semi-automatic",
    ),
    "semi-accept-only": (
        "---\nunmatched: manual\n---\n\nName a biome of central Brazil.\n\n"
        "[short-answer]:\n* Cerrado\n* Pantanal\n",
        "semi-automatic",
    ),
    "semi-reject-only": (
        "Name a biome of central Brazil.\n\n[short-answer]:\n\n[short-answer/reject]:\n"
        "* Savana\n  > Savanna is the general term. Name the Brazilian biome.\n",
        "semi-automatic",
    ),
    "manual": ("Name a biome of central Brazil.\n\n[short-answer]:\n", "manual"),
}


@pytest.mark.parametrize("name", EXAMPLES)
def test_grading_example_loads_without_errors_and_round_trips(name: str) -> None:
    source, automation = EXAMPLES[name]
    if name == "automatic":
        source = _STEM + source
    loaded = _load(source)
    assert _errors(loaded) == []
    assert "unknown-frontmatter-key" not in _codes(loaded)
    question = loaded.document
    assert question.automation == automation
    assert _roundtrip(question) == question


@pytest.mark.parametrize(
    "name",
    ["manual", "semi-automatic", "reject-only", "accept-reject"],
)
def test_corpus_markdown_matches_its_yaml_sibling(name: str) -> None:
    source = VALID / "short-answer" / f"{name}.mdq.md"
    from_md = mdq.load(source, kind="question")
    from_yaml = mdq.load(parsed_sibling(source), kind="question")
    assert _errors(from_md) == []
    assert from_md.document == from_yaml.document


def test_corpus_fill_in_unmatched_manual_matches_its_yaml_sibling() -> None:
    source = VALID / "fill-in" / "unmatched-manual.mdq.md"
    from_md = mdq.load(source, kind="question")
    assert _errors(from_md) == []
    assert (
        from_md.document == mdq.load(parsed_sibling(source), kind="question").document
    )
    assert from_md.document.unmatched == "manual"


@pytest.mark.parametrize(
    "name",
    ["short-answer-unknown-unmatched.yaml", "short-answer-automation-field.yaml"],
)
def test_invalid_corpus_documents_are_rejected(name: str) -> None:
    assert _errors(mdq.load(INVALID_DIR / name, kind="question"))


#
# AC2: render
#
def _sa(**fields: Any) -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(stem="Qual é a capital do Brasil?", **fields)


@pytest.mark.parametrize(
    ("key", "field", "value"),
    [
        ("unmatched", "unmatched", "manual"),
        ("incorrectFeedback", "incorrect_feedback", "Tente de novo."),
    ],
)
def test_set_field_is_written_to_the_frontmatter_and_round_trips(
    key: str, field: str, value: str
) -> None:
    question = _sa(accept=["Brasília"], **{field: value})
    assert key in _frontmatter_block(str(question))
    assert _roundtrip(question) == question


def test_unset_fields_are_omitted_from_the_render() -> None:
    text = str(_sa(accept=["Brasília"]))
    assert "unmatched" not in text
    assert "incorrectFeedback" not in text


@pytest.mark.parametrize(
    "fields", [{}, {"unmatched": "manual"}, {"unmatched": "incorrect"}]
)
def test_question_with_no_accept_renders_an_empty_block(fields: dict) -> None:
    question = _sa(**fields)
    text = str(question)
    assert text.rstrip("\n").endswith("[short-answer]:")
    assert "openEnded" not in text
    assert _roundtrip(question) == question


def test_reject_only_question_renders_an_empty_accept_block_and_round_trips() -> None:
    question = _sa(
        reject=[models.AnswerPattern(pattern="Rio", feedback="Foi até 1960.")]
    )
    text = str(question)
    assert "[short-answer]:\n\n[short-answer/reject]:" in text
    assert _roundtrip(question) == question


@pytest.mark.parametrize(
    "accept",
    [
        ["*"],
        ["*", "Brasília"],
        [models.AnswerPattern(pattern="*", feedback="Isso mesmo.")],
    ],
    ids=["single", "list", "feedback"],
)
def test_asterisk_pattern_renders_without_backticks_and_round_trips(
    accept: list,
) -> None:
    question = _sa(accept=accept)
    text = str(question)
    assert "`" not in text
    assert ("[short-answer]: *" in text) or ("* *" in text)
    assert _roundtrip(question) == question


def test_literal_backtick_asterisk_keeps_its_backticks() -> None:
    question = _sa(accept=["`*`"])
    assert "[short-answer]: `*`" in str(question)
    assert _roundtrip(question) == question


def test_render_never_writes_open_ended() -> None:
    for question in (_sa(), _sa(accept=["Brasília"]), _sa(reject=["Rio"])):
        assert "openEnded" not in str(question)


def test_fill_in_unmatched_round_trips() -> None:
    question = models.FillInQuestion(
        stem="O rio [^rio] banha Manaus.",
        unmatched="manual",
        blanks=[models.ShortAnswerBlank(id="rio", accept=["Negro"])],
    )
    assert "unmatched" in _frontmatter_block(str(question))
    assert _roundtrip(question) == question


def test_fill_in_without_unmatched_omits_it() -> None:
    question = models.FillInQuestion(
        stem="O rio [^rio] banha Manaus.",
        blanks=[models.ShortAnswerBlank(id="rio", accept=["Negro"])],
    )
    assert "unmatched" not in str(question)


def test_fill_in_blank_with_no_accept_renders_an_empty_block_and_round_trips() -> None:
    question = models.FillInQuestion(
        stem="O rio [^rio] banha Manaus.",
        blanks=[models.ShortAnswerBlank(id="rio")],
    )
    assert "[^rio/short-answer]:" in str(question)
    assert "openEnded" not in str(question)
    assert _roundtrip(question) == question
