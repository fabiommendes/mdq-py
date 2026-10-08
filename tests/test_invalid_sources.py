"""
`examples/invalid/**/*.mdq.md`: Markdown documents `load` must reject.

Each one's `.lint.json` lists every diagnostic `load` reports for it --
code, severity and path -- errors included. A `.yaml` sibling, when
present, is the same document written directly, and must report the
same diagnostics.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from mdq import load
from _corpus import (
    INVALID_MODEL_ONLY_PARSED,
    INVALID_PARSED,
    INVALID_SOURCES,
    INVALID_SYNTAX,
    parsed_sibling,
    relative_id,
)


def _lint_json(source: Path) -> Path:
    return source.with_name(source.name.removesuffix(".mdq.md") + ".lint.json")


def _diagnostics(path: Path) -> Counter:
    loaded = load(path)
    assert loaded.document is None, f"{path.name} loaded without an error"
    return Counter(
        json.dumps({"code": d.code, "severity": d.severity, "path": list(d.path)}, sort_keys=True)
        for d in loaded.diagnostics
    )


def _expected(source: Path) -> Counter:
    entries = json.loads(_lint_json(source).read_text(encoding="utf-8"))
    return Counter(json.dumps(entry, sort_keys=True) for entry in entries)


def test_there_are_invalid_sources() -> None:
    assert INVALID_SOURCES


@pytest.mark.parametrize("source", INVALID_SOURCES, ids=[relative_id(p) for p in INVALID_SOURCES])
def test_invalid_source_reports_its_lint_json(source: Path) -> None:
    assert _lint_json(source).exists(), f"{source.name} has no .lint.json"
    assert _diagnostics(source) == _expected(source)


@pytest.mark.parametrize("source", INVALID_SOURCES, ids=[relative_id(p) for p in INVALID_SOURCES])
def test_invalid_yaml_sibling_reports_the_same_diagnostics(source: Path) -> None:
    sibling = parsed_sibling(source)
    if not sibling.exists():
        pytest.skip("no .yaml sibling")
    assert _diagnostics(sibling) == _expected(source)


# ---------------------------------------------------------------------
# Invalid examples written directly as `.yaml`, with no Markdown source.
# They pin their diagnostics the same way, in a `.lint.json` of their own.
# ---------------------------------------------------------------------

INVALID_PARSED_ONLY = [
    path
    for path in INVALID_PARSED + INVALID_MODEL_ONLY_PARSED + INVALID_SYNTAX
    if not path.with_name(path.name.removesuffix(path.suffix) + ".mdq.md").exists()
]


def _parsed_lint_json(path: Path) -> Path:
    return path.with_name(path.name.removesuffix(path.suffix) + ".lint.json")


def test_there_are_invalid_parsed_only_examples() -> None:
    assert INVALID_PARSED_ONLY


@pytest.mark.parametrize(
    "path", INVALID_PARSED_ONLY, ids=[relative_id(p) for p in INVALID_PARSED_ONLY]
)
def test_invalid_parsed_only_example_reports_its_lint_json(path: Path) -> None:
    lint_json = _parsed_lint_json(path)
    assert lint_json.exists(), f"{path.name} has no .lint.json"
    entries = json.loads(lint_json.read_text(encoding="utf-8"))
    expected = Counter(json.dumps(entry, sort_keys=True) for entry in entries)
    assert _diagnostics(path) == expected
