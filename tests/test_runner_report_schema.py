"""
Agreement of `RunnerReport` with `schema/runner-report.yaml`.

The report is not a document that `mdq.load` reads, so the agreement test of
the documents (`test_schema_agreement.py`) does not cover it. Here a valid
report is changed one field at a time, and the JSON Schema and the model must
accept or reject the result together.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from _corpus import MDQ_ROOT
from mdq import models

SCHEMA = yaml.safe_load((MDQ_ROOT / "schema" / "runner-report.yaml").read_text("utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: A report that has every field of the schema.
FULL: dict[str, Any] = {
    "version": 1,
    "status": "completed",
    "cases": [
        {
            "source": 0,
            "line": 3,
            "verdict": "fail",
            "id": "test_a",
            "message": "m",
            "expected": "1",
            "actual": "2",
            "stdout": {"text": "o", "truncated": False},
            "stderr": {"text": "e"},
            "duration": 0.5,
            "memory": 1024,
            "meta": {"k": [None, 1]},
        }
    ],
    "build": "warning",
    "message": "ok",
    "runner": {"name": "r", "version": "1", "language": "python", "toolchainVersion": "3.13"},
    "hashes": {"submission": DIGEST, "sources": [DIGEST]},
    "meta": {"coverage": None},
}

#: JSON values that a field can get, whatever its type.
VALUES: list[Any] = [
    None, True, False, 0, 1, 2, -1, 5.0, 1.0, 0.0, -0.0, 1.5, 1e300, "", "x", "1",
    DIGEST, DIGEST.upper(), DIGEST + "0", "completed", "pass", [], {}, {"text": "t"},
    [DIGEST], [""], ["x"], {"a": 1},
]  # fmt: skip


def _paths(node: Any, prefix: tuple[str | int, ...] = ()) -> list[tuple[str | int, ...]]:
    """Every key of the report, as a path, but not what is inside a `meta`."""
    found: list[tuple[str | int, ...]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.append((*prefix, key))
            if key != "meta":
                found.extend(_paths(value, (*prefix, key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, dict):
                found.extend(_paths(value, (*prefix, index)))
            else:
                found.append((*prefix, index))
    return found


def _set(report: dict[str, Any], path: tuple[str | int, ...], value: Any) -> dict[str, Any]:
    changed = copy.deepcopy(report)
    node: Any = changed
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return changed


def _drop(report: dict[str, Any], path: tuple[str | int, ...]) -> dict[str, Any]:
    changed = copy.deepcopy(report)
    node: Any = changed
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return changed


def _agree(report: Any) -> None:
    by_schema = VALIDATOR.is_valid(report)
    try:
        models.RunnerReport.model_validate(report, by_alias=True, by_name=False)
        by_model = True
    except ValidationError:
        by_model = False
    assert by_model == by_schema, (
        f"{report!r}: the schema says {by_schema}, the model says {by_model}"
    )


def test_the_full_report_is_valid() -> None:
    assert VALIDATOR.is_valid(FULL)
    _agree(FULL)


@pytest.mark.parametrize("path", _paths(FULL), ids=lambda p: ".".join(map(str, p)))
def test_a_field_set_to_any_json_value(path: tuple[str | int, ...]) -> None:
    for value in VALUES:
        _agree(_set(FULL, path, value))


@pytest.mark.parametrize("path", _paths(FULL), ids=lambda p: ".".join(map(str, p)))
def test_a_field_removed(path: tuple[str | int, ...]) -> None:
    if isinstance(path[-1], int):
        return
    _agree(_drop(FULL, path))


@pytest.mark.parametrize(
    "report",
    [
        {"status": "completed", "cases": []},
        {"status": "completed"},
        {"cases": []},
        {"status": "completed", "cases": [], "extra": 1},
        {"status": "completed", "cases": [{"source": 0, "line": 1, "verdict": "pass", "x": 1}]},
        {"status": "completed", "cases": [{"source": 0.0, "line": 5.0, "verdict": "pass"}]},
        {"status": "completed", "cases": [{"source": 0.5, "line": 1, "verdict": "pass"}]},
        {"version": 1.0, "status": "build-error", "cases": []},
        {"version": 2, "status": "build-error", "cases": []},
        {"status": "runner-error", "cases": [], "runner": {"version": "1"}},
        {"status": "runner-error", "cases": [], "runner": {"name": "r", "toolchain_version": "1"}},
        {"status": "completed", "cases": None},
        [],
        "report",
        None,
    ],
)
def test_other_documents(report: Any) -> None:
    _agree(report)
