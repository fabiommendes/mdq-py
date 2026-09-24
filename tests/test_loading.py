"""
Tests for `mdq.loading`, the module that owns the full
markdown/data -> model -> diagnostics pipeline (see
`dev/specs/to-do/loading-module.md`).

Every caller -- library, CLI, include resolution -- is meant to go
through `load`/`parse` instead of the old `parse_question`/`parse_exam`
pass-throughs, and every problem (a parse failure, a JSON-Schema-shaped
issue, a pydantic-only rule, a lint warning) is meant to come back as a
`Diagnostic`, never as a raised `ParseError` or pydantic `ValidationError`.

Fixtures use Brazil-themed questions and exams, per AGENTS.md.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import mdq
from mdq import Diagnostic, InvalidDocument, Severity, load, parse
from mdq.loaders import DictLoader, IncludeNotFound

# ---------------------------------------------------------------------
# Fixtures: Brazil-themed MDQ source, in each surface form.
# ---------------------------------------------------------------------

QUESTION_MD = """\
Qual é a capital do Brasil?

* [ ] Rio de Janeiro
* [x] Brasília
* [ ] São Paulo
"""

QUESTION_DATA = {
    "type": "multiple-selection",
    "stem": "Qual é a capital do Brasil?",
    "choices": [
        {"id": "rio-de-janeiro", "text": "Rio de Janeiro"},
        {"id": "brasilia", "text": "Brasília", "correct": True},
        {"id": "sao-paulo", "text": "São Paulo"},
    ],
}

EXAM_MD = """\
# Exame de Geografia do Brasil

Responda a todas as questões.

===

Qual é a capital do Brasil?

* [ ] Rio de Janeiro
* [x] Brasília
* [ ] São Paulo
"""

ESSAY_MD = """\
Explique, em uma frase, o que é o efeito Coriolis.

