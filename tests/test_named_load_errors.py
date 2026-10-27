"""
Error codes `load` reports when a document cannot become a model.

The corpus (`examples/invalid`) covers which documents fail with which code,
including the empty exam `start` (`exam-start-empty-string`). This module
keeps what the corpus does not record: the `schema-error` diagnostic keeps
the message of pydantic.
"""

from __future__ import annotations

from mdq import load


def test_schema_error_keeps_pydantics_message() -> None:
    [diagnostic] = load({"type": "essay"}).diagnostics
    assert diagnostic.code == "schema-error"
    assert diagnostic.message
