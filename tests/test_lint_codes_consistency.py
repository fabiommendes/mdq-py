"""
Tests for the "Tests" section of `dev/specs/to-do/rule-conformance.md`:

    A test that every code in `docs/lint-codes.md` is produced by some
    corpus example, and every code the implementation produces is in
    `docs/lint-codes.md`.

No such test existed before this file (checked with `grep -rl
lint-codes mdq-py/tests/`), so this is new, not an extension.

`docs/lint-codes.md` has two tables: a `warning`/`info` reference table,
and an "## Errors" table for codes now raised as pydantic errors. Both
are parsed from the same simple "| `code` | ..." row shape.

The corpus side deliberately does NOT scan plain `examples/invalid/`
(only `examples/valid/` and `examples/invalid/model-only/`):
`examples/invalid/` exists to fail JSON Schema, so `load` reports it
through pydantic's own generic error `type`s (`missing`,
`string_too_short`, `value_error`, ...) before any lint code or named
model-error code ever runs -- `docs/lint-codes.md`'s own module
docstring excludes exactly this category ("a parse failure, a pydantic
validation error, ... which are not lint rules and are not listed
here"). `examples/invalid/model-only/` is schema-*valid* by
construction (see `mdq/testing.py`), so every `error` it produces is a
genuine named model-error code, not schema noise.

This intentionally does not distinguish *which* document exercises a
code, only whether at least one does -- matching the spec's wording
("is produced by some corpus example").
"""

from __future__ import annotations

import re

from mdq import load
from _corpus import INVALID_MODEL_ONLY_PARSED, INVALID_PARSED, MDQ_ROOT, VALID_PARSED

_LINT_CODES_MD = MDQ_ROOT / "docs" / "lint-codes.md"
_ROW_RE = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|")


def _documented_codes() -> tuple[set[str], set[str]]:
    """Return `(warning_or_info_codes, error_codes)` from lint-codes.md."""
    warning_or_info: set[str] = set()
    errors: set[str] = set()
    in_errors_section = False
    for line in _LINT_CODES_MD.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Errors"):
            in_errors_section = True
            continue
        match = _ROW_RE.match(line)
        if match is None:
            continue
        (errors if in_errors_section else warning_or_info).add(match.group(1))
    return warning_or_info, errors


def _produced_warning_or_info_codes() -> set[str]:
    """Every `warning`/`info` code any `examples/valid/` document produces."""
    codes: set[str] = set()
    for path in VALID_PARSED:
        loaded = load(path)
        codes.update(d.code for d in loaded.diagnostics if d.severity != "error")
    return codes


def _produced_error_codes() -> set[str]:
    """Every `error` code any `examples/invalid/model-only/` document produces."""
    codes: set[str] = set()
    for path in INVALID_MODEL_ONLY_PARSED:
        loaded = load(path)
        codes.update(d.code for d in loaded.diagnostics if d.severity == "error")
    return codes


def test_lint_codes_md_has_rows() -> None:
    """Guards against a parsing regression silently emptying both sets."""
    warning_or_info, errors = _documented_codes()
    assert warning_or_info
    assert errors


def test_corpus_is_not_empty() -> None:
    assert VALID_PARSED
    assert INVALID_MODEL_ONLY_PARSED


#: Codes only the markdown parser can produce. A `.mdq.md` example and its
#: `.yaml` sibling must match the same `.lint.json`, and the YAML side never
#: produces a parser warning, so the corpus cannot hold an example for
#: these. `tests/test_unknown_frontmatter_keys.py` and
#: `tests/test_include_all.py` cover them instead.
_PARSER_ONLY_CODES = frozenset({"unknown-frontmatter-key", "separator-before-include"})

#: Codes only `Exam.resolve` produces, never `load`. The corpus test cannot
#: see them. `tests/test_include_all.py` covers them instead.
_RESOLVE_ONLY_CODES = frozenset({"empty-include-all"})


def test_every_documented_warning_or_info_code_is_produced_by_the_corpus() -> None:
    documented, _ = _documented_codes()
    produced = _produced_warning_or_info_codes()
    missing = documented - produced - _PARSER_ONLY_CODES - _RESOLVE_ONLY_CODES
    assert not missing, (
        f"docs/lint-codes.md documents these warning/info codes, but no "
        f"example under examples/valid/ produces them: {sorted(missing)}"
    )


def test_every_documented_error_code_is_produced_by_the_corpus() -> None:
    # A rule that the schema also enforces (a malformed `uuid`, an extra
    # field in an include block) has its example in `examples/invalid/`,
    # not in `model-only/`. `load` still reports the documented code for it.
    _, documented_errors = _documented_codes()
    produced_errors = _produced_error_codes()
    for path in INVALID_PARSED:
        loaded = load(path)
        produced_errors.update(d.code for d in loaded.diagnostics if d.severity == "error")
    missing = documented_errors - produced_errors
    assert not missing, (
        f"docs/lint-codes.md's Errors table documents these codes, but no "
        f"example under examples/invalid/ produces them as an `error` "
        f"diagnostic: {sorted(missing)}"
    )


def test_every_code_the_implementation_produces_is_documented() -> None:
    documented_warning_or_info, documented_errors = _documented_codes()
    documented = documented_warning_or_info | documented_errors
    produced = _produced_warning_or_info_codes() | _produced_error_codes()
    undocumented = produced - documented
    assert not undocumented, (
        f"examples/valid/ and examples/invalid/model-only/ produce these "
        f"codes, but docs/lint-codes.md does not list them: {sorted(undocumented)}"
    )
