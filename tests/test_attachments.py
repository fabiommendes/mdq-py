"""
question-base.md, "Attachments", and exam.md, "Attachments": the cases that
the corpus in `examples/` does not hold, such as the Markdown that the models
write and the path of a warning inside an exam.
"""

from __future__ import annotations

import mdq
from mdq import models
from mdq._parser import parse_exam, parse_question

STEM = "Qual é a vazão média do rio São Francisco em Sobradinho, em m³/s?\n\n[numeric]: 2000\n"


def _codes(loaded: mdq.Loaded) -> list[tuple[str, tuple[str | int, ...]]]:
    return [(d.code, tuple(d.path)) for d in loaded.diagnostics]


def test_render_escapes_the_label_the_origin_and_the_info_string() -> None:
    question = models.NumericQuestion.model_validate(
        {
            "type": "numeric",
            "stem": "Qual é a vazão?",
            "answer": 2000,
            "attachments": [
                {
                    "name": "a&b.csv",
                    "format": "csv",
                    "origin": "dados de 2024/a&b.csv",
                    "label": "**vazões** [2024] `csv` <b> a_b\\c",
                },
                {"name": "conta&base.py", "format": "py&", "text": "```\nprint(1)\n"},
                {"name": "(mapa).pdf", "format": "pdf", "origin": "(mapa).pdf"},
            ],
        }
    )
    parsed = parse_question(question.render())
    assert parsed.get("attachments") == question.to_dict()["attachments"]


def test_the_render_of_an_ordering_puts_the_section_after_extra() -> None:
    source = (
        "Ordene.\n\n[ordering]:\n* a\n* b\n\n## [reject]\n\n* b\n* a\n\n"
        "## [attachments]\n\n[mapa](mapa.pdf)\n\n## [extra]\n\n* c\n"
    )
    loaded = mdq.load(source)
    assert loaded.document is not None
    rendered = loaded.document.render()
    headings = [line for line in rendered.splitlines() if line.startswith("## [")]
    assert headings == ["## [extra]", "## [attachments]", "## [reject]"]
    assert mdq.load(rendered).document == loaded.document


def test_a_second_section_in_an_ordering_is_a_parse_error() -> None:
    source = (
        "Ordene.\n\n[ordering]:\n* a\n* b\n\n## [attachments]\n\n[mapa](mapa.pdf)\n\n"
        "## [extra]\n\n* c\n\n## [attachments]\n\n[mapa](outro.pdf)\n"
    )
    assert _codes(mdq.load(source)) == [("parse-error", ())]


def test_a_heading_that_is_not_a_section_in_the_attachments_is_a_parse_error() -> None:
    source = STEM + "\n## [attachments]\n\n[vazões](vazoes.csv)\n\n## [hints]\n\nUse a tabela.\n"
    assert _codes(mdq.load(source)) == [("parse-error", ())]


def test_an_exam_with_only_the_section_has_no_instructions() -> None:
    exam = parse_exam("# Prova\n\n## [attachments]\n\n[mapa.pdf](mapa.pdf)\n\n===\n\n" + STEM)
    assert "instructions" not in exam
    assert exam["attachments"] == [{"name": "mapa.pdf", "format": "pdf", "origin": "mapa.pdf"}]


def test_another_bracket_heading_stays_in_the_instructions() -> None:
    exam = parse_exam("# Prova\n\nLeia.\n\n## [mapas]\n\nVeja o anexo.\n\n===\n\n" + STEM)
    assert exam["instructions"] == "Leia.\n\n## [mapas]\n\nVeja o anexo."
    assert "attachments" not in exam


def test_a_setext_section_of_a_question_in_an_exam_warns_at_the_section() -> None:
    source = "# Prova\n\n===\n\n" + STEM + "\n[attachments]\n-------------\n\n[vazões](vazoes.csv)\n"
    loaded = mdq.load(source, kind="exam")
    assert loaded.document is not None
    assert ("setext-heading", ("questions", 0, "attachments")) in _codes(loaded)


def test_the_exam_render_writes_the_section_after_the_instructions() -> None:
    source = "# Prova\n\nLeia.\n\n## [attachments]\n\n[mapa](mapas/brasil.pdf)\n\n===\n\n" + STEM
    loaded = mdq.load(source, kind="exam")
    assert loaded.document is not None
    assert mdq.load(loaded.document.render(), kind="exam").document == loaded.document


def test_the_public_form_drops_the_origin_and_keeps_the_label() -> None:
    loaded = mdq.load(STEM + "\n## [attachments]\n\n[vazões](dados/vazoes.csv)\n")
    assert loaded.document is not None
    assert loaded.document.public()["attachments"] == [
        {"name": "vazoes.csv", "format": "csv", "label": "vazões"}
    ]


def test_a_parse_error_in_the_section_of_an_exam_gives_the_line_of_the_file() -> None:
    source = "---\nid: prova\n---\n# Prova\n\nLeia.\n\n## [attachments]\n\nTexto.\n\n===\n\n" + STEM
    [diagnostic] = mdq.load(source, kind="exam").diagnostics
    assert (diagnostic.code, diagnostic.line) == ("parse-error", 10)
