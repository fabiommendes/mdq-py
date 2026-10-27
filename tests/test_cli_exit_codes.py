"""
Exit codes and error output of the CLI (D08): 0 success, 1 invalid document
or failed conversion, 2 usage or I/O. No command prints a traceback.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mdq.cli import app

runner = CliRunner()

OK = "Qual é a capital do Brasil?\n\n[short-answer]: Brasília\n"
INVALID = "Qual é a capital do Brasil?\n\n[short-answer]: Brasília\n[numeric]: 3\n\n[numeric]: 2\n"
GIFT = "Qual é a capital do Brasil? {=Brasília}\n"
NOT_UTF8 = b"\xff\xfe"


def invoke(*args: str | Path, stdin: bytes | str | None = None):
    return runner.invoke(app, [str(a) for a in args], input=stdin)


def assert_clean_error(result, *fragments: str) -> None:
    assert not isinstance(result.exception, Exception) or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output
    assert "error: error" not in result.output
    assert "\x1b[" not in result.stderr
    assert result.stderr.startswith("error: ")
    for fragment in fragments:
        assert fragment in result.stderr


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    (tmp_path / "ok.mdq.md").write_text(OK, encoding="utf-8")
    (tmp_path / "invalid.mdq.md").write_text(INVALID, encoding="utf-8")
    (tmp_path / "ok.txt").write_text(OK, encoding="utf-8")
    (tmp_path / "ok.gift").write_text(GIFT, encoding="utf-8")
    (tmp_path / "bad.mdq.md").write_bytes(NOT_UTF8)
    (tmp_path / "bad.aiken").write_bytes(NOT_UTF8)
    (tmp_path / "dir.mdq.md").mkdir()
    return tmp_path


# ---------------------------------------------------------------------
# Exit 2: usage and I/O, the same in every command
# ---------------------------------------------------------------------


@pytest.mark.parametrize("command", ["validate", "show", "export"])
def test_unknown_input_suffix_is_a_usage_error(command: str, docs: Path) -> None:
    result = invoke(command, docs / "ok.txt")
    assert result.exit_code == 2
    assert_clean_error(result, "cannot infer a format from", "ok.txt")
    assert "format=" not in result.stderr


def test_unknown_suffix_message_is_worded_for_each_command(docs: Path) -> None:
    assert "--format" in invoke("validate", docs / "ok.txt").stderr
    assert "--format" not in invoke("show", docs / "ok.txt").stderr
    assert "--format" not in invoke("export", docs / "ok.txt").stderr


@pytest.mark.parametrize("command", ["validate", "show", "import", "export"])
def test_missing_file_is_a_usage_error(command: str, docs: Path) -> None:
    result = invoke(command, docs / "nope.mdq.md", "--format", "aiken") if command == "import" else invoke(command, docs / "nope.mdq.md")
    assert result.exit_code == 2
    assert_clean_error(result, "nope.mdq.md")


@pytest.mark.parametrize("command", ["validate", "show", "import", "export"])
def test_directory_is_a_usage_error(command: str, docs: Path) -> None:
    args = [command, docs / "dir.mdq.md"]
    if command == "import":
        args += ["--format", "aiken"]
    result = invoke(*args)
    assert result.exit_code == 2
    assert_clean_error(result, "dir.mdq.md")


@pytest.mark.parametrize(
    ("args", "name"),
    [
        (["validate", "bad.mdq.md"], "bad.mdq.md"),
        (["show", "bad.mdq.md"], "bad.mdq.md"),
        (["export", "bad.mdq.md"], "bad.mdq.md"),
        (["import", "bad.aiken"], "bad.aiken"),
    ],
)
def test_non_utf8_file_is_a_usage_error(args: list[str], name: str, docs: Path) -> None:
    result = invoke(args[0], docs / args[1])
    assert result.exit_code == 2
    assert_clean_error(result, name, "UTF-8")


@pytest.mark.parametrize("command", ["validate", "show"])
def test_non_utf8_stdin_is_a_usage_error(command: str) -> None:
    result = invoke(command, "-", stdin=NOT_UTF8)
    assert result.exit_code == 2
    assert_clean_error(result, "<stdin>", "UTF-8")


@pytest.mark.parametrize("command", ["import", "export"])
def test_unknown_format_is_a_usage_error(command: str, docs: Path) -> None:
    source = docs / ("ok.gift" if command == "import" else "ok.mdq.md")
    result = invoke(command, source, "--format", "bogus")
    assert result.exit_code == 2
    assert_clean_error(result, "bogus")


def test_export_unknown_output_suffix_is_a_usage_error(docs: Path) -> None:
    result = invoke("export", docs / "ok.mdq.md", "-o", docs / "out.txt")
    assert result.exit_code == 2
    assert_clean_error(result, "txt")
    assert not (docs / "out.txt").exists()


def test_import_without_a_format_to_infer_is_a_usage_error(docs: Path) -> None:
    (docs / "question").write_text(GIFT, encoding="utf-8")
    result = invoke("import", docs / "question")
    assert result.exit_code == 2
    assert_clean_error(result, "cannot infer a format", "--format")


@pytest.mark.parametrize(
    "args",
    [
        ["new", "essay", "-o", "{missing}/q.mdq.md"],
        ["import", "{gift}", "-o", "{missing}/q.mdq.md"],
        ["export", "{ok}", "--format", "gift", "-o", "{missing}/q.gift"],
    ],
)
def test_output_in_a_missing_directory_is_a_usage_error(args: list[str], docs: Path) -> None:
    fill = {"missing": docs / "nope", "gift": docs / "ok.gift", "ok": docs / "ok.mdq.md"}
    result = invoke(*(a.format(**fill) for a in args))
    assert result.exit_code == 2
    assert_clean_error(result, "cannot write", "nope")


# ---------------------------------------------------------------------
# Exit 1: the document is invalid or cannot be converted
# ---------------------------------------------------------------------


@pytest.mark.parametrize("command", ["show", "export"])
def test_invalid_document_prints_its_first_error_once(command: str, docs: Path) -> None:
    result = invoke(command, docs / "invalid.mdq.md")
    assert result.exit_code == 1
    assert_clean_error(result)
    assert len(result.stderr.strip().splitlines()) == 1


def test_export_wrong_kind_is_exit_1(docs: Path) -> None:
    (docs / "exam.mdq.md").write_text("# Prova\n\nIntro.\n", encoding="utf-8")
    result = invoke("export", docs / "exam.mdq.md")
    assert result.exit_code == 1
    assert_clean_error(result, "wrong-kind")


def test_failed_conversion_is_exit_1(docs: Path) -> None:
    (docs / "broken.gift").write_text("Qual? {=Brasília\n", encoding="utf-8")
    result = invoke("import", docs / "broken.gift")
    assert result.exit_code == 1
    assert_clean_error(result)


# ---------------------------------------------------------------------
# stdin
# ---------------------------------------------------------------------


def test_import_reads_stdin(docs: Path) -> None:
    result = invoke("import", "-", "--format", "gift", stdin=GIFT)
    assert result.exit_code == 0, result.output
    assert "Brasília" in result.output


def test_export_reads_stdin(docs: Path) -> None:
    result = invoke("export", "-", "--format", "gift", stdin=OK)
    assert result.exit_code == 0, result.output
    assert "Brasília" in result.output


def test_import_stdin_needs_a_format() -> None:
    result = invoke("import", "-", stdin=GIFT)
    assert result.exit_code == 2
    assert_clean_error(result, "<stdin>", "--format")


# ---------------------------------------------------------------------
# Exit 0
# ---------------------------------------------------------------------


def test_export_reads_yaml_by_suffix(docs: Path) -> None:
    (docs / "q.yaml").write_text(
        "type: short-answer\nstem: Qual é a capital do Brasil?\naccept:\n  - Brasília\n",
        encoding="utf-8",
    )
    result = invoke("export", docs / "q.yaml", "--format", "gift")
    assert result.exit_code == 0, result.output
    assert "Brasília" in result.output
