"""Tests for the mdq.linter checks -- the "beyond JSON Schema" rules
applied on top of schema validation (duplicate choice ids/texts, blank
text fields, multiple-choice needing a correct choice, ...).
"""

from __future__ import annotations

import pytest

from mdq import load


def _rules(diagnostics) -> set[str]:
    return {d.code for d in diagnostics}


# ---------------------------------------------------------------------
# blank-text-field: preamble, stem, epilogue, comment
# ---------------------------------------------------------------------


@pytest.mark.parametrize("field_name", ["preamble", "stem", "epilogue", "comment"])
def test_whitespace_only_text_field_warns(field_name: str) -> None:
    doc = {
        "type": "essay",
        "stem": "A perfectly fine stem.",
        "input": "text",
        field_name: "   \n\t  ",
    }
    warnings = load(doc).diagnostics
    assert "blank-text-field" in _rules(warnings)
    matching = [w for w in warnings if w.code == "blank-text-field"]
    assert matching[0].path == (field_name,)


def test_non_blank_text_fields_do_not_warn() -> None:
    doc = {
        "type": "essay",
        "stem": "Explain X.",
        "preamble": "Some context.",
        "epilogue": "Be concise.",
        "comment": "Internal note.",
        "input": "text",
    }
    assert load(doc).diagnostics == []


def test_missing_text_fields_do_not_warn() -> None:
    doc = {"type": "essay", "stem": "Explain X.", "input": "text"}
    assert load(doc).diagnostics == []


# ---------------------------------------------------------------------
# duplicate-choice-id / duplicate-choice-text are model errors now, not
# lint warnings -- see tests/test_unique_ids.py
# (dev/specs/to-do/unique-ids.md).
# ---------------------------------------------------------------------


def test_unique_choices_do_not_warn() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "x",
        "choices": [
            {"id": "a", "text": "A", "score": 1},
            {"id": "b", "text": "B"},
        ],
    }
    assert _rules(load(doc).diagnostics) == set()


def test_choices_without_id_are_not_flagged_as_duplicates() -> None:
    """Choice `id` is optional -- two choices both omitting it isn't a
    collision, and shouldn't be treated as one."""
    doc = {
        "type": "multiple-choice",
        "stem": "x",
        "choices": [
            {"text": "A", "score": 1},
            {"text": "B"},
        ],
    }
    assert _rules(load(doc).diagnostics) == set()


def test_choice_checks_do_not_apply_to_essay_or_numeric() -> None:
    essay_doc = {"type": "essay", "stem": "x", "input": "text"}
    numeric_doc = {"type": "numeric", "stem": "x", "answer": 4}
    assert load(essay_doc).diagnostics == []
    assert load(numeric_doc).diagnostics == []


# ---------------------------------------------------------------------
# multiple-choice-no-correct-choice
# ---------------------------------------------------------------------


def test_multiple_choice_without_any_correct_choice_warns() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "x",
        "choices": [{"id": "a", "text": "A", "score": 0}, {"id": "b", "text": "B"}],
    }
    warnings = load(doc).diagnostics
    assert "multiple-choice-no-correct-choice" in _rules(warnings)


def test_multiple_choice_with_a_correct_choice_does_not_warn() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "x",
        "choices": [{"id": "a", "text": "A", "score": 1}, {"id": "b", "text": "B"}],
    }
    warnings = load(doc).diagnostics
    assert "multiple-choice-no-correct-choice" not in _rules(warnings)


def test_only_multiple_choice_gets_the_correct_choice_check() -> None:
    """multiple-selection legitimately can have every choice be
    incorrect (e.g. 'select all prime numbers' with none listed), so it
    must NOT get the multiple-choice-only rule."""
    doc = {
        "type": "multiple-selection",
        "stem": "x",
        "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
    }
    assert "multiple-choice-no-correct-choice" not in _rules(
        load(doc).diagnostics
    )


# ---------------------------------------------------------------------
# severities: every rule always runs; a strict-only rule now reports at
# "info" rather than being gated by a level (see
# `dev/specs/to-do/loading-module.md`, "Severities of lint rules").
# ---------------------------------------------------------------------