[essay]
"""

ESSAY_DATA = {
    "type": "essay",
    "stem": "Explique, em uma frase, o que é o efeito Coriolis.",
}

# An ordering question whose `accept` and `reject` alternatives declare
# the exact same lines -- a rule only the pydantic model enforces
# (ordering.md#additional-rules); JSON Schema alone would accept this.
ORDERING_OVERLAP_DATA = {
    "type": "ordering",
    "stem": "Ordene as linhas do algoritmo de Euclides para o MDC.",
    "lines": [[0, "a, b = b, a % b"], [0, "return a"]],
    "accept": [{"lines": [[0, "a, b = b, a % b"], [0, "return a"]]}],
    "reject": [{"lines": [[0, "a, b = b, a % b"], [0, "return a"]]}],
}


def _codes(diagnostics: list[Diagnostic]) -> list[str]:
    return [d.code for d in diagnostics]


def _severities(diagnostics: list[Diagnostic]) -> list[Severity]:
    return [d.severity for d in diagnostics]


# ---------------------------------------------------------------------
# `mdq` re-exports
# ---------------------------------------------------------------------


def test_mdq_reexports_the_loading_api() -> None:
    for name in ("load", "Loaded", "parse", "Diagnostic", "Severity", "InvalidDocument"):
        assert hasattr(mdq, name), f"mdq.{name} is not re-exported"


def test_mdq_no_longer_exposes_parse_question_or_parse_exam() -> None:
    assert not hasattr(mdq, "parse_question")
    assert not hasattr(mdq, "parse_exam")


# ---------------------------------------------------------------------
# `load`: source kinds
# ---------------------------------------------------------------------


def test_str_source_is_markdown_text_by_default() -> None:
    loaded = load(QUESTION_MD)
    assert loaded
    assert loaded.document is not None
    assert loaded.document.stem == "Qual é a capital do Brasil?"


def test_str_source_is_never_treated_as_a_path() -> None:
    """
    A `str` is always the document's own text -- even one that happens to
    look like a path to a file that exists on disk must be parsed as
    Markdown, not opened.
    """
    text = "Isto não é um caminho de arquivo.\n\n[essay]\n"
    loaded = load(text)
    assert loaded
    assert loaded.document.stem == "Isto não é um caminho de arquivo."


def test_str_source_honors_format_override() -> None:
    yaml_text = "type: essay\nstem: Explique o Cerrado em um parágrafo.\n"
    loaded = load(yaml_text, format="yaml")
    assert loaded
    assert loaded.document.stem == "Explique o Cerrado em um parágrafo."


@pytest.mark.parametrize(
    "suffix,content",
    [
        (".mdq.md", QUESTION_MD),
        (".mdq", QUESTION_MD),
    ],
)
def test_path_with_mdq_suffix_is_parsed_as_markdown(
    tmp_path: Path, suffix: str, content: str
) -> None:
    path = tmp_path / f"capital{suffix}"
    path.write_text(content, encoding="utf-8")
    loaded = load(path)
    assert loaded
    assert loaded.document.stem == "Qual é a capital do Brasil?"


@pytest.mark.parametrize("suffix", [".yaml", ".yml"])
def test_path_with_yaml_suffix_is_parsed_as_yaml(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"efeito-coriolis{suffix}"
    path.write_text(
        "type: essay\nstem: Explique, em uma frase, o efeito Coriolis.\n",
        encoding="utf-8",
    )
    loaded = load(path)
    assert loaded
    assert loaded.document.stem == "Explique, em uma frase, o efeito Coriolis."


def test_path_with_json_suffix_is_parsed_as_json(tmp_path: Path) -> None:
    path = tmp_path / "efeito-coriolis.json"
    path.write_text(json.dumps(ESSAY_DATA), encoding="utf-8")
    loaded = load(path)
    assert loaded
    assert loaded.document.stem == ESSAY_DATA["stem"]


def test_path_format_overrides_the_suffix(tmp_path: Path) -> None:
    path = tmp_path / "efeito-coriolis.txt"
    path.write_text(json.dumps(ESSAY_DATA), encoding="utf-8")
    loaded = load(path, format="json")
    assert loaded
    assert loaded.document.stem == ESSAY_DATA["stem"]


def test_io_source_is_read_then_handled_as_str() -> None:
    stream = io.StringIO(QUESTION_MD)
    loaded = load(stream)
    assert loaded
    assert loaded.document.stem == "Qual é a capital do Brasil?"


def test_io_source_honors_format_override() -> None:
    stream = io.StringIO(json.dumps(ESSAY_DATA))
    loaded = load(stream, format="json")
    assert loaded
    assert loaded.document.stem == ESSAY_DATA["stem"]


def test_mapping_source_skips_the_parse_step() -> None:
    loaded = load(QUESTION_DATA)
    assert loaded
    assert loaded.document.stem == QUESTION_DATA["stem"]
    assert loaded.document.type == "multiple-selection"


def test_mapping_source_produces_no_frontmatter_warnings() -> None:
    """A Mapping is already-parsed data: there is no frontmatter to warn about."""
    loaded = load(ESSAY_DATA)
    assert _codes(loaded.diagnostics) == []


# ---------------------------------------------------------------------
# `load`: call errors (never a diagnostic)
# ---------------------------------------------------------------------


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load(tmp_path / "nao-existe.mdq.md")


def test_unknown_format_raises(tmp_path: Path) -> None:
    path = tmp_path / "sem-extensao-conhecida.txt"
    path.write_text(QUESTION_MD, encoding="utf-8")
    with pytest.raises(ValueError):
        load(path)


# ---------------------------------------------------------------------
# `kind`
# ---------------------------------------------------------------------


def test_kind_question_narrows_a_question_document() -> None:
    loaded = load(QUESTION_MD, kind="question")
    assert loaded
    assert loaded.document.stem == "Qual é a capital do Brasil?"


def test_kind_exam_narrows_an_exam_document() -> None:
    loaded = load(EXAM_MD, kind="exam", loader=DictLoader({}))
    assert loaded
    assert loaded.document.title == "Exame de Geografia do Brasil"


def test_kind_none_accepts_a_question() -> None:
    assert load(QUESTION_MD, kind=None)


def test_kind_none_accepts_an_exam() -> None:
    assert load(EXAM_MD, kind=None, loader=DictLoader({}))


def test_kind_question_on_an_exam_reports_wrong_kind() -> None:
    loaded = load(EXAM_MD, kind="question", loader=DictLoader({}))
    assert not loaded
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1
    diagnostic = loaded.diagnostics[0]
    assert diagnostic.severity == "error"
    assert diagnostic.code == "wrong-kind"


def test_kind_exam_on_a_question_reports_wrong_kind() -> None:
    loaded = load(QUESTION_MD, kind="exam")
    assert not loaded
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1
    diagnostic = loaded.diagnostics[0]
    assert diagnostic.severity == "error"
    assert diagnostic.code == "wrong-kind"


def test_wrong_kind_is_reported_instead_of_pydantic_errors() -> None:
    """
    The kind mismatch must be caught before model validation, even when
    the document (wrongly typed) would also fail pydantic validation for
    unrelated reasons (an exam has no 'stem', so validating it as a
    Question would normally produce a pile of "missing field" errors).
    """
    loaded = load({"type": "exam", "questions": []}, kind="question")
    assert [d.code for d in loaded.diagnostics] == ["wrong-kind"]


def test_kind_mismatch_on_mapping_source() -> None:
    loaded = load(QUESTION_DATA, kind="exam")
    assert not loaded
    assert loaded.diagnostics[0].code == "wrong-kind"


# ---------------------------------------------------------------------
# `Loaded`: truthiness
# ---------------------------------------------------------------------


def test_loaded_is_truthy_when_a_document_was_built() -> None:
    assert bool(load(QUESTION_MD)) is True


def test_loaded_is_falsy_when_no_document_was_built() -> None:
    assert bool(load("")) is False


def test_loaded_with_only_warnings_is_still_truthy() -> None:
    # An unknown frontmatter key produces a warning, not an error; the
    # document is still built.
    loaded = load("---\nauther: Machado de Assis\n---\n\n" + ESSAY_MD)
    assert any(d.severity == "warning" for d in loaded.diagnostics)
    assert bool(loaded) is True
    assert loaded.document is not None


# ---------------------------------------------------------------------
# `Loaded.validate`
# ---------------------------------------------------------------------


def test_validate_returns_the_document_when_clean() -> None:
    document = load(QUESTION_MD).validate()
    assert document.stem == "Qual é a capital do Brasil?"


def test_validate_default_raises_on_error_but_not_on_warning() -> None:
    loaded = load("---\nauther: Machado de Assis\n---\n\n" + ESSAY_MD)
    assert any(d.severity == "warning" for d in loaded.diagnostics)
    # default raise_on="error": warnings alone must not raise.
    document = loaded.validate()
    assert document is not None


def test_validate_raise_on_warning_raises_when_a_warning_is_present() -> None:
    loaded = load("---\nauther: Machado de Assis\n---\n\n" + ESSAY_MD)
    with pytest.raises(InvalidDocument):
        loaded.validate(raise_on="warning")


def test_validate_raise_on_info_raises_when_an_info_diagnostic_is_present() -> None:
    # A bare-ellipsis stem is a strict-only rule, reported at "info".
    loaded = load("...\n\n[essay]\n")
    assert any(d.severity == "info" for d in loaded.diagnostics)
    with pytest.raises(InvalidDocument):
        loaded.validate(raise_on="info")


def test_validate_raise_on_info_also_raises_on_a_plain_warning() -> None:
    """
    Severities rank error > warning > info, and `validate` raises on
    anything "at or above" `raise_on`. "info" is the lowest rank, so
    every diagnostic -- including a plain warning -- is at or above it.
    """
    loaded = load("---\nauther: Machado de Assis\n---\n\n" + ESSAY_MD)
    diagnostics = loaded.diagnostics
    assert any(d.severity == "warning" for d in diagnostics)
    assert not any(d.severity in ("error", "info") for d in diagnostics)
    with pytest.raises(InvalidDocument):
        loaded.validate(raise_on="info")


def test_validate_never_raises_when_there_are_no_diagnostics_at_all() -> None:
    loaded = load(QUESTION_MD)
    assert loaded.diagnostics == []
    for raise_on in ("error", "warning", "info"):
        document = loaded.validate(raise_on=raise_on)
        assert document is not None


def test_validate_always_raises_when_there_is_no_document() -> None:
    loaded = load("")
    assert loaded.document is None
    for raise_on in ("error", "warning", "info"):
        with pytest.raises(InvalidDocument):
            loaded.validate(raise_on=raise_on)


def test_validate_error_raised_carries_every_diagnostic() -> None:
    loaded = load("---\nauther: Machado de Assis\n---\n\n" + ESSAY_MD)
    try:
        loaded.validate(raise_on="warning")
    except InvalidDocument as exc:
        assert exc.diagnostics == loaded.diagnostics
    else:
        pytest.fail("expected InvalidDocument")


# ---------------------------------------------------------------------
# `parse`
# ---------------------------------------------------------------------


def test_parse_is_a_shortcut_for_load_then_validate() -> None:
    document = parse(QUESTION_MD)
    assert document.stem == "Qual é a capital do Brasil?"


def test_parse_honors_kind() -> None:
    document = parse(QUESTION_MD, kind="question")
    assert document.type == "multiple-selection"


def test_parse_raises_invalid_document_on_error() -> None:
    with pytest.raises(InvalidDocument):
        parse("")


def test_parse_raise_on_warning_raises_on_a_warning() -> None:
    with pytest.raises(InvalidDocument):
        parse("---\nauther: Machado de Assis\n---\n\n" + ESSAY_MD, raise_on="warning")


def test_parse_never_leaks_parse_error_or_pydantic_validation_error() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from mdq.errors import ParseError

    with pytest.raises(InvalidDocument):
        parse("")  # a ParseError-shaped failure (no stem/body at all)

    with pytest.raises(InvalidDocument):
        parse({"type": "essay"})  # a pydantic-shaped failure (missing stem)

    # Neither of the underlying exception types should ever escape.
    for source in ("", {"type": "essay"}):
        try:
            parse(source)
        except (ParseError, PydanticValidationError):
            pytest.fail("a raw ParseError/ValidationError escaped `parse`")
        except InvalidDocument:
            pass


# ---------------------------------------------------------------------
# Parse failures
# ---------------------------------------------------------------------


def test_parse_failure_is_a_single_error_diagnostic() -> None:
    loaded = load("")  # no body at all -> MissingField("stem")
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1
    assert loaded.diagnostics[0].severity == "error"


def test_parse_failure_without_a_known_location_has_no_line() -> None:
    loaded = load("")
    assert loaded.diagnostics[0].line is None


def test_parse_failure_with_a_known_location_sets_the_line() -> None:
    # The block right after [ordering] must be a fenced code block or a
    # list; a plain paragraph there is a parse error tied to a specific
    # source node, which does carry a line range.
    text = (
        "Ordene as linhas abaixo.\n"
        "\n"
        "[ordering]\n"
        "\n"
        "Isto não é uma lista nem um bloco de código.\n"
    )
    loaded = load(text)
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1
    assert loaded.diagnostics[0].severity == "error"
    assert loaded.diagnostics[0].line is not None
    assert loaded.diagnostics[0].line >= 1


def test_yaml_syntax_error_is_a_single_error_diagnostic() -> None:
    loaded = load("type: essay\nstem: [unterminated\n", format="yaml")
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1
    assert loaded.diagnostics[0].severity == "error"


def test_json_syntax_error_is_a_single_error_diagnostic() -> None:
    loaded = load("{not valid json", format="json")
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1
    assert loaded.diagnostics[0].severity == "error"


# ---------------------------------------------------------------------
# Pydantic errors
# ---------------------------------------------------------------------


def test_pydantic_missing_field_becomes_one_error_diagnostic() -> None:
    loaded = load({"type": "essay"})  # missing 'stem'
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1
    diagnostic = loaded.diagnostics[0]
    assert diagnostic.severity == "error"
    assert diagnostic.code == "missing"
    assert diagnostic.path[-1] == "stem"


def test_pydantic_multiple_errors_become_one_diagnostic_each() -> None:
    loaded = load({"type": "multiple-choice"})  # missing 'stem' and 'choices'
    assert loaded.document is None
    assert len(loaded.diagnostics) == 2
    paths = {d.path[-1] for d in loaded.diagnostics}
    assert paths == {"stem", "choices"}
    assert all(d.severity == "error" for d in loaded.diagnostics)
    assert all(d.code == "missing" for d in loaded.diagnostics)


def test_pydantic_only_rule_ordering_overlap_is_reported_as_an_error() -> None:
    """
    JSON Schema cannot express "accept and reject must be disjoint" --
    only the pydantic model enforces it. `load` must still catch it and
    turn it into an error diagnostic, not let the ValueError escape.
    """
    loaded = load(ORDERING_OVERLAP_DATA)
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1
    diagnostic = loaded.diagnostics[0]
    assert diagnostic.severity == "error"
    assert diagnostic.code == "value_error"


def test_pydantic_only_rule_violation_fails_mdq_validate_style_pipeline() -> None:
    """Mirrors the CLI-level acceptance criterion in the spec's "Done means"."""
    loaded = load(ORDERING_OVERLAP_DATA)
    assert not loaded
    with pytest.raises(InvalidDocument):
        loaded.validate()


