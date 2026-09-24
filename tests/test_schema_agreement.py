"""
Schema/model agreement (see "Schema/model agreement" in
dev/specs/to-do/loading-module.md).

Runtime JSON Schema validation goes away with `mdq.validator`; this test
is what replaces it as the guard against the schema and the pydantic
models drifting apart. It uses `jsonschema` directly against the bundled
schema (`mdq.scripts.schema_bundle`), and `mdq.load` for the model side.

Every document under `examples/valid/` -- every `.yaml`/`.json` file,
which already includes the `.yaml` sibling of each `.mdq.md` source, since
both live in the same directory -- must satisfy both sides. Every
document under `examples/invalid/` must fail both.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from mdq import load
from mdq.scripts.schema_bundle import TYPE_SCHEMAS, bundle_schemas
from mdq.testing import INVALID_PARSED, VALID_PARSED, relative_id

BUNDLE = bundle_schemas()


def _question_type(document: object) -> str | None:
    if not isinstance(document, dict):
        return None
    if "type" in document:
        return document["type"]
    if "questions" in document:
        return "exam"
    return None


def _schema_errors(document: dict) -> list[str]:
    question_type = _question_type(document)
    if question_type not in TYPE_SCHEMAS:
        return [f"document has no recognizable 'type' ({question_type!r})"]
    schema = {
        "$ref": f"#/$defs/{Path(TYPE_SCHEMAS[question_type]).stem}",
        "$defs": BUNDLE["$defs"],
    }
    validator = Draft202012Validator(schema)
    return [
        f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
        for e in validator.iter_errors(document)
    ]


def test_examples_dir_has_documents() -> None:
    assert VALID_PARSED
    assert INVALID_PARSED


@pytest.mark.parametrize(
    "path", VALID_PARSED, ids=[relative_id(p) for p in VALID_PARSED]
)
def test_valid_example_satisfies_schema_and_loads_cleanly(path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))

    schema_errors = _schema_errors(document)
    loaded = load(path)
    load_errors = [d for d in loaded.diagnostics if d.severity == "error"]

    if schema_errors and not load_errors:
        pytest.fail(
            f"{relative_id(path)}: rejected by the JSON Schema but accepted by "
            f"`load`:\n" + "\n".join(f"  - {e}" for e in schema_errors)
        )
    if load_errors and not schema_errors:
        pytest.fail(
            f"{relative_id(path)}: rejected by `load` but accepted by the JSON "
            f"Schema:\n" + "\n".join(f"  - {d.severity} {d.code}: {d.message}" for d in load_errors)
        )
    assert not schema_errors, (
        f"{relative_id(path)} lives under examples/valid/ but fails the schema:\n"
        + "\n".join(f"  - {e}" for e in schema_errors)
    )
    assert not load_errors, (
        f"{relative_id(path)} lives under examples/valid/ but `load` reports errors:\n"
        + "\n".join(f"  - {d.severity} {d.code}: {d.message}" for d in load_errors)
    )


@pytest.mark.parametrize(
    "path", INVALID_PARSED, ids=[relative_id(p) for p in INVALID_PARSED]
)
def test_invalid_example_fails_schema_and_load(path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))

    schema_errors = _schema_errors(document)
    loaded = load(path)
    load_errors = [d for d in loaded.diagnostics if d.severity == "error"]

    if not schema_errors and load_errors:
        pytest.fail(
            f"{relative_id(path)}: lives under examples/invalid/ and `load` "
            f"correctly rejects it, but it still satisfies the JSON Schema"
        )
    if schema_errors and not load_errors:
        pytest.fail(
            f"{relative_id(path)}: lives under examples/invalid/ and fails the "
            f"JSON Schema, but `load` accepts it with no errors"
        )
    assert schema_errors, (
        f"{relative_id(path)} lives under examples/invalid/ but satisfies the "
        f"bundled JSON Schema"
    )
    assert load_errors, (
        f"{relative_id(path)} lives under examples/invalid/ but `load` reports "
        f"no error diagnostic"
    )
