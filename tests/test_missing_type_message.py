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