def test_strict_only_rules_still_run_at_info_severity() -> None:
    doc = {"type": "numeric", "stem": "...", "answer": 4, "locale": "cn"}
    diagnostics = load(doc).diagnostics
    assert _rules(diagnostics) >= {"unexpanded-stem-ellipsis", "locale-lookalike-language"}
    info_codes = {d.code for d in diagnostics if d.severity == "info"}
    assert {"unexpanded-stem-ellipsis", "locale-lookalike-language"} <= info_codes


# ---------------------------------------------------------------------
# integration: warnings surface through `load` without affecting the
# document being built
# ---------------------------------------------------------------------


def test_load_reports_warnings_without_failing() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "x",
        "choices": [
            {"id": "a", "text": "A", "score": 0},
            {"id": "b", "text": "B", "score": 0},
        ],
    }
    loaded = load(doc)
    assert loaded
    assert not any(d.severity == "error" for d in loaded.diagnostics)
    assert "multiple-choice-no-correct-choice" in _rules(loaded.diagnostics)


# ---------------------------------------------------------------------
# generic: uuid, tags, stem shape, locale
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "uuid,rule",
    [
        # 13th char is the version nibble, 17th the variant nibble.
        ("123e4567-e89b-92d3-a456-426614174000", "uuid-unknown-version"),
        ("123e4567-e89b-12d3-c456-426614174000", "uuid-unknown-variant"),
    ],
)
def test_uuid_with_bad_version_or_variant_warns(uuid: str, rule: str) -> None:
    doc = {"type": "essay", "stem": "x", "uuid": uuid}
    assert rule in _rules(load(doc).diagnostics)


def test_well_formed_uuid_does_not_warn() -> None:
    doc = {
        "type": "essay",
        "stem": "x",
        "uuid": "123e4567-e89b-12d3-a456-426614174000",
    }
    assert _rules(load(doc).diagnostics) == set()


def test_malformed_uuid_is_left_to_the_schema() -> None:
    """A UUID of the wrong shape is a schema `pattern` failure; the
    linter must not pile a second, confusing message on top of it."""
    doc = {"type": "essay", "stem": "x", "uuid": "nope"}
    assert _rules(load(doc).diagnostics) == set()


def test_tag_containing_a_comma_warns() -> None:
    doc = {"type": "essay", "stem": "x", "tags": ["algorithms, complexity"]}
    assert "unsplit-tag-list" in _rules(load(doc).diagnostics)


def test_blank_tag_warns() -> None:
    doc = {"type": "essay", "stem": "x", "tags": ["ok", "  "]}
    warnings = load(doc).diagnostics
    assert "blank-tag" in _rules(warnings)
    assert [w for w in warnings if w.code == "blank-tag"][0].path == ("tags", 1)


def test_ordinary_tags_do_not_warn() -> None:
    doc = {"type": "essay", "stem": "x", "tags": ["algorithms", "complexity"]}
    assert _rules(load(doc).diagnostics) == set()


@pytest.mark.parametrize(
    "stem",
    [
        "## A heading",
        "* a list item",
        "1. an ordered item",
        "> a quote",
        "| a | table |",
        "```python",
    ],
)
def test_non_paragraph_stem_warns_at_strict(stem: str) -> None:
    doc = {"type": "essay", "stem": stem}
    assert "stem-not-a-paragraph" in _rules(load(doc).diagnostics)


def test_ordinary_stem_is_not_flagged_as_a_block() -> None:
    doc = {"type": "essay", "stem": "Explain why 2 + 2 = 4."}
    assert _rules(load(doc).diagnostics) == set()


def test_locale_lookalike_warns_but_real_locale_does_not() -> None:
    bad = {"type": "essay", "stem": "x", "locale": "cn"}
    good = {"type": "essay", "stem": "x", "locale": "zh-Hans-CN"}
    assert "locale-lookalike-language" in _rules(
        load(bad).diagnostics
    )
    assert _rules(load(good).diagnostics) == set()


# ---------------------------------------------------------------------
# choices: blank text, visual equivalence, one-correct-answer
# ---------------------------------------------------------------------


def test_whitespace_only_choice_text_warns() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "x",
        "choices": [{"text": "A", "score": 1}, {"text": "   "}],
    }
    warnings = load(doc).diagnostics
    assert "blank-choice-text" in _rules(warnings)


