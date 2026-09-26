"""
Tests for the `.lint.json` corpus convention and its snapshot script (see
"Expected lint files (`.lint.json`)" in
dev/specs/to-do/loading-module.md).

ASSUMPTION (the spec names the script but not its exact CLI shape): the
snapshot script `mdq/scripts/lint_snapshot.py` exposes a
`main(argv: list[str]) -> int` entry point mirroring
`main` in the root `scripts/schema_bundle.py`, accepting `--root PATH` to point at a
corpus root (default: `examples/valid`) and `--overwrite PATH...` to
rewrite specifically-named `.lint.json` files. If the real interface
differs, only the snapshot-script tests below need updating -- the
`.lint.json` comparison tests do not depend on it.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from mdq import load
from mdq.testing import VALID_PARSED, VALID_SOURCES, relative_id

# ---------------------------------------------------------------------
# Shared helpers: computing / comparing a document's expected diagnostics
# ---------------------------------------------------------------------

_SOURCE_SUFFIXES = (".mdq.md", ".mdq", ".yaml", ".yml", ".json")


def _stem(doc_path: Path) -> str:
    name = doc_path.name
    for suffix in _SOURCE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return doc_path.stem


def _lint_json_path(doc_path: Path) -> Path:
    """`foo.mdq.md` and `foo.yaml` share `foo.lint.json`."""
    return doc_path.with_name(f"{_stem(doc_path)}.lint.json")


def _expected_diagnostics(doc_path: Path) -> list[dict]:
    lint_json = _lint_json_path(doc_path)
    if not lint_json.exists():
        return []
    return json.loads(lint_json.read_text(encoding="utf-8"))


def _actual_diagnostics(doc_path: Path) -> list[dict]:
    loaded = load(doc_path)
    return [
        {"code": d.code, "severity": d.severity, "path": list(d.path)}
        for d in loaded.diagnostics
        if d.severity != "error"
    ]


def _multiset(entries: list[dict]) -> Counter:
    return Counter(json.dumps(entry, sort_keys=True) for entry in entries)


def _assert_matches_lint_json(doc_path: Path) -> None:
    expected = _expected_diagnostics(doc_path)
    actual = _actual_diagnostics(doc_path)
    assert _multiset(actual) == _multiset(expected), (
        f"{doc_path.name}: diagnostics do not match {_lint_json_path(doc_path).name} "
        f"(as a multiset)\nexpected: {expected}\nactual:   {actual}"
    )


# ---------------------------------------------------------------------
# Self-contained mechanics: multiset comparison, missing file, and the
# md/yaml pair sharing one `.lint.json`.
# ---------------------------------------------------------------------

#: A malformed locale -- one default-level warning.
#:
#: (Previously a pair of duplicate choices; `duplicate-choice-id` and
#: `duplicate-choice-text` are `error` diagnostics raised by the models
#: now -- dev/specs/to-do/unique-ids.md -- so a document that trips them
#: never reaches the lint pass at all, and can no longer stand in for
#: "a document with a lint warning" here.)
DUPLICATE_TEXT_YAML = """\
type: essay
stem: Explique o efeito Coriolis.
locale: xx-99
"""

DUPLICATE_TEXT_MD = (
    "---\n"
    "locale: xx-99\n"
    "---\n"
    "\n"
    "Explique o efeito Coriolis.\n"
    "\n"
    "[essay]\n"
)

DUPLICATE_TEXT_LINT_JSON = [
    {"code": "malformed-locale", "severity": "warning", "path": ["locale"]},
]


#: Two independent warnings on the same document: a malformed locale and
#: a blank tag.
TWO_WARNINGS_YAML = """\
type: essay
stem: Explique o efeito Coriolis.
locale: xx-99
tags:
  - "   "
