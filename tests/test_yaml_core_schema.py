"""
base.md, "Frontmatter": the frontmatter and YAML documents follow the YAML
1.2 Core schema. YAML 1.1 forms (`yes`, `on`, timestamps, base-60 `1:30`,
leading-zero octals, `_` in numbers) are plain strings or decimal numbers.
"""

from __future__ import annotations

import math

import mdq
from mdq._parser import load_yaml, parse_exam


def test_nan_is_a_float() -> None:
    assert math.isnan(load_yaml("value: .nan")["value"])


def test_include_yes_is_a_string_include() -> None:
    text = "# Prova\n\n---\ninclude: yes\n---\n"
    doc = parse_exam(text)
    assert doc["questions"][0] == {"include": "yes"}


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
