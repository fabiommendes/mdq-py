"""
base.md, "Frontmatter": the frontmatter and YAML documents follow the YAML
1.2 Core schema. YAML 1.1 forms (`yes`, `on`, timestamps, base-60 `1:30`,
leading-zero octals, `_` in numbers) are plain strings or decimal numbers.
The parse side is in `examples/normalize.yaml` and
`examples/valid/multiple-choice/yaml-core-schema`; what is left here is the
rendering.
"""

from __future__ import annotations

import mdq


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
