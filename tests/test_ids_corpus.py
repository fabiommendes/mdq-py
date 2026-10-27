"""
`examples/valid/**/*.ids.yaml`: the ids a document gets from `with_ids()`.

Each file sits next to a `.mdq.md` and/or a `.yaml` of the same name, and
both must give the ids it lists (docs/exam.md, "Question ids";
docs/question-types/multiple-choice.md, "Choice ids"). Keys:

* `id`: the id of the question.
* `choices`: the ids of the choices, in order.
* `blanks`: fill-in only, a blank id -> the ids of its choices.
* `questions`: exam only, the ids of its questions, in order.

A key that is absent is not checked.

The files pin the derivation of mdq-py and mdq-js, not the spec: the spec
leaves the derived ids implementation-defined. When two texts give the same
slug, the texts are processed in code point order of the raw text (not by
position), and the first one takes the bare slug. A later one falls back to
its full slug, then to the full slug with `-2`, `-3`, ...
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from mdq import load
from mdq.models import Exam
from _corpus import SOURCE_SUFFIX, VALID_DIR, relative_id

IDS_FILES = sorted(VALID_DIR.rglob("*.ids.yaml"))


def _documents(ids_file: Path) -> list[Path]:
    stem = ids_file.name.removesuffix(".ids.yaml")
    siblings = [ids_file.with_name(stem + SOURCE_SUFFIX), ids_file.with_name(stem + ".yaml")]
    return [path for path in siblings if path.exists()]


def _ids_of(document: Any) -> dict[str, Any]:
    """The ids of an addressable document, in the shape of an `.ids.yaml`."""
    if isinstance(document, Exam):
        return {"questions": [question.id for question in document.questions]}
    ids: dict[str, Any] = {"id": document.id}
    if getattr(document, "choices", None) is not None:
        ids["choices"] = [choice.id for choice in document.choices]
    blanks = {
        blank.id: [choice.id for choice in blank.choices]
        for blank in getattr(document, "blanks", None) or []
        if getattr(blank, "choices", None) is not None
    }
    if blanks:
        ids["blanks"] = blanks
    return ids


def test_there_are_ids_files() -> None:
    assert IDS_FILES


@pytest.mark.parametrize("ids_file", IDS_FILES, ids=[relative_id(p) for p in IDS_FILES])
def test_with_ids_gives_the_listed_ids(ids_file: Path) -> None:
    expected = yaml.safe_load(ids_file.read_text(encoding="utf-8"))
    documents = _documents(ids_file)
    assert documents, f"{ids_file.name} has no document next to it"
    for path in documents:
        loaded = load(path, ids="fill")
        assert loaded.document is not None, (path.name, loaded.diagnostics)
        actual = _ids_of(loaded.document)
        assert {key: actual.get(key) for key in expected} == expected, path.name
