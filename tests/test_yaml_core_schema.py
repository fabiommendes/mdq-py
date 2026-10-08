"""
base.md, "Frontmatter": the frontmatter and YAML documents follow the YAML
1.2 Core schema. YAML 1.1 forms (`yes`, `on`, timestamps, base-60 `1:30`,
leading-zero octals, `_` in numbers) are plain strings or decimal numbers.
"""

from __future__ import annotations

import math

import pytest

import mdq
from mdq._parser import load_yaml, parse_exam, parse_question

CORE_SCALARS = [
    ("true", True),
    ("True", True),
    ("FALSE", False),
    ("null", None),
    ("~", None),
    ("", None),
    ("42", 42),
    ("-7", -7),
    ("010", 10),
    ("0o10", 8),
    ("0x1F", 31),
    ("1.5", 1.5),
    ("-2.", -2.0),
    (".5", 0.5),
    ("1e3", 1000.0),
    ("1E+3", 1000.0),
    (".inf", math.inf),
    ("-.Inf", -math.inf),
]

YAML_11_ONLY = [
    "yes",
    "no",
    "on",
    "off",
    "Yes",
    "NO",
    "y",
    "n",
    "1:30",
    "1:30:00",
    "2026-03-10",
    "2026-03-10 09:00:00-03:00",
    "2026-03-10T09:00:00Z",
    "0b101",
    "1_000",
    "1_000.5",
    "=",
    "<<",
]


@pytest.mark.parametrize(
    ("text", "value"), CORE_SCALARS, ids=[t or "empty" for t, _ in CORE_SCALARS]
)
def test_core_schema_scalar(text: str, value: object) -> None:
    assert load_yaml(f"value: {text}") == {"value": value}


def test_nan_is_a_float() -> None:
    assert math.isnan(load_yaml("value: .nan")["value"])


@pytest.mark.parametrize("text", YAML_11_ONLY)
def test_yaml_11_form_is_a_string(text: str) -> None:
    assert load_yaml(f"value: {text}") == {"value": text}


def test_quoted_scalars_stay_strings() -> None:
    assert load_yaml('a: "true"\nb: \'42\'\nc: "~"') == {
        "a": "true",
        "b": "42",
        "c": "~",
    }


def test_corpus_example_tags_and_meta() -> None:
    doc = mdq.load(
        "../examples/valid/multiple-choice/yaml-core-schema.mdq.md", kind="question"
    )
    question = mdq.load(
        __import__("pathlib").Path(
            "../examples/valid/multiple-choice/yaml-core-schema.mdq.md"
        )
    ).document
    assert question.tags == ["yes", "no", "on", "off", "1:30", "2026-03-10"]
    assert question.meta == {
        "octal": 8,
        "leading-zero": 10,
        "hex": 31,
        "flag": True,
        "nothing": None,
    }
    del doc


def test_include_yes_is_a_string_include() -> None:
    text = "# Prova\n\n---\ninclude: yes\n---\n"
    doc = parse_exam(text)
    assert doc["questions"][0] == {"include": "yes"}


def test_start_with_a_space_separator_is_a_string_and_normalizes() -> None:
    doc = parse_exam("---\nstart: 2026-03-10 09:00:00-03:00\n---\n\n# Exam\n")
    assert doc["start"] == "2026-03-10T09:00:00-03:00"


def test_duration_hh_mm_needs_no_quotes() -> None:
    doc = parse_exam("---\nduration: 1:30\n---\n\n# Exam\n")
    assert doc["duration"] == "PT1H30M"


def test_leading_zero_weight_is_decimal() -> None:
    doc = parse_question("---\nweight: 010\n---\n\nQual?\n\n* [*] A\n* [ ] B\n")
    assert doc["weight"] == 10


TRICKY_TAGS = ["0e0", "yes", "1:30", "010", "true", "2026-03-10", "null"]


def test_render_quotes_exactly_what_the_core_schema_needs() -> None:
    question = mdq.load(
        {"type": "essay", "stem": "Explique.", "tags": TRICKY_TAGS}, kind="question"
    ).document
    text = str(question)
    again = mdq.load(text, kind="question").document
    assert again.tags == TRICKY_TAGS
    frontmatter = text.split("---")[1]
    assert "- yes\n" in frontmatter and "- 1:30\n" in frontmatter
    assert "- '0e0'\n" in frontmatter and "- '010'\n" in frontmatter