#: `visually-identical-choice-text` is removed: `duplicate-choice-text`
#: (a model error now) already compares choice texts the same way it
#: did -- see test_choice_text_that_differs_only_inside_a_code_span_does_not_error
#: and test_duplicate_choice_text_after_whitespace_normalization_is_a_model_error
#: in tests/test_unique_ids.py (dev/specs/to-do/unique-ids.md).


def test_multiple_choice_with_two_correct_choices_warns() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "x",
        "choices": [
            {"id": "a", "text": "A", "score": 1},
            {"id": "b", "text": "B", "score": 1},
        ],
    }
    assert "multiple-choice-many-correct-choices" in _rules(
        load(doc).diagnostics
    )


def test_partial_credit_choices_are_not_correct_answers() -> None:
    """A question where every choice carries partial credit still has no
    full-credit answer."""
    doc = {
        "type": "multiple-choice",
        "stem": "x",
        "choices": [
            {"id": "a", "text": "A", "score": 0.5},
            {"id": "b", "text": "B", "score": 0.5},
        ],
    }
    rules = _rules(load(doc).diagnostics)
    assert "multiple-choice-no-correct-choice" in rules
    assert "multiple-choice-many-correct-choices" not in rules


# ---------------------------------------------------------------------
# true-false markers
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "marker", ["T", "V", "S", "F", "t", "v", "s", "f", "对", "真", "错", "偽"]
)
def test_assigned_true_false_markers_do_not_warn(marker: str) -> None:
    doc = {
        "type": "true-false",
        "stem": "x",
        "choices": [
            {
                "text": "A",
                "marker": marker,
                "correct": marker.upper() not in ("F", "错", "偽"),
            },
            {"text": "B", "marker": "F"},
        ],
    }
    assert _rules(load(doc).diagnostics) == set()


@pytest.mark.parametrize("marker", ["N", "D", "W", "n"])
def test_provisional_marker_warns(marker: str) -> None:
    """true-false.md: PROVISIONAL letters read as true today, but a later
    revision may reassign them, so implementations SHOULD warn."""
    doc = {
        "type": "true-false",
        "stem": "x",
        "choices": [{"text": "A", "marker": marker}, {"text": "B", "marker": "F"}],
    }
    assert "provisional-true-false-marker" in _rules(load(doc).diagnostics)


def test_indonesian_s_marker_warns_as_false_friend() -> None:
    """true-false.md#locale: `S` means true globally, but is the initial
    letter of Indonesian "salah" (false) -- flag it beyond the usual
    locale-mismatch notice, since it risks silent misgrading."""
    doc = {
        "type": "true-false",
        "stem": "x",
        "locale": "id",
        "choices": [
            {"text": "A", "marker": "S", "correct": True},
            {"text": "B", "marker": "F"},
        ],
    }
    rules = _rules(load(doc).diagnostics)
    assert "false-friend-true-false-marker" in rules
    assert "provisional-true-false-marker" not in rules


def test_multiple_selection_marker_is_reserved() -> None:
    doc = {
        "type": "true-false",
        "stem": "x",
        "choices": [{"text": "A", "marker": "X"}, {"text": "B", "marker": "F"}],
    }
    rules = _rules(load(doc).diagnostics)
    assert "reserved-true-false-marker" in rules
    assert "provisional-true-false-marker" not in rules


def test_marker_inconsistent_with_locale_warns_at_strict() -> None:
    """A pt-BR question normally writes V/F, not T/F."""
    doc = {
        "type": "true-false",
        "stem": "x",
        "locale": "pt-BR",
        "choices": [
            {"text": "A", "marker": "T", "correct": True},
            {"text": "B", "marker": "F"},
        ],
    }
    assert "locale-mismatched-true-false-marker" in _rules(
        load(doc).diagnostics
    )


def test_marker_consistent_with_locale_does_not_warn() -> None:
    doc = {
        "type": "true-false",
        "stem": "x",
        "locale": "pt-BR",
        "choices": [
            {"text": "A", "marker": "V", "correct": True},
            {"text": "B", "marker": "F"},
        ],
    }
    assert _rules(load(doc).diagnostics) == set()