# ---------------------------------------------------------------------
# Lint diagnostics and ordering
# ---------------------------------------------------------------------


def test_default_level_lint_rules_are_warnings() -> None:
    # No choice scores >= 1, so the question has no correct answer.
    data = {
        "type": "multiple-choice",
        "stem": "Qual das opções é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0},
            {"id": "b", "text": "Brasília", "score": 0},
        ],
    }
    loaded = load(data)
    assert loaded
    assert "multiple-choice-no-correct-choice" in _codes(loaded.diagnostics)
    matching = [
        d for d in loaded.diagnostics if d.code == "multiple-choice-no-correct-choice"
    ]
    assert matching[0].severity == "warning"


def test_strict_only_lint_rule_is_reported_as_info() -> None:
    loaded = load("...\n\n[essay]\n")
    assert loaded
    matching = [d for d in loaded.diagnostics if d.code == "unexpanded-stem-ellipsis"]
    assert len(matching) == 1
    assert matching[0].severity == "info"


def test_lint_runs_only_when_the_model_was_built() -> None:
    loaded = load("")  # parse failure -- no model, no lint pass
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1  # just the parse-failure diagnostic


def test_unknown_frontmatter_warnings_come_before_lint_diagnostics() -> None:
    text = "---\nauther: Machado de Assis\n---\n\n...\n\n[essay]\n"
    loaded = load(text)
    assert loaded
    codes = _codes(loaded.diagnostics)
    assert "unknown-frontmatter-key" in codes
    assert "unexpanded-stem-ellipsis" in codes
    assert codes.index("unknown-frontmatter-key") < codes.index("unexpanded-stem-ellipsis")


