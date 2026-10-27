"""
A question with no `type`, or an exam entry that is neither a question
nor an include block, gets a clear `schema-error` message instead of
pydantic's discriminator message.

Which documents fail, with which code and path, is covered by the invalid
corpus (`exam-entry-*`, `question-missing-type`, `exam-*misspelled-include-all*`).
This module keeps the message text.
"""

from __future__ import annotations

import pytest

from mdq import load


def _messages(doc: dict) -> list[str]:
    loaded = load(doc)
    assert loaded.document is None
    return [d.message for d in loaded.diagnostics]


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
    [message] = _messages(_exam({key: "biome"}))
    assert message.startswith(
        "an entry of `questions` needs a `type`, or an `include` or `includeAll` key"
    )
    assert f"did you mean `{hint}` instead of `{key}`?" in message


def test_exam_entry_without_hint() -> None:
    [message] = _messages(_exam({"stem": "Quanto?"}))
    assert message.endswith("`includeAll` key")
    assert "discriminator" not in message


def test_question_without_type() -> None:
    assert _messages({"stem": "Descreva o Cerrado."}) == ["a question needs a `type`"]


def _exam_md(block: str) -> str:
    return f"# Biomas\n\n{block}"


def test_md_block_with_misspelled_include_key_and_no_body() -> None:
    loaded = load(_exam_md("---\ninclude-all: biome\n---\n"), format="mdq")
    [d] = loaded.diagnostics
    assert d.message.endswith("(did you mean `includeAll` instead of `include-all`?)")


def test_md_block_with_misspelled_include_key_and_body() -> None:
    source = _exam_md("---\ninclude_all: biome\n---\n\nQual bioma?\n\n[essay]\n")
    [d] = load(source, format="mdq").diagnostics
    assert "did you mean `includeAll` instead of `include_all`?" in d.message


def test_md_block_without_include_like_key_has_no_hint() -> None:
    loaded = load(_exam_md("---\nautor: Ana\n---\n\nQual bioma?\n\n[essay]\n"), format="mdq")
    [d] = [d for d in loaded.diagnostics if d.code == "invalid-frontmatter-field"]
    assert "did you mean" not in d.message


def test_md_block_with_exact_include_key_has_no_hint() -> None:
    loaded = load(_exam_md("---\ninclude: q1\n---\n"), format="mdq")
    assert all("did you mean" not in d.message for d in loaded.diagnostics)
