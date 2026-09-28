"""
Tests for `dev/specs/to-do/rule-conformance.md`: the "Additional rules"
tables in `docs/question-types/*.md` are the specification, and the
lint implementation must match them row for row.

Sections mirror the spec:

* A -- four codes whose severity changes to match the spec.
* C -- rules missing from the implementation. The spec's codes are
  proposals; `_PROPOSED_CODES` is the one place to rename one, so every
  test below reads the code through it rather than hard-coding a
  literal.
* D -- critical rules the audit could not find an enforcement point
  for. Each becomes a `load()` test expecting an `error`. Where the
  spec gives no code, a test accepts a small set of plausible codes and
  says so in a comment.

Written against the public `mdq.load` API and the models' own `lint()`
method -- no `mdq.linter` internals. Fixtures use Brazil-themed
questions, per AGENTS.md. No corpus examples are added here: the spec
has the implementer add them together with the `.lint.json` files.
"""

from __future__ import annotations

from mdq import Diagnostic, load

#: Section C's proposed codes, keyed by rule so a rename is a one-line
#: change here rather than a hunt-and-replace across the test bodies.
#: The same code is intentionally reused for "all-choices-correct" across
#: multiple-choice and multiple-selection, per the spec's "use the same
#: code for the same rule in every question type".
_PROPOSED_CODES: dict[str, str] = {
    "unsafe-id": "unsafe-id",
    "missing-id": "missing-id",
    "missing-title": "missing-title",
    "blank-choice-feedback": "blank-choice-feedback",
    "blank-choice-comment": "blank-choice-comment",
    "visually-identical-choices": "visually-identical-choices",
    "missing-choice-id": "missing-choice-id",
    "all-choices-correct": "all-choices-correct",
    "no-correct-choice": "no-correct-choice",
    "uniform-true-false-answers": "uniform-true-false-answers",
    "non-nfc-true-false-marker": "non-nfc-true-false-marker",
    "unknown-highlight-language": "unknown-highlight-language",
    "missing-answer-key": "missing-answer-key",
    "domain-mismatch": "domain-mismatch",
    "missing-tolerance": "missing-tolerance",
    "accept-wildcard": "accept-wildcard",
    "ignored-regex-flag": "ignored-regex-flag",
    "unreachable-reject": "unreachable-reject",
}


def _codes(diagnostics: list[Diagnostic]) -> set[str]:
    return {d.code for d in diagnostics}


def _load_ok(doc: dict):
    loaded = load(doc)
    assert loaded.document is not None, loaded.diagnostics
    return loaded.document


# =======================================================================
# Section A: severity changes (the spec wins)
# =======================================================================


def test_stem_not_a_paragraph_is_a_warning() -> None:
    """base.md:253. Uses a blockquote opener, not a heading: H1 is a
    forbidden block element (base.md's "Forbidden elements"), which
    would make the document uninterpretable as a mere non-paragraph
    stem once Section D's forbidden-elements rule is enforced."""
    doc = {
        "type": "essay",
        "stem": "> Isso não é um parágrafo comum.",
        "input": "text",
    }
    question = _load_ok(doc)
    matching = [d for d in question.lint() if d.code == "stem-not-a-paragraph"]
    assert len(matching) == 1
    assert matching[0].severity == "warning"


def test_code_input_without_highlight_is_info() -> None:
    """essay.md:90."""
    doc = {"type": "essay", "stem": "Descreva o algoritmo.", "input": "code"}
    question = _load_ok(doc)
    matching = [d for d in question.lint() if d.code == "code-input-without-highlight"]
    assert len(matching) == 1
    assert matching[0].severity == "info"


def test_multiple_choice_no_correct_choice_is_info() -> None:
    """multiple-choice.md:216."""
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0},
            {"id": "b", "text": "Salvador", "score": 0},
        ],
    }
    question = _load_ok(doc)
    matching = [
        d for d in question.lint() if d.code == "multiple-choice-no-correct-choice"
    ]
    assert len(matching) == 1
    assert matching[0].severity == "info"