def test_unknown_frontmatter_warning_severity_is_warning() -> None:
    loaded = load("---\nauther: Machado de Assis\n---\n\n" + ESSAY_MD)
    matching = [d for d in loaded.diagnostics if d.code == "unknown-frontmatter-key"]
    assert len(matching) == 1
    assert matching[0].severity == "warning"


# ---------------------------------------------------------------------
# Include resolution
# ---------------------------------------------------------------------

INCLUDED_QUESTION_MD = """\
---
id: recursao-fatorial
---

Converta este algoritmo iterativo de fatorial em um recursivo.

[essay]
"""

INCLUDED_QUESTION_DATA = {
    "id": "recursao-fatorial",
    "type": "essay",
    "stem": "Converta este algoritmo iterativo de fatorial em um recursivo.",
}


def _exam_with_include(include_id: str) -> str:
    return (
        "# Prova de Algoritmos\n"
        "\n"
        "Responda a todas as questões.\n"
        "\n"
        "---\n"
        f"include: {include_id}\n"
        "---\n"
    )


def test_default_loader_for_path_source_is_file_loader_of_the_parent_dir(
    tmp_path: Path,
) -> None:
    (tmp_path / "recursao-fatorial.mdq.md").write_text(
        INCLUDED_QUESTION_MD, encoding="utf-8"
    )
    exam_path = tmp_path / "prova.mdq.md"
    exam_path.write_text(_exam_with_include("recursao-fatorial"), encoding="utf-8")

    loaded = load(exam_path)  # no explicit loader
    assert loaded
    assert loaded.document.questions[0].id == "recursao-fatorial"