def test_choices_without_markers_are_not_flagged() -> None:
    """`marker` is optional -- a document that only carries the boolean
    `answer` must lint clean."""
    doc = {
        "type": "true-false",
        "stem": "x",
        "choices": [{"text": "A", "correct": True}, {"text": "B"}],
    }
    assert _rules(load(doc).diagnostics) == set()


# ---------------------------------------------------------------------
# essay
# ---------------------------------------------------------------------


def test_highlight_without_code_input_warns() -> None:
    doc = {"type": "essay", "stem": "x", "input": "text", "highlight": "python"}
    assert "ignored-highlight" in _rules(load(doc).diagnostics)


def test_highlight_is_ignored_by_default_input_too() -> None:
    """`input` defaults to "text", so an omitted input still makes
    `highlight` a no-op."""
    doc = {"type": "essay", "stem": "x", "highlight": "python"}
    assert "ignored-highlight" in _rules(load(doc).diagnostics)


def test_code_input_without_highlight_warns() -> None:
    doc = {"type": "essay", "stem": "x", "input": "code"}
    assert "code-input-without-highlight" in _rules(load(doc).diagnostics)


def test_code_input_with_highlight_does_not_warn() -> None:
    doc = {"type": "essay", "stem": "x", "input": "code", "highlight": "python"}
    assert _rules(load(doc).diagnostics) == set()


# ---------------------------------------------------------------------
# short-answer
# ---------------------------------------------------------------------


def test_uncompilable_regex_warns() -> None:
    doc = {"type": "short-answer", "stem": "x", "regex": "([unclosed"}
    assert "invalid-regex" in _rules(load(doc).diagnostics)


def test_regex_shadows_the_accepted_answers() -> None:
    """short-answer.md: the frontmatter `regex` takes precedence, which
    leaves the body's answers unreachable."""
    doc = {"type": "short-answer", "stem": "x", "regex": "yes", "oneOf": ["yes"]}
    warnings = load(doc).diagnostics
    assert "shadowed-answers" in _rules(warnings)
    assert [w for w in warnings if w.code == "shadowed-answers"][0].path == ("oneOf",)


@pytest.mark.parametrize("regex", ["^yes", "yes$", "^yes$"])
def test_redundant_regex_anchors_warn_at_strict(regex: str) -> None:
    doc = {"type": "short-answer", "stem": "x", "regex": regex}
    assert "redundant-regex-anchor" in _rules(
        load(doc).diagnostics
    )


def test_short_answer_without_any_grading_strategy_warns() -> None:
    doc = {"type": "short-answer", "stem": "x"}
    assert "short-answer-not-gradable" in _rules(load(doc).diagnostics)


def test_open_ended_short_answer_does_not_need_an_answer() -> None:
    doc = {"type": "short-answer", "stem": "x", "openEnded": True}
    assert _rules(load(doc).diagnostics) == set()


def test_short_answer_with_accepted_answers_does_not_warn() -> None:
    doc = {"type": "short-answer", "stem": "x", "oneOf": ["Brasília"]}
    assert _rules(load(doc).diagnostics) == set()


# ---------------------------------------------------------------------
# numeric
# ---------------------------------------------------------------------


def test_integer_domain_with_a_fractional_answer_warns() -> None:
    doc = {"type": "numeric", "stem": "x", "answer": 3.5, "domain": "integer"}
    assert "answer-outside-domain" in _rules(load(doc).diagnostics)


def test_integer_domain_with_a_whole_answer_does_not_warn() -> None:
    doc = {"type": "numeric", "stem": "x", "answer": 4.0, "domain": "integer"}
    assert _rules(load(doc).diagnostics) == set()


def test_relative_tolerance_around_zero_warns() -> None:
    """`answer x relative` is 0 when the answer is 0, so the tolerance
    can never widen the accepted range."""
    doc = {
        "type": "numeric",
        "stem": "x",
        "answer": 0,
        "tolerance": {"relative": 0.05},
    }
    assert "relative-tolerance-around-zero" in _rules(load(doc).diagnostics)


def test_absolute_tolerance_around_zero_is_fine() -> None:
    doc = {
        "type": "numeric",
        "stem": "x",
        "answer": 0,
        "tolerance": {"absolute": 0.05},
    }
    assert _rules(load(doc).diagnostics) == set()


