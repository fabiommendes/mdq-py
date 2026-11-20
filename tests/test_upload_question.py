"""`matches_extensions` and the parts of `UploadQuestion` the corpus leaves out."""

from __future__ import annotations

import pytest

import mdq
from mdq.models import UploadQuestion, matches_extensions, max_size_bytes


def _question(**fields: object) -> UploadQuestion:
    return UploadQuestion(stem="Envie.", **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("extensions", "name", "expected"),
    [
        (None, "qualquer coisa", True),
        ([".pdf"], "Relatório.PDF", True),
        ([".pdf"], ".pdf", False),
        ([".pdf"], "a.pdf", True),
        ([".tar.gz"], "dados.tar.gz", True),
        ([".tar.gz"], "dados.gz", False),
        ([".gz"], "dados.tar.gz", True),
        ([".kml"], "mapa.KML", False),  # Kelvin sign is not K
        ([".kml"], "mapa.KML", True),
        ([".pdf", ".png"], "a.PNG", True),
        ([".pdf", ".png"], "a.gif", False),
    ],
)
def test_matches_extensions(extensions: list[str] | None, name: str, expected: bool) -> None:
    fields = {} if extensions is None else {"extensions": extensions}
    model = _question(**fields)
    assert matches_extensions(model, name) is expected
    assert matches_extensions(model.public(), name) is expected


def test_max_size_bytes_none_without_limit() -> None:
    assert max_size_bytes(_question()) is None


@pytest.mark.parametrize(
    "fields",
    [
        {"maxFiles": True},
        {"maxSize": True},
        {"maxSize": "5 mb"},
        {"maxSize": "5 MB\n"},
        {"extensions": [".pdf", ".pdf"]},
        {"extensions": [".PDF"]},
        {"extensions": []},
    ],
)
def test_invalid_fields_are_schema_errors(fields: dict[str, object]) -> None:
    loaded = mdq.load({"type": "upload", "stem": "Envie.", **fields}, kind="question")
    assert any(d.code == "schema-error" for d in loaded.diagnostics)


def test_render_frontmatter() -> None:
    question = _question(max_files=2, max_size="5 MB", extensions=[".pdf"])
    text = question.render()
    assert "[upload]" in text
    assert "maxFiles: 2" in text and "5 MB" in text


def test_correct_responses_empty_with_answer_key() -> None:
    assert _question(answer_key="Chave").correct_responses() == []