def test_explicit_loader_overrides_the_default() -> None:
    text = _exam_with_include("recursao-fatorial")
    loader = DictLoader({"recursao-fatorial": INCLUDED_QUESTION_DATA})
    loaded = load(text, loader=loader)
    assert loaded
    assert loaded.document.questions[0].id == "recursao-fatorial"


def test_loader_may_return_markdown_text() -> None:
    class _StrLoader:
        def load(self, question_id: str) -> str:
            return INCLUDED_QUESTION_MD

    loaded = load(_exam_with_include("recursao-fatorial"), loader=_StrLoader())
    assert loaded
    assert loaded.document.questions[0].id == "recursao-fatorial"


def test_loader_may_return_a_mapping() -> None:
    loader = DictLoader({"recursao-fatorial": INCLUDED_QUESTION_DATA})
    loaded = load(_exam_with_include("recursao-fatorial"), loader=loader)
    assert loaded
    assert loaded.document.questions[0].id == "recursao-fatorial"


def test_included_question_diagnostics_are_prefixed_with_questions_index() -> None:
    included_with_warning = {
        # unknown-frontmatter-key cannot fire on a Mapping source (there's
        # no frontmatter to parse) -- use a lint-level rule instead: a
        # blank comment field.
        "id": "recursao-fatorial",
        "type": "essay",
        "stem": "Converta este algoritmo iterativo de fatorial em um recursivo.",
        "comment": "   ",
    }
    loader = DictLoader({"recursao-fatorial": included_with_warning})
    loaded = load(_exam_with_include("recursao-fatorial"), loader=loader)
    assert loaded
    matching = [d for d in loaded.diagnostics if d.code == "blank-text-field"]
    assert len(matching) == 1
    assert matching[0].path[:2] == ("questions", 0)


