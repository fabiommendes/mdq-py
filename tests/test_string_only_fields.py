"""
exam.md and base.md: `id`, `include` and `includeAll` take only a YAML
string. A number or boolean is not converted (`id: 2024` is not
`"2024"`). The corpus covers the rejected values; this module covers the
quoted form, whose `include` the corpus cannot hold (it would have to
resolve).
"""

from __future__ import annotations

from mdq import load


def test_quoted_values_are_strings() -> None:
    text = '---\nid: "2024"\n---\n\n# Prova\n\n---\ninclude: "2024"\n---\n'
    loaded = load(text, format="mdq")
    assert loaded.document is not None, loaded.diagnostics
    assert loaded.document.id == "2024"
