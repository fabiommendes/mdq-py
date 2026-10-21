"""essay.md, "Answer key": extent, heading forms and the `content` rename."""

import mdq
import pytest

HEAD = "Explique o ciclo da água.\n\n[essay]\n\n"


def _load(src: str) -> mdq.Loaded:
    return mdq.load(src, kind="question")


def _errors(loaded: mdq.Loaded) -> list[tuple[str, tuple]]:
    return [(d.code, tuple(d.path)) for d in loaded.diagnostics if d.severity == "error"]


def test_setext_h2_starts_the_answer_key() -> None:
    loaded = _load(HEAD + "[answer-key]\n------------\n\nEvaporação.\n")
    assert _errors(loaded) == []
    assert loaded.document.answer_key == "Evaporação."


def test_inner_h2_does_not_end_the_answer_key() -> None:
    loaded = _load(HEAD + "## [answer-key]\n\nA.\n\n## Critérios\n\nB.\n")
    assert _errors(loaded) == []
    assert loaded.document.answer_key == "A.\n\n## Critérios\n\nB."


def test_h1_in_the_answer_key_is_forbidden() -> None:
    loaded = _load(HEAD + "## [answer-key]\n\nA.\n\n# Título\n")
    assert _errors(loaded) == [("forbidden-block-element", ("answerKey",))]


def test_h1_in_the_answer_key_of_a_model_is_forbidden() -> None:
    loaded = mdq.load(
        {"type": "essay", "stem": "Q?", "answerKey": "Setext\n======"}, kind="question"
    )
    assert _errors(loaded) == [("forbidden-block-element", ("answerKey",))]


def test_second_answer_key_is_a_parse_error() -> None:
    loaded = _load(HEAD + "## [answer-key]\n\nA.\n\n## [answer-key]\n\nB.\n")
    assert _errors(loaded) == [("parse-error", ())]


def test_empty_answer_key_is_absent() -> None:
    loaded = _load(HEAD + "## [answer-key]\n")
    assert _errors(loaded) == []
    assert loaded.document.answer_key is None
    assert "missing-answer-key" in [d.code for d in loaded.diagnostics]


def test_essay_is_a_valid_slug() -> None:
    loaded = _load("[essay] Descreva o Pantanal.\n\n[essay]\n")
    assert _errors(loaded) == []
    assert loaded.document.id == "essay"


def test_paragraph_with_only_the_tag_is_never_a_slug() -> None:
    loaded = _load("[essay]\n")
    assert _errors(loaded) == [("parse-error", ())]


@pytest.mark.parametrize("value", ["code", "text", "plain"])
def test_input_is_an_invalid_frontmatter_field(value: str) -> None:
    loaded = _load(f"---\ninput: {value}\n---\n\nQ?\n\n[essay]\n")
    assert _errors(loaded) == [("invalid-frontmatter-field", ("input",))]
