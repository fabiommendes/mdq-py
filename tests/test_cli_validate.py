"""
Tests for `mdq validate`, once it is rebuilt on top of `mdq.loading` (see
`dev/specs/to-do/loading-module.md`).

The command drops `--type`/`--schema-dir` (`load` figures out the format
from the file itself) and keeps `--level default|strict`, which now only
changes whether "info"-severity diagnostics are printed -- every rule
always runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mdq.cli import app

runner = CliRunner()

ESSAY_MD = "Explique o que é o efeito Coriolis, em uma frase.\n\n[essay]\n"

# An ordering question whose accept/reject alternatives overlap -- valid
# JSON Schema, but rejected by the pydantic model (ordering.md#additional-rules).
ORDERING_OVERLAP_YAML = """\
type: ordering
stem: Ordene as linhas do algoritmo de Euclides para o MDC.
lines:
  - [0, "a, b = b, a % b"]
  - [0, "return a"]
accept:
  - lines:
      - [0, "a, b = b, a % b"]
      - [0, "return a"]
reject:
  - lines:
      - [0, "a, b = b, a % b"]
      - [0, "return a"]
"""

# A well-formed multiple-selection question whose two choices share the
# same text -- a default-level lint warning, not an error.
DUPLICATE_CHOICE_TEXT_MD = (
    "Qual das opções é a capital do Brasil?\n"
    "\n"
    "* [x] Brasília\n"
    "* [ ] Brasília\n"
)

# A bare-ellipsis stem trips a strict-only rule (reported at "info").
STRICT_ONLY_MD = "...\n\n[essay]\n"


def test_validate_accepts_a_markdown_file(tmp_path: Path) -> None:
    path = tmp_path / "coriolis.mdq.md"
    path.write_text(ESSAY_MD, encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0, result.output


def test_validate_accepts_a_yaml_file(tmp_path: Path) -> None:
    path = tmp_path / "coriolis.yaml"
    path.write_text("type: essay\nstem: Explique o efeito Coriolis.\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0, result.output


def test_validate_accepts_a_json_file(tmp_path: Path) -> None:
    path = tmp_path / "coriolis.json"
    path.write_text(
        json.dumps({"type": "essay", "stem": "Explique o efeito Coriolis."}),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0, result.output


def test_validate_exits_1_on_a_schema_level_error(tmp_path: Path) -> None:
    path = tmp_path / "quebrado.yaml"
    path.write_text("type: essay\n", encoding="utf-8")  # missing 'stem'
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 1, result.output


def test_validate_exits_1_on_a_pydantic_only_rule_violation(tmp_path: Path) -> None:
    """
    ordering accept/reject overlap: no JSON Schema rule forbids it, but
    the pydantic model does, and that alone must still fail `validate`.
    """
    path = tmp_path / "euclides.yaml"
    path.write_text(ORDERING_OVERLAP_YAML, encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 1, result.output


def test_validate_exits_0_with_only_warnings(tmp_path: Path) -> None:
    path = tmp_path / "capital.mdq.md"
    path.write_text(DUPLICATE_CHOICE_TEXT_MD, encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0, result.output


def test_validate_exits_2_when_the_file_is_missing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "nao-existe.mdq.md")])
    assert result.exit_code == 2, result.output


def test_validate_default_level_does_not_show_info_diagnostics(tmp_path: Path) -> None:
    path = tmp_path / "estrito.mdq.md"
    path.write_text(STRICT_ONLY_MD, encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0, result.output
    assert "unexpanded-stem-ellipsis" not in result.output


def test_validate_strict_level_shows_info_diagnostics(tmp_path: Path) -> None:
    path = tmp_path / "estrito.mdq.md"
    path.write_text(STRICT_ONLY_MD, encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path), "--level", "strict"])
    assert "unexpanded-stem-ellipsis" in result.output


def test_validate_strict_level_still_exits_0_for_info_only_documents(
    tmp_path: Path,
) -> None:
    path = tmp_path / "estrito.mdq.md"
    path.write_text(STRICT_ONLY_MD, encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path), "--level", "strict"])
    assert result.exit_code == 0, result.output


def test_validate_rejects_the_removed_type_option(tmp_path: Path) -> None:
    path = tmp_path / "coriolis.mdq.md"
    path.write_text(ESSAY_MD, encoding="utf-8")
    result = runner.invoke(app, ["validate", str(path), "--type", "essay"])
    assert result.exit_code == 2
    assert "--type" in result.output or "no such option" in result.output.lower()


def test_validate_rejects_the_removed_schema_dir_option(tmp_path: Path) -> None:
    path = tmp_path / "coriolis.mdq.md"
    path.write_text(ESSAY_MD, encoding="utf-8")
    result = runner.invoke(
        app, ["validate", str(path), "--schema-dir", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "--schema-dir" in result.output or "no such option" in result.output.lower()