def test_included_question_error_becomes_an_exam_error() -> None:
    broken = {"id": "recursao-fatorial", "type": "essay"}  # missing 'stem'
    loader = DictLoader({"recursao-fatorial": broken})
    loaded = load(_exam_with_include("recursao-fatorial"), loader=loader)
    assert not loaded
    assert loaded.document is None
    assert any(d.severity == "error" for d in loaded.diagnostics)


def test_include_not_found_is_an_error_diagnostic_at_questions_index() -> None:
    loader = DictLoader({})
    loaded = load(_exam_with_include("nao-existe"), loader=loader)
    assert not loaded
    assert loaded.document is None
    assert len(loaded.diagnostics) == 1
    diagnostic = loaded.diagnostics[0]
    assert diagnostic.severity == "error"
    assert diagnostic.path == ("questions", 0)


def test_include_without_loader_is_an_error_diagnostic_at_questions_index() -> None:
    loaded = load(_exam_with_include("nao-existe"))
    assert not loaded
    assert [(d.severity, d.path) for d in loaded.diagnostics] == [
        ("error", ("questions", 0))
    ]


def test_include_not_found_raises_from_the_loader_directly() -> None:
    """Sanity check on the fixture: `DictLoader` itself still raises."""
    loader = DictLoader({})
    with pytest.raises(IncludeNotFound):
        loader.load("nao-existe")