def test_relative_tolerance_written_as_a_percentage_warns_at_strict() -> None:
    """`relative` is a fraction (0.05 for 5%); a value of 5 means 500%."""
    doc = {"type": "numeric", "stem": "x", "answer": 10, "tolerance": {"relative": 5}}
    assert "relative-tolerance-over-one" in _rules(
        load(doc).diagnostics
    )


def test_decimal_places_ignored_for_integer_domain_warns_at_strict() -> None:
    doc = {
        "type": "numeric",
        "stem": "x",
        "answer": 4,
        "domain": "integer",
        "decimalPlaces": 2,
    }
    assert "ignored-decimal-places" in _rules(
        load(doc).diagnostics
    )


# ---------------------------------------------------------------------
# fill-in
# ---------------------------------------------------------------------


def _fill_in(stem: str, blanks: list) -> dict:
    return {"type": "fill-in", "stem": stem, "blanks": blanks}


def test_stem_referencing_an_undefined_blank_warns() -> None:
    doc = _fill_in(
        "The capital is [^capital] and the size is [^size].",
        [{"id": "capital", "type": "short-answer", "oneOf": ["Brasília"]}],
    )
    warnings = load(doc).diagnostics
    assert "undefined-blank" in _rules(warnings)


def test_blank_never_referenced_by_the_stem_warns() -> None:
    doc = _fill_in(
        "The capital is [^capital].",
        [
            {"id": "capital", "type": "short-answer", "oneOf": ["Brasília"]},
            {"id": "size", "type": "numeric", "answer": 2800000},
        ],
    )
    warnings = load(doc).diagnostics
    assert "unreferenced-blank" in _rules(warnings)
    matching = [w for w in warnings if w.code == "unreferenced-blank"]
    assert matching[0].path == ("blanks", 1, "id")


def test_inline_blank_type_is_stripped_from_the_marker() -> None:
    """fill-in.md writes `[^size/numeric]` to state a blank's type
    inline; the id is the part before the slash."""
    doc = _fill_in(
        "It has about [^size/numeric] habitants.",
        [{"id": "size", "type": "numeric", "answer": 2800000}],
    )
    rules = _rules(load(doc).diagnostics)
    assert "undefined-blank" not in rules
    assert "unreferenced-blank" not in rules


#: `duplicate-blank-id` is a model error now, not a lint warning -- see
#: test_duplicate_blank_id_is_a_model_error in tests/test_unique_ids.py
#: (dev/specs/to-do/unique-ids.md).


def test_blanks_inherit_the_checks_of_the_type_they_name() -> None:
    """A choice blank is graded like a multiple-choice question, a
    numeric blank like a numeric one -- so each gets those rules, with
    the path pointing into the blank."""
    doc = _fill_in(
        "[^pick] and [^count].",
        [
            {
                "id": "pick",
                "type": "multiple-choice",
                "choices": [{"text": "A"}, {"text": "B"}],
            },
            {
                "id": "count",
                "type": "numeric",
                "answer": 0,
                "tolerance": {"relative": 0.1},
            },
        ],
    )
    warnings = load(doc).diagnostics
    rules = _rules(warnings)
    assert "multiple-choice-no-correct-choice" in rules
    assert "relative-tolerance-around-zero" in rules
    by_rule = {w.code: w.path for w in warnings}
    assert by_rule["multiple-choice-no-correct-choice"] == ("blanks", 0, "choices")
    assert by_rule["relative-tolerance-around-zero"] == (
        "blanks",
        1,
        "tolerance",
        "relative",
    )


def test_well_formed_fill_in_does_not_warn() -> None:
    doc = _fill_in(
        "The capital of Brazil is [^capital]. It has about [^size] habitants.",
        [
            {
                "id": "capital",
                "type": "multiple-choice",
                "choices": [
                    {"id": "lisbon", "text": "Lisbon"},
                    {"id": "brasilia", "text": "Brasília", "score": 1},
                ],
            },
            {
                "id": "size",
                "type": "numeric",
                "answer": 2800000,
                "tolerance": {"relative": 0.1},
            },
        ],
    )
    assert _rules(load(doc).diagnostics) == set()
