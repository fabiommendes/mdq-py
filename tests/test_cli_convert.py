"""
Tests for the `mdq import` and `mdq export` CLI commands, and the
`mdq.convert` format registry they sit on top of.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mdq.cli import app
from mdq.convert import export_question, import_question
from mdq.convert._base import load_converter

runner = CliRunner()

AIKEN_SOURCE = (
    "What is the capital of Brazil?\n"
    "\n"
    "A. Rio de Janeiro\n"
    "B. Brasilia\n"
    "C. Sao Paulo\n"
    "\n"
    "ANSWER: B\n"
)

GIFT_SOURCE = (
    "What is the largest biome in Brazil? "
    "{=Amazonia ~Caatinga#dry shrubland ~Pantanal}\n"
)


# ---------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------


def test_load_converter_returns_aiken_instance():
    converter = load_converter("aiken")
    assert type(converter).__name__ == "Aiken"


def test_load_converter_is_case_insensitive():
    assert type(load_converter("AIKEN")) is type(load_converter("aiken"))


def test_load_converter_unknown_format_raises():
    with pytest.raises(ValueError, match="Unknown format"):
        load_converter("does-not-exist")


def test_import_export_registry_round_trip():
    question = import_question(AIKEN_SOURCE, format="aiken")
    rendered = export_question(question, format="aiken")
    reimported = import_question(rendered, format="aiken")
    assert reimported == question


# ---------------------------------------------------------------------
# `mdq import`
# ---------------------------------------------------------------------


def test_cli_import_prints_mdq_to_stdout(tmp_path: Path):
    src = tmp_path / "question.aiken"
    src.write_text(AIKEN_SOURCE, encoding="utf-8")

    result = runner.invoke(app, ["import", str(src)])
    assert result.exit_code == 0
    assert "Brasilia" in result.output
    assert "* [*] Brasilia" in result.output


def test_cli_import_writes_output_file(tmp_path: Path):
    src = tmp_path / "question.aiken"
    src.write_text(AIKEN_SOURCE, encoding="utf-8")
    dest = tmp_path / "question.mdq.md"

    result = runner.invoke(app, ["import", str(src), "-o", str(dest)])
    assert result.exit_code == 0
    assert dest.exists()
    assert "* [*] Brasilia" in dest.read_text(encoding="utf-8")


def test_cli_import_explicit_format_overrides_extension(tmp_path: Path):
    src = tmp_path / "question.txt"
    src.write_text(AIKEN_SOURCE, encoding="utf-8")

    result = runner.invoke(app, ["import", str(src), "--format", "aiken"])
    assert result.exit_code == 0
    assert "* [*] Brasilia" in result.output


def test_cli_import_missing_file(tmp_path: Path):
    missing = tmp_path / "does-not-exist.aiken"
    result = runner.invoke(app, ["import", str(missing)])
    assert result.exit_code == 2


def test_cli_import_unrecognized_extension_without_format(tmp_path: Path):
    src = tmp_path / "question"
    src.write_text(AIKEN_SOURCE, encoding="utf-8")
    result = runner.invoke(app, ["import", str(src)])
    assert result.exit_code == 2
    assert "cannot infer format" in result.output


def test_cli_import_unknown_format(tmp_path: Path):
    src = tmp_path / "question.nope"
    src.write_text(AIKEN_SOURCE, encoding="utf-8")
    result = runner.invoke(app, ["import", str(src)])
    assert result.exit_code == 1
    assert "Unknown format" in result.output


def test_cli_import_malformed_source_reports_parse_error(tmp_path: Path):
    src = tmp_path / "broken.aiken"
    src.write_text("no choices here at all\n", encoding="utf-8")
    result = runner.invoke(app, ["import", str(src)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------
# `mdq export`
# ---------------------------------------------------------------------


def test_cli_export_prints_aiken_to_stdout(tmp_path: Path):
    doc = tmp_path / "question.mdq.md"
    doc.write_text(
        "What is the capital of Brazil?\n"
        "\n"
        "* [ ] Rio de Janeiro\n"
        "* [*] Brasilia\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["export", str(doc)])
    assert result.exit_code == 0
    assert "ANSWER: b" in result.output


def test_cli_export_writes_output_file_and_infers_format(tmp_path: Path):
    doc = tmp_path / "question.mdq.md"
    doc.write_text(
        "What is the capital of Brazil?\n"
        "\n"
        "* [ ] Rio de Janeiro\n"
        "* [*] Brasilia\n",
        encoding="utf-8",
    )
    dest = tmp_path / "question.aiken"

    result = runner.invoke(app, ["export", str(doc), "-o", str(dest)])
    assert result.exit_code == 0
    assert dest.exists()
    assert "ANSWER: b" in dest.read_text(encoding="utf-8")


def test_cli_export_missing_file(tmp_path: Path):
    missing = tmp_path / "does-not-exist.mdq.md"
    result = runner.invoke(app, ["export", str(missing)])
    assert result.exit_code == 2


def test_cli_export_malformed_document(tmp_path: Path):
    doc = tmp_path / "broken.mdq.md"
    doc.write_text("", encoding="utf-8")
    result = runner.invoke(app, ["export", str(doc)])
    assert result.exit_code == 1


def test_cli_export_unsupported_question_type(tmp_path: Path):
    doc = tmp_path / "essay.mdq.md"
    doc.write_text("Explain photosynthesis.\n\n[essay]\n", encoding="utf-8")
    result = runner.invoke(app, ["export", str(doc)])
    assert result.exit_code == 1


def test_cli_import_export_round_trip_via_cli(tmp_path: Path):
    src = tmp_path / "question.aiken"
    src.write_text(AIKEN_SOURCE, encoding="utf-8")
    mdq_doc = tmp_path / "question.mdq.md"
    back = tmp_path / "question2.aiken"

    result = runner.invoke(app, ["import", str(src), "-o", str(mdq_doc)])
    assert result.exit_code == 0

    result = runner.invoke(app, ["export", str(mdq_doc), "-o", str(back)])
    assert result.exit_code == 0

    assert "ANSWER: b" in back.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# `.gift` format
# ---------------------------------------------------------------------


def test_cli_import_gift_file(tmp_path: Path):
    src = tmp_path / "question.gift"
    src.write_text(GIFT_SOURCE, encoding="utf-8")

    result = runner.invoke(app, ["import", str(src)])
    assert result.exit_code == 0
    assert "Amazonia" in result.output
    assert "* [*] Amazonia" in result.output


def test_cli_export_gift_file(tmp_path: Path):
    doc = tmp_path / "question.mdq.md"
    doc.write_text(
        "What is the largest biome in Brazil?\n"
        "\n"
        "* [*] Amazonia\n"
        "* [ ] Caatinga\n"
        "* [ ] Pantanal\n",
        encoding="utf-8",
    )
    dest = tmp_path / "question.gift"

    result = runner.invoke(app, ["export", str(doc), "-o", str(dest)])
    assert result.exit_code == 0
    assert dest.exists()
    rendered = dest.read_text(encoding="utf-8")
    assert "=Amazonia" in rendered
    assert "~Caatinga" in rendered


def test_cli_import_export_gift_round_trip_via_cli(tmp_path: Path):
    src = tmp_path / "question.gift"
    src.write_text(GIFT_SOURCE, encoding="utf-8")
    mdq_doc = tmp_path / "question.mdq.md"
    back = tmp_path / "question2.gift"

    result = runner.invoke(app, ["import", str(src), "-o", str(mdq_doc)])
    assert result.exit_code == 0

    result = runner.invoke(app, ["export", str(mdq_doc), "-o", str(back)])
    assert result.exit_code == 0

    rendered = back.read_text(encoding="utf-8")
    assert "=Amazonia" in rendered
    assert "~Caatinga" in rendered


# ---------------------------------------------------------------------
# `.xml` (Moodle XML) format
# ---------------------------------------------------------------------

MOODLE_XML_SOURCE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<quiz>\n"
    '  <question type="shortanswer">\n'
    "    <name><text>Longest river</text></name>\n"
    '    <questiontext format="markdown"><text>'
    "<![CDATA[Name Brazil's longest river.]]></text></questiontext>\n"
    "    <defaultgrade>1.0</defaultgrade>\n"
    '    <answer fraction="100" format="markdown">'
    "<text><![CDATA[Amazon]]></text></answer>\n"
    "  </question>\n"
    "</quiz>\n"
)


def test_cli_import_moodle_xml_file(tmp_path: Path):
    src = tmp_path / "question.xml"
    src.write_text(MOODLE_XML_SOURCE, encoding="utf-8")

    result = runner.invoke(app, ["import", str(src)])
    assert result.exit_code == 0
    assert "Amazon" in result.output


def test_cli_export_moodle_xml_file(tmp_path: Path):
    doc = tmp_path / "question.mdq.md"
    doc.write_text(
        "Name Brazil's longest river.\n\n[short-answer]: Amazon\n",
        encoding="utf-8",
    )
    dest = tmp_path / "question.xml"

    result = runner.invoke(app, ["export", str(doc), "-o", str(dest)])
    assert result.exit_code == 0
    assert dest.exists()
    rendered = dest.read_text(encoding="utf-8")
    assert "<quiz" in rendered
    assert "Amazon" in rendered


def test_cli_import_export_moodle_xml_round_trip_via_cli(tmp_path: Path):
    src = tmp_path / "question.xml"
    src.write_text(MOODLE_XML_SOURCE, encoding="utf-8")
    mdq_doc = tmp_path / "question.mdq.md"
    back = tmp_path / "question2.xml"

    result = runner.invoke(app, ["import", str(src), "-o", str(mdq_doc)])
    assert result.exit_code == 0

    result = runner.invoke(app, ["export", str(mdq_doc), "-o", str(back)])
    assert result.exit_code == 0

    rendered = back.read_text(encoding="utf-8")
    assert "<quiz" in rendered
    assert "Amazon" in rendered
