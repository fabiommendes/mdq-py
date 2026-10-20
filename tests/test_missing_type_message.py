"""
A question with no `type`, or an exam entry that is neither a question
nor an include block, gets a clear `schema-error` message instead of
pydantic's discriminator message.
"""

from __future__ import annotations

import pytest

from mdq import load


def _messages(doc: dict) -> list[tuple[str, tuple, str]]:
    loaded = load(doc)
    assert loaded.document is None
    return [(d.code, d.path, d.message) for d in loaded.diagnostics]


def _exam(entry: dict) -> dict:
    return {"type": "exam", "title": "Biomas", "questions": [entry]}


@pytest.mark.parametrize(
    ("key", "hint"),
    [
        ("include-all", "includeAll"),
        ("Include", "include"),
    ],
)
def test_exam_entry_with_misspelled_include_key(key: str, hint: str) -> None:
    [(code, path, message)] = _messages(_exam({key: "biome"}))
    assert (code, path) == ("schema-error", ("questions", 0))
    assert message.startswith(
        "an entry of `questions` needs a `type`, or an `include` or `includeAll` key"
    )
    assert f"did you mean `{hint}` instead of `{key}`?" in message


def test_exam_entry_without_hint() -> None:
    [(_, _, message)] = _messages(_exam({"stem": "Quanto?"}))
    assert message.endswith("`includeAll` key")
    assert "discriminator" not in message


def test_question_without_type() -> None:
    [(code, path, message)] = _messages({"stem": "Descreva o Cerrado."})
    assert (code, path) == ("schema-error", ())
    assert message == "a question needs a `type`"


def _exam_md(block: str) -> str:
    return f"# Biomas\n\n{block}"


def _invalid_field(loaded) -> list:
    return [d for d in loaded.diagnostics if d.code == "invalid-frontmatter-field"]


def test_md_block_with_misspelled_include_key_and_no_body() -> None:
    loaded = load(_exam_md("---\ninclude-all: biome\n---\n"), format="mdq")
    assert loaded.document is None
    [d] = loaded.diagnostics
    assert d.code == "parse-error"
    assert d.severity == "error"
    assert d.message.endswith("(did you mean `includeAll` instead of `include-all`?)")


def test_md_block_with_misspelled_include_key_and_body() -> None:
    source = _exam_md("---\ninclude_all: biome\n---\n\nQual bioma?\n\n[essay]\n")
    loaded = load(source, format="mdq")
    assert loaded.document is None
    [d] = _invalid_field(loaded)
    assert (d.code, d.severity) == ("invalid-frontmatter-field", "error")
    assert d.path == ("questions", 0, "include_all")
    assert "did you mean `includeAll` instead of `include_all`?" in d.message


def test_md_block_without_include_like_key_has_no_hint() -> None:
    loaded = load(_exam_md("---\nautor: Ana\n---\n\nQual bioma?\n\n[essay]\n"), format="mdq")
    [d] = _invalid_field(loaded)
    assert "did you mean" not in d.message


def test_md_block_with_exact_include_key_has_no_hint() -> None:
    loaded = load(_exam_md("---\ninclude: q1\n---\n"), format="mdq")
    assert all("did you mean" not in d.message for d in loaded.diagnostics)