"""

TWO_WARNINGS_LINT_JSON = [
    {"code": "malformed-locale", "severity": "warning", "path": ["locale"]},
    {"code": "blank-tag", "severity": "warning", "path": ["tags", 0]},
]


def test_lint_json_multiset_ignores_order(tmp_path: Path) -> None:
    doc = tmp_path / "capital.yaml"
    doc.write_text(TWO_WARNINGS_YAML, encoding="utf-8")
    lint_json = tmp_path / "capital.lint.json"
    # `lint_document` would actually produce `blank-text-field` before
    # `duplicate-choice-text` -- written here in the opposite order to
    # prove the comparison does not care.
    lint_json.write_text(json.dumps(TWO_WARNINGS_LINT_JSON), encoding="utf-8")
    _assert_matches_lint_json(doc)


def test_lint_json_match_must_be_exact_as_a_multiset() -> None:
    # A trivial case proving the multiset comparison is order-independent
    # but not lossy: duplicating an entry changes the multiset.
    a = [{"code": "x", "severity": "warning", "path": []}]
    b = [{"code": "x", "severity": "warning", "path": []}] * 2
    assert _multiset(a) == _multiset(a)
    assert _multiset(a) != _multiset(b)


def test_missing_lint_json_expects_zero_diagnostics(tmp_path: Path) -> None:
    doc = tmp_path / "coriolis.mdq.md"
    doc.write_text("Explique o efeito Coriolis.\n\n[essay]\n", encoding="utf-8")
    # No coriolis.lint.json next to it.
    assert _expected_diagnostics(doc) == []
    _assert_matches_lint_json(doc)  # this document really produces none


def test_missing_lint_json_with_real_diagnostics_is_a_mismatch(tmp_path: Path) -> None:
    doc = tmp_path / "capital.yaml"
    doc.write_text(DUPLICATE_TEXT_YAML, encoding="utf-8")
    # No capital.lint.json -- but this document does warn.
    assert _actual_diagnostics(doc) != []
    with pytest.raises(AssertionError):
        _assert_matches_lint_json(doc)


def test_md_and_yaml_siblings_are_checked_against_the_same_lint_json(
    tmp_path: Path,
) -> None:
    (tmp_path / "capital.yaml").write_text(DUPLICATE_TEXT_YAML, encoding="utf-8")
    (tmp_path / "capital.mdq.md").write_text(DUPLICATE_TEXT_MD, encoding="utf-8")
    (tmp_path / "capital.lint.json").write_text(
        json.dumps(DUPLICATE_TEXT_LINT_JSON), encoding="utf-8"
    )
    _assert_matches_lint_json(tmp_path / "capital.yaml")
    _assert_matches_lint_json(tmp_path / "capital.mdq.md")


# ---------------------------------------------------------------------
# The real corpus: every valid example either matches its `.lint.json`
# or produces no diagnostics (the "Done means" acceptance criterion).
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", VALID_PARSED, ids=[relative_id(p) for p in VALID_PARSED]
)
def test_valid_parsed_example_matches_its_lint_json(path: Path) -> None:
    _assert_matches_lint_json(path)


@pytest.mark.parametrize(
    "path", VALID_SOURCES, ids=[relative_id(p) for p in VALID_SOURCES]
)
def test_valid_source_example_matches_its_lint_json(path: Path) -> None:
    _assert_matches_lint_json(path)


# ---------------------------------------------------------------------
# Snapshot script: mdq/scripts/lint_snapshot.py
# ---------------------------------------------------------------------

lint_snapshot = pytest.importorskip("mdq.scripts.lint_snapshot")


def _write_corpus(tmp_path: Path) -> Path:
    (tmp_path / "capital.yaml").write_text(DUPLICATE_TEXT_YAML, encoding="utf-8")
    return tmp_path


def test_snapshot_writes_a_missing_lint_json(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    lint_json = root / "capital.lint.json"
    assert not lint_json.exists()

    code = lint_snapshot.main(["--root", str(root)])

    assert code == 0
    assert lint_json.exists()
    assert _multiset(json.loads(lint_json.read_text(encoding="utf-8"))) == _multiset(
        DUPLICATE_TEXT_LINT_JSON
    )


def test_snapshot_never_writes_a_document_with_no_diagnostics(tmp_path: Path) -> None:
    root = tmp_path
    (root / "coriolis.mdq.md").write_text(
        "Explique o efeito Coriolis.\n\n[essay]\n", encoding="utf-8"
    )
    code = lint_snapshot.main(["--root", str(root)])
    assert code == 0
    assert not (root / "coriolis.lint.json").exists()


def test_snapshot_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    lint_json = root / "capital.lint.json"
    stale_content = json.dumps([{"code": "stale", "severity": "warning", "path": []}])
    lint_json.write_text(stale_content, encoding="utf-8")

    code = lint_snapshot.main(["--root", str(root)])

    assert code != 0
    assert lint_json.read_text(encoding="utf-8") == stale_content


def test_snapshot_reports_the_difference_for_a_stale_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    root = _write_corpus(tmp_path)
    lint_json = root / "capital.lint.json"
    lint_json.write_text(
        json.dumps([{"code": "stale", "severity": "warning", "path": []}]),
        encoding="utf-8",
    )

    lint_snapshot.main(["--root", str(root)])

    output = capsys.readouterr().out + capsys.readouterr().err
    assert "capital.lint.json" in output


def test_snapshot_matching_existing_file_exits_zero(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    lint_json = root / "capital.lint.json"
    lint_json.write_text(json.dumps(DUPLICATE_TEXT_LINT_JSON), encoding="utf-8")

    code = lint_snapshot.main(["--root", str(root)])

    assert code == 0
    assert json.loads(lint_json.read_text(encoding="utf-8")) == DUPLICATE_TEXT_LINT_JSON


def test_snapshot_overwrite_rewrites_only_the_given_files(tmp_path: Path) -> None:
    root = tmp_path
    (root / "capital.yaml").write_text(DUPLICATE_TEXT_YAML, encoding="utf-8")
    (root / "outro.yaml").write_text(DUPLICATE_TEXT_YAML, encoding="utf-8")
    capital_lint = root / "capital.lint.json"
    outro_lint = root / "outro.lint.json"
    stale = json.dumps([{"code": "stale", "severity": "warning", "path": []}])
    capital_lint.write_text(stale, encoding="utf-8")
    outro_lint.write_text(stale, encoding="utf-8")

    code = lint_snapshot.main(
        ["--root", str(root), "--overwrite", str(capital_lint)]
    )

    # The named file is rewritten to match reality...
    assert _multiset(
        json.loads(capital_lint.read_text(encoding="utf-8"))
    ) == _multiset(DUPLICATE_TEXT_LINT_JSON)
    # ...but the other stale file is left untouched, so the run as a
    # whole still reports a difference.
    assert outro_lint.read_text(encoding="utf-8") == stale
    assert code != 0


def test_there_is_no_flag_that_rewrites_every_file(tmp_path: Path) -> None:
    """`--overwrite` takes explicit paths; there is no "overwrite all" flag."""
    root = tmp_path
    (root / "capital.yaml").write_text(DUPLICATE_TEXT_YAML, encoding="utf-8")
    (root / "capital.lint.json").write_text(
        json.dumps([{"code": "stale", "severity": "warning", "path": []}]),
        encoding="utf-8",
    )

    code = lint_snapshot.main(["--root", str(root), "--overwrite"])

    # `--overwrite` with no paths rewrites nothing -- it is not a synonym
    # for "overwrite everything".
    assert code != 0
    assert "stale" in (root / "capital.lint.json").read_text(encoding="utf-8")