def test_locale_mismatched_true_false_marker_is_a_warning() -> None:
    """true-false.md:214."""
    doc = {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre o Brasil.",
        "locale": "pt",
        "choices": [
            {
                "id": "a",
                "text": "O Amazonas é o maior rio do mundo em volume de água.",
                "correct": True,
                "marker": "T",
            },
            {"id": "b", "text": "Brasília fica no litoral.", "correct": False, "marker": "F"},
        ],
    }
    question = _load_ok(doc)
    matching = [
        d for d in question.lint() if d.code == "locale-mismatched-true-false-marker"
    ]
    assert len(matching) == 1
    assert matching[0].severity == "warning"


# =======================================================================
# Section C: missing rules
# =======================================================================


# --- base.md:252 id must be url-safe -----------------------------------


def test_unsafe_id_warns() -> None:
    doc = {
        "type": "essay",
        "id": "capital do Brasil",
        "stem": "Descreva a Baía de Guanabara.",
        "input": "text",
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["unsafe-id"] in _codes(question.lint())


def test_url_safe_id_does_not_warn() -> None:
    doc = {
        "type": "essay",
        "id": "capital-do-brasil",
        "stem": "Descreva a Baía de Guanabara.",
        "input": "text",
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["unsafe-id"] not in _codes(question.lint())


# --- base.md:255 id, title should be defined ---------------------------


def test_missing_id_and_title_report_info() -> None:
    doc = {"type": "essay", "stem": "Descreva a Baía de Guanabara.", "input": "text"}
    question = _load_ok(doc)
    codes = _codes(question.lint())
    assert _PROPOSED_CODES["missing-id"] in codes
    assert _PROPOSED_CODES["missing-title"] in codes


def test_defined_id_and_title_do_not_warn() -> None:
    doc = {
        "type": "essay",
        "id": "baia-de-guanabara",
        "title": "A Baía de Guanabara",
        "stem": "Descreva a Baía de Guanabara.",
        "input": "text",
    }
    question = _load_ok(doc)
    codes = _codes(question.lint())
    assert _PROPOSED_CODES["missing-id"] not in codes
    assert _PROPOSED_CODES["missing-title"] not in codes


# --- MC/MS/TF choices[].feedback, choices[].comment ---------------------


def test_blank_choice_feedback_warns() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0, "feedback": "   "},
            {"id": "b", "text": "Brasília", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["blank-choice-feedback"] in _codes(question.lint())


def test_non_blank_choice_feedback_does_not_warn() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0, "feedback": "Já foi, não é mais."},
            {"id": "b", "text": "Brasília", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["blank-choice-feedback"] not in _codes(question.lint())


def test_blank_choice_comment_warns() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0, "comment": "\t "},
            {"id": "b", "text": "Brasília", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["blank-choice-comment"] in _codes(question.lint())


def test_non_blank_choice_comment_does_not_warn() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0, "comment": "nota interna"},
            {"id": "b", "text": "Brasília", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["blank-choice-comment"] not in _codes(question.lint())


# --- MC/MS/TF choices[].text visual equivalence -------------------------


def test_visually_identical_choices_warns() -> None:
    """
    multiple-choice.md footnote: reuses the ordering linter's rendered
    comparison (`visually-identical-lines`). `*Rio de Janeiro*` and
    `_Rio de Janeiro_` render identically but are literally different
    strings, so `duplicate-choice-text`'s whitespace-only normalization
    does not also reject the document -- that would make this rule
    untestable, since the document would already fail to load.
    """
    doc = {
        "type": "multiple-choice",
        "stem": "Qual cidade é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "*Rio de Janeiro*", "score": 0},
            {"id": "b", "text": "_Rio de Janeiro_", "score": 0},
            {"id": "c", "text": "Brasília", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["visually-identical-choices"] in _codes(question.lint())


def test_visually_distinct_choices_do_not_warn() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual cidade é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0},
            {"id": "b", "text": "Brasília", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["visually-identical-choices"] not in _codes(question.lint())


# --- MC/MS/TF choices[].id defined, not derived -------------------------


def test_missing_choice_id_reports_info() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"text": "Rio de Janeiro", "score": 0},
            {"id": "brasilia", "text": "Brasília", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["missing-choice-id"] in _codes(question.lint())


def test_every_choice_with_an_explicit_id_does_not_warn() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "rio", "text": "Rio de Janeiro", "score": 0},
            {"id": "brasilia", "text": "Brasília", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["missing-choice-id"] not in _codes(question.lint())


# --- multiple-choice.md:217 not every choice correct --------------------


def test_multiple_choice_all_correct_reports_all_choices_correct() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual destas afirmações é verdadeira?",
        "choices": [
            {"id": "a", "text": "O Brasil fica na América do Sul.", "score": 1},
            {"id": "b", "text": "O Amazonas é um rio.", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["all-choices-correct"] in _codes(question.lint())


def test_multiple_choice_with_one_correct_choice_does_not_warn() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0},
            {"id": "b", "text": "Brasília", "score": 1},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["all-choices-correct"] not in _codes(question.lint())


# --- multiple-selection.md:122 at least one correct ----------------------


def test_multiple_selection_no_correct_choice_reports_no_correct_choice() -> None:
    doc = {
        "type": "multiple-selection",
        "stem": "Quais destes são biomas brasileiros?",
        "choices": [
            {"id": "a", "text": "Cerrado", "correct": False},
            {"id": "b", "text": "Savana Africana", "correct": False},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["no-correct-choice"] in _codes(question.lint())


def test_multiple_selection_with_a_correct_choice_does_not_warn_no_correct_choice() -> None:
    doc = {
        "type": "multiple-selection",
        "stem": "Quais destes são biomas brasileiros?",
        "choices": [
            {"id": "a", "text": "Cerrado", "correct": True},
            {"id": "b", "text": "Savana Africana", "correct": False},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["no-correct-choice"] not in _codes(question.lint())


# --- multiple-selection.md:123 not every choice correct ------------------


def test_multiple_selection_all_correct_reports_all_choices_correct() -> None:
    doc = {
        "type": "multiple-selection",
        "stem": "Quais destes são biomas brasileiros?",
        "choices": [
            {"id": "a", "text": "Cerrado", "correct": True},
            {"id": "b", "text": "Pantanal", "correct": True},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["all-choices-correct"] in _codes(question.lint())


def test_multiple_selection_with_mixed_choices_does_not_warn_all_correct() -> None:
    doc = {
        "type": "multiple-selection",
        "stem": "Quais destes são biomas brasileiros?",
        "choices": [
            {"id": "a", "text": "Cerrado", "correct": True},
            {"id": "b", "text": "Savana Africana", "correct": False},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["all-choices-correct"] not in _codes(question.lint())


# --- true-false.md:218 not all true or all false -------------------------


def test_true_false_all_true_reports_uniform_answers() -> None:
    doc = {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre o Brasil.",
        "choices": [
            {"id": "a", "text": "O Brasil fica na América do Sul.", "correct": True, "marker": "T"},
            {"id": "b", "text": "A capital do Brasil é Brasília.", "correct": True, "marker": "T"},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["uniform-true-false-answers"] in _codes(question.lint())


def test_true_false_mixed_answers_does_not_warn_uniform() -> None:
    doc = {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre o Brasil.",
        "choices": [
            {"id": "a", "text": "O Brasil fica na América do Sul.", "correct": True, "marker": "T"},
            {"id": "b", "text": "Brasília fica no litoral.", "correct": False, "marker": "F"},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["uniform-true-false-answers"] not in _codes(question.lint())


# --- true-false.md:219 marker is one code point in NFC -------------------


def test_non_nfc_true_false_marker_reports_info() -> None:
    """
    U+212B (ANGSTROM SIGN) is one code point -- satisfying the field's
    single-character shape -- but is not its own NFC form: NFC
    normalizes it to U+00C5 (LATIN CAPITAL LETTER A WITH RING ABOVE).
    """
    doc = {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre o Brasil.",
        "choices": [
            {"id": "a", "text": "O Brasil fica na América do Sul.", "correct": True, "marker": "Å"},
            {"id": "b", "text": "Brasília fica no litoral.", "correct": False, "marker": "F"},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["non-nfc-true-false-marker"] in _codes(question.lint())


def test_nfc_true_false_marker_does_not_warn() -> None:
    doc = {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre o Brasil.",
        "choices": [
            {"id": "a", "text": "O Brasil fica na América do Sul.", "correct": True, "marker": "T"},
            {"id": "b", "text": "Brasília fica no litoral.", "correct": False, "marker": "F"},
        ],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["non-nfc-true-false-marker"] not in _codes(question.lint())


# --- essay.md:89, ordering.md:343 highlight is a recognized language -----


def test_essay_unrecognized_highlight_language_reports_info() -> None:
    doc = {
        "type": "essay",
        "stem": "Escreva uma função que calcule o MDC.",
        "input": "code",
        "highlight": "not-a-real-pygments-lexer-xyz",
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["unknown-highlight-language"] in _codes(question.lint())


def test_essay_recognized_highlight_language_does_not_warn() -> None:
    doc = {
        "type": "essay",
        "stem": "Escreva uma função que calcule o MDC.",
        "input": "code",
        "highlight": "python",
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["unknown-highlight-language"] not in _codes(question.lint())


def test_ordering_unrecognized_highlight_language_reports_info() -> None:
    doc = {
        "type": "ordering",
        "stem": "Ordene as linhas do algoritmo de Euclides para o MDC.",
        "content": "code",
        "highlight": "not-a-real-pygments-lexer-xyz",
        "lines": [[0, "a, b = b, a % b"], [0, "return a"]],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["unknown-highlight-language"] in _codes(question.lint())


def test_ordering_recognized_highlight_language_does_not_warn() -> None:
    doc = {
        "type": "ordering",
        "stem": "Ordene as linhas do algoritmo de Euclides para o MDC.",
        "content": "code",
        "highlight": "python",
        "lines": [[0, "a, b = b, a % b"], [0, "return a"]],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["unknown-highlight-language"] not in _codes(question.lint())


# --- essay.md:91 answerKey defined ---------------------------------------


def test_missing_answer_key_reports_info() -> None:
    doc = {"type": "essay", "stem": "Descreva o bioma da Caatinga.", "input": "text"}
    question = _load_ok(doc)
    assert _PROPOSED_CODES["missing-answer-key"] in _codes(question.lint())


def test_defined_answer_key_does_not_warn() -> None:
    doc = {
        "type": "essay",
        "stem": "Descreva o bioma da Caatinga.",
        "input": "text",
        "answerKey": "Vegetação xerófila adaptada à semiaridez.",
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["missing-answer-key"] not in _codes(question.lint())


# --- numeric.md:153 domain agrees with the inferred domain --------------


def test_numeric_domain_narrower_than_inferred_reports_mismatch() -> None:
    """
    numeric.md, "Number type/domain": ranking is integer < fraction <
    decimal, and a declared domain never widens the value written in
    the body. `answer: "1/3"` is a fraction; declaring `domain:
    "integer"` contradicts it.
    """
    doc = {
        "type": "numeric",
        "stem": "Qual fração representa um terço?",
        "answer": "1/3",
        "domain": "integer",
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["domain-mismatch"] in _codes(question.lint())


def test_numeric_domain_matching_inferred_domain_does_not_warn() -> None:
    doc = {
        "type": "numeric",
        "stem": "Qual fração representa um terço?",
        "answer": "1/3",
        "domain": "fraction",
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["domain-mismatch"] not in _codes(question.lint())


# --- numeric.md:156 tolerance for a decimal or fraction answer ----------


def test_decimal_answer_without_tolerance_reports_missing_tolerance() -> None:
    doc = {"type": "numeric", "stem": "Qual é o valor de pi, com duas casas?", "answer": 3.14}
    question = _load_ok(doc)
    assert _PROPOSED_CODES["missing-tolerance"] in _codes(question.lint())


def test_decimal_answer_with_tolerance_does_not_warn() -> None:
    doc = {
        "type": "numeric",
        "stem": "Qual é o valor de pi, com duas casas?",
        "answer": 3.14,
        "tolerance": {"absolute": 0.01},
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["missing-tolerance"] not in _codes(question.lint())


# --- short-answer.md:383 accept holds a `*` wildcard ---------------------


def test_accept_wildcard_warns() -> None:
    doc = {
        "type": "short-answer",
        "stem": "Qual é a capital do Brasil?",
        "accept": ["Brasília", "*"],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["accept-wildcard"] in _codes(question.lint())


def test_accept_without_wildcard_does_not_warn() -> None:
    doc = {
        "type": "short-answer",
        "stem": "Qual é a capital do Brasil?",
        "accept": ["Brasília"],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["accept-wildcard"] not in _codes(question.lint())


# --- short-answer.md:385 regex flag accepted but ignored -----------------


def test_ignored_regex_flag_reports_info() -> None:
    """short-answer.md, "Regex flags": `m`/`g`/`s`/`u`/`v`/`y`/`d` are
    accepted but have no effect."""
    doc = {
        "type": "short-answer",
        "stem": "Qual é a capital do Brasil?",
        "regex": "/Bras[íi]lia/m",
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["ignored-regex-flag"] in _codes(question.lint())


def test_meaningful_regex_flag_does_not_warn() -> None:
    doc = {
        "type": "short-answer",
        "stem": "Qual é a capital do Brasil?",
        "regex": "/Bras[íi]lia/i",
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["ignored-regex-flag"] not in _codes(question.lint())


# --- short-answer.md:386 reject `*` not the last item --------------------


def test_reject_wildcard_not_last_reports_unreachable() -> None:
    doc = {
        "type": "short-answer",
        "stem": "Qual é a capital do Brasil?",
        "accept": ["Brasília"],
        "reject": ["*", "Rio de Janeiro"],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["unreachable-reject"] in _codes(question.lint())


def test_reject_wildcard_last_does_not_warn() -> None:
    doc = {
        "type": "short-answer",
        "stem": "Qual é a capital do Brasil?",
        "accept": ["Brasília"],
        "reject": ["Rio de Janeiro", "*"],
    }
    question = _load_ok(doc)
    assert _PROPOSED_CODES["unreachable-reject"] not in _codes(question.lint())


# =======================================================================
# Section D: critical rules to verify
# =======================================================================


def test_forbidden_block_element_in_stem_from_a_yaml_document_is_an_error() -> None:
    """
    base.md:250, also for documents built from YAML/JSON. `load` is
    given a `Mapping` directly here (no markdown parse step at all), so
    if this is enforced only at parse time -- rather than as a model
    rule -- this document would wrongly slip through.

    An H1 heading is one of base.md's "Forbidden elements". The spec
    gives no code for this rule, so a small set of plausible codes is
    accepted -- see `_FORBIDDEN_ELEMENT_CODES`.
    """
    _FORBIDDEN_ELEMENT_CODES = {
        "forbidden-block-element",
        "forbidden-stem-element",
        "forbidden-element",
    }
    doc = {
        "type": "essay",
        "stem": "# Bioma predominante no Nordeste",
        "input": "text",
    }
    loaded = load(doc)
    assert loaded.document is None, (
        "base.md:250 (forbidden block elements in preamble/epilogue/stem, "
        "also for YAML/JSON documents) is not enforced: the document loaded "
        f"cleanly with diagnostics {loaded.diagnostics!r}"
    )
    assert any(d.severity == "error" for d in loaded.diagnostics)
    codes = _codes(loaded.diagnostics)
    assert codes & _FORBIDDEN_ELEMENT_CODES, (
        f"expected one of {_FORBIDDEN_ELEMENT_CODES!r}, got {codes!r}"
    )


def test_blank_marker_outside_a_plain_text_run_is_an_error() -> None:
    """
    fill-in.md:301: a `[^id]` marker may only appear in a plain text run
    of a paragraph. Here it sits inside an emphasis span
    (`**[^cap]**`), not a plain run. The spec gives no code, so a small
    set of plausible codes is accepted -- see `_BLANK_PLACEMENT_CODES`.
    """
    _BLANK_PLACEMENT_CODES = {
        "blank-outside-plain-text",
        "misplaced-blank",
        "invalid-blank-placement",
    }
    doc = {
        "type": "fill-in",
        "stem": "A capital do Brasil é **[^capital]**.",
        "blanks": [
            {"id": "capital", "type": "short-answer", "oneOf": ["Brasília"]},
        ],
    }
    loaded = load(doc)
    assert loaded.document is None, (
        "fill-in.md:301 (a blank may only appear in a plain text run) is not "
        f"enforced: the document loaded cleanly with diagnostics {loaded.diagnostics!r}"
    )
    assert any(d.severity == "error" for d in loaded.diagnostics)
    codes = _codes(loaded.diagnostics)
    assert codes & _BLANK_PLACEMENT_CODES, f"expected one of {_BLANK_PLACEMENT_CODES!r}, got {codes!r}"


def test_true_false_marker_disagreeing_with_correct_is_an_error() -> None:
    """
    true-false.md:210: the marker must agree with `correct` according to
    its category (TRUE/FALSE/PROVISIONAL). Here `marker: "F"` (a FALSE
    marker) is paired with `correct: true` -- a direct contradiction.
    """
    doc = {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre o Brasil.",
        "choices": [
            {
                "id": "a",
                "text": "O Brasil faz fronteira com todos os países da América do Sul, exceto Chile e Equador.",
                "correct": True,
                "marker": "F",
            },
            {"id": "b", "text": "A Lua é feita de queijo.", "correct": False, "marker": "F"},
        ],
    }
    loaded = load(doc)
    assert loaded.document is None, (
        "true-false.md:210 (marker agrees with correct) is not enforced: "
        f"the document loaded cleanly with diagnostics {loaded.diagnostics!r}"
    )
    assert any(d.severity == "error" for d in loaded.diagnostics)


def test_accept_as_both_body_block_and_frontmatter_field_is_an_error() -> None:
    """
    short-answer.md:379: `accept`/`reject` must not be written as a body
    block and a frontmatter field at the same time. Built from real
    Markdown source (not a dict): the ambiguity only exists when a
    document is parsed, since a `dict`/YAML document has no "body
    block" spelling to collide with. The spec gives no code, so a small
    set of plausible codes is accepted -- see `_DOUBLE_ANSWER_KEY_CODES`.
    """
    _DOUBLE_ANSWER_KEY_CODES = {
        "duplicate-answer-key",
        "accept-block-and-field",
        "conflicting-accept",
    }
    source = (
        "---\n"
        "id: sa-capital\n"
        "accept:\n"
        "  - Brasília\n"
        "---\n"
        "\n"
        "Qual é a capital do Brasil?\n"
        "\n"
        "[short-answer/accept]:\n"
        "* Brasília\n"
    )
    loaded = load(source, kind="question", format="mdq")
    assert loaded.document is None, (
        "short-answer.md:379 (accept/reject as both a body block and a "
        f"frontmatter field) is not enforced: loaded cleanly with "
        f"diagnostics {loaded.diagnostics!r}"
    )
    assert any(d.severity == "error" for d in loaded.diagnostics)
    codes = _codes(loaded.diagnostics)
    assert codes & _DOUBLE_ANSWER_KEY_CODES, f"expected one of {_DOUBLE_ANSWER_KEY_CODES!r}, got {codes!r}"
