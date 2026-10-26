"""
Error codes `load` reports when a document cannot become a model.

The corpus (`examples/invalid`) covers which documents fail with which code.
This module keeps what the corpus does not record:

* Q6: the `schema-error` diagnostic keeps the message of pydantic.
* Q7: an empty exam `start` is `malformed-start` -- exam.md, "Duration and
  Start Time".
"""

from __future__ import annotations

from mdq import load


def test_schema_error_keeps_pydantics_message() -> None:
    [diagnostic] = load({"type": "essay"}).diagnostics
    assert diagnostic.code == "schema-error"
    assert diagnostic.message


def test_empty_start_is_malformed() -> None:
    loaded = load({"type": "exam", "title": "Prova de Geografia", "questions": [], "start": ""})
    assert loaded.document is None
    assert [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"] == [
        ("malformed-start", ("start",))
    ]
