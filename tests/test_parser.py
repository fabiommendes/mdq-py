"""
Parse MDQ Markdown source and check it against the paired `.yaml` fixture
that documents the exact document a conforming parser must produce.

Coverage here is intentionally partial: the parser is basic and some
fixtures encode ids or fields that (as far as we can tell) no
deterministic rule can reproduce -- see the comments below and the
project report for specifics. `NOT_YET_SUPPORTED` documents precisely
which of the 38 valid pairs are expected to fail today, so the
parametrized test doubles as a progress log rather than silently
skipping unknown breakage.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from mdq import load
from mdq._banks import FileLoader
from mdq.models import Exam
from _parse import parse_file
from _corpus import VALID_SOURCES, parsed_sibling, relative_id

#: Pairs the parser is known not to reproduce exactly, with the reason.
#: Keyed by the same id `relative_id` gives the pair (e.g.
#: "multiple-choice.composite-ids.mdq.md").
NOT_YET_SUPPORTED: dict[str, str] = {
    # "numeric.table-stem.mdq.md": (
    #     "the parser uses plain CommonMark with no table extension, so a "
    #     "GFM pipe table is just an ordinary paragraph to it and its rows "
    #     "collapse into a single line of prose; see BACKLOG.md"
    # ),
}


console = Console(force_terminal=True)


def load_document(path: Path):
    """The parsed sibling's own data, loaded straight off disk."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_source_files_found() -> None:
    assert VALID_SOURCES, "no .mdq.md fixtures found"


@pytest.mark.parametrize(
    "source", VALID_SOURCES, ids=[relative_id(p) for p in VALID_SOURCES]
)
def test_parses_matches_fixture(source: Path) -> None:
    key = relative_id(source)
    if key in NOT_YET_SUPPORTED:
        pytest.xfail(NOT_YET_SUPPORTED[key])

    got = parse_file(source)
    parsed_path = parsed_sibling(source)
    expected = load_document(parsed_path)

    # More helpful output than pytest's default diff.
    if got != expected:
        console.print(Panel(Syntax(yaml.dump(got), "yaml"), title="Parsed"))
        console.print(Panel(Syntax(yaml.dump(expected), "yaml"), title="Expected"))

        print("md:", source)
        print("yaml:", parsed_path)

    assert got == expected


@pytest.mark.parametrize(
    "source", VALID_SOURCES, ids=[relative_id(p) for p in VALID_SOURCES]
)
def test_parsed_document_validates(source: Path) -> None:
    key = relative_id(source)
    if key in NOT_YET_SUPPORTED:
        pytest.xfail(NOT_YET_SUPPORTED[key])
    loaded = load(parse_file(source))
    assert loaded, loaded.diagnostics
    # An exam's include blocks must also resolve against the examples.
    if isinstance(loaded.document, Exam):
        loaded.document.resolve(FileLoader(source.parent))


# ---------------------------------------------------------------------
# messages that a `.lint.json` does not record
# ---------------------------------------------------------------------


def test_numeric_zero_denominator_message() -> None:
    loaded = load("Quanto é um dividido por zero?\n\n[numeric]: 1/0\n", format="mdq")
    assert loaded.document is None
    assert "zero denominator" in loaded.diagnostics[0].message
