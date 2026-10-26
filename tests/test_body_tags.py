"""
Reserved tags, tag case, misplaced tags and adjacent lists
(docs/question-types/question-base.md, "Body tags").
"""

from __future__ import annotations

import pytest

import mdq

STEM = "Qual é a capital do Brasil?\n\n"


def _errors(source: str) -> list[tuple[str, str]]:
    loaded = mdq.load(source, format="mdq")
    return [(d.code, d.message) for d in loaded.diagnostics if d.severity == "error"]


@pytest.mark.parametrize(
    "source",
    [
        "Quanto é 13 + 13?\n\n[Numeric]: 26\n",
        "Quanto é 13 + 13?\n\n[NUMERIC(m)]: 26\n",
        STEM + "[Short-Answer]: Brasília\n",
        STEM + "[short-answer]: Brasília\n\n[SHORT-ANSWER/reject]: Rio\n",
        "A capital é [^cap].\n\n[^cap/Short-Answer]: Brasília\n",
        "Ordene.\n\n[Ordering]:\n* a\n* b\n",
        "Explique.\n\n[Essay]\n",
    ],
)
def test_a_known_tag_in_another_case_is_a_parse_error(source: str) -> None:
    [(code, message)] = _errors(source)
    assert code == "parse-error"
    assert message.startswith("tags are lower case: write `[")


def test_the_unit_of_a_numeric_tag_keeps_its_case() -> None:
    [(_, message)] = _errors("Pressão?\n\n[Numeric(Pa)]: 101325\n")
    assert message == "tags are lower case: write `[numeric(Pa)]:`"


@pytest.mark.parametrize(
    "tag", ["[short-answer/foo]: b", "[short-answer/foo]", "[^cap/foo]: x"]
)
def test_a_tag_with_an_unknown_suffix_is_a_parse_error(tag: str) -> None:
    source = "A capital é [^cap].\n\n" + tag + "\n" if "^" in tag else STEM + tag + "\n"
    [(code, message)] = _errors(source)
    assert code == "parse-error"
    assert message.startswith("unknown tag")


@pytest.mark.parametrize("name", ["preAccept", "preReject"])
def test_a_frontmatter_field_is_not_a_tag(name: str) -> None:
    source = STEM + f"[short-answer]: Brasília\n\n[short-answer/{name}]: Brasilia\n"
    [(code, message)] = _errors(source)
    assert code == "parse-error"
    assert "frontmatter only" in message


def test_an_ordinary_link_reference_definition_is_valid() -> None:
    source = STEM + "Veja o [IBGE][ibge].\n\n[short-answer]: Brasília\n\n[ibge]: https://www.ibge.gov.br\n"
    assert _errors(source) == []


@pytest.mark.parametrize(
    "source",
    [
        STEM + "[short-answer]: Brasília\n\nÉ uma cidade planejada.\n\n[short-answer/reject]: Rio\n",
        "Quanto é 13 + 13?\n\n[numeric]: 26\n\nSoma.\n\n[numeric]: 27\n",
        "Ordene.\n\n[ordering]:\n* a\n* b\n\nNota.\n\n[numeric]: 1\n",
        "Explique.\n\n[essay]\n\n[short-answer]: x\n",
    ],
)
def test_a_tag_in_the_epilogue_is_detached(source: str) -> None:
    codes = [code for code, _ in _errors(source)]
    assert codes == ["detached-tag"]


@pytest.mark.parametrize(
    "body",
    [
        "[short-answer]:\n* Brasília\n- Brasilia\n",
        "[short-answer]:\n* Brasília\n1. Brasilia\n",
    ],
)
def test_a_list_glued_to_a_content_list_is_a_parse_error(body: str) -> None:
    [(code, message)] = _errors(STEM + body)
    assert code == "parse-error"
    assert "same list marker" in message


def test_an_ordering_list_followed_by_a_list_is_a_parse_error() -> None:
    [(code, _)] = _errors("Ordene.\n\n[ordering]:\n* a\n* b\n1. c\n")
    assert code == "parse-error"


def test_a_choice_blank_list_followed_by_a_list_is_a_parse_error() -> None:
    source = "A capital é [^cap].\n\n[^cap]:\n* [*] Brasília\n* [ ] Lisboa\n- nota\n"
    [(code, _)] = _errors(source)
    assert code == "parse-error"


def test_a_list_after_a_blank_line_is_an_epilogue() -> None:
    question = mdq.parse(STEM + "[short-answer]:\n* Brasília\n\n1. Capital federal\n", format="mdq")
    assert question.epilogue == "1. Capital federal"
