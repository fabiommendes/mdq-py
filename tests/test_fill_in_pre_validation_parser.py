"""
Parser side of `preAccept` and `preReject` in a fill-in question
(docs/question-types/fill-in.md "Frontmatter" [^7], "Short answer blanks"
and "Additional Rules" [^8]; docs/lint-codes.md `undefined-blank`).

The frontmatter keys are maps from blank id to a pattern list. In the
parsed document they are fields of the matching blank.
"""

from __future__ import annotations

from typing import Any

import pytest
from _corpus import EXAMPLES_ROOT, parsed_sibling

import mdq
from mdq import errors
from mdq._parser import parse_question

SOURCE = EXAMPLES_ROOT / "valid" / "fill-in" / "pre-validation-lints.mdq.md"

BODY = """
The Pantanal lies mostly in the state of [^state] and floods during the
[^season] season.

[^state/short-answer]:
* Mato Grosso do Sul
* Mato Grosso

[^season/short-answer]:
* rainy
* wet
"""


def _load(source: str) -> mdq.Loaded:
    return mdq.load(source, kind="question")


def _errors(loaded: mdq.Loaded) -> list[mdq.Diagnostic]:
    return [d for d in loaded.diagnostics if d.severity == "error"]


def _parse(frontmatter: str, body: str = BODY) -> dict[str, Any]:
    return dict(parse_question(f"---\n{frontmatter}---\n{body}"))


def _blank(parsed: dict[str, Any], blank_id: str) -> dict[str, Any]:
    (blank,) = [b for b in parsed["blanks"] if b["id"] == blank_id]
    return blank


#
# AC1: pre-lists land on the matching blank
#
ENTRY_FORMS = [
    pytest.param('["Mato Grosso"]', ["Mato Grosso"], id="plain-string"),
    pytest.param('["/^[A-Za-z ]+$/i"]', ["/^[A-Za-z ]+$/i"], id="regex-with-flags"),
    pytest.param('["`a.b`"]', ["`a.b`"], id="backtick-literal"),
    pytest.param(
        "\n      - pattern: /\\d+/\n        feedback: Write the name.\n",
        [{"pattern": "/\\d+/", "feedback": "Write the name."}],
        id="mapping-with-feedback",
    ),
    pytest.param(
        "\n      - pattern: /\\d+/\n        comment: Digits are not a name.\n",
        [{"pattern": "/\\d+/", "comment": "Digits are not a name."}],
        id="mapping-with-comment",
    ),
]


@pytest.mark.parametrize("key", ["preAccept", "preReject"])
@pytest.mark.parametrize(("yaml_list", "expected"), ENTRY_FORMS)
def test_entries_are_kept_as_written_on_the_blank(
    key: str, yaml_list: str, expected: list[Any]
) -> None:
    parsed = _parse(
        f"{key}:\n  state: {yaml_list}\n"
        if not yaml_list.startswith("\n")
        else f"{key}:\n  state:{yaml_list}"
    )
    assert _blank(parsed, "state")[key] == expected


def test_question_dict_has_no_pre_keys_and_no_warning() -> None:
    warnings: list[mdq.Diagnostic] = []
    parsed = parse_question(
        '---\npreAccept:\n  state: ["/^[A-Za-z ]+$/"]\n'
        'preReject:\n  season: ["/\\\\d+/"]\n---\n' + BODY,
        warnings=warnings,
    )
    assert "preAccept" not in parsed
    assert "preReject" not in parsed
    assert [w for w in warnings if w.code == "unknown-frontmatter-key"] == []


def test_load_reports_no_unknown_key_diagnostic() -> None:
    loaded = _load('---\npreAccept:\n  state: ["/a/"]\n---\n' + BODY)
    assert _errors(loaded) == []
    assert "unknown-frontmatter-key" not in [d.code for d in loaded.diagnostics]


def test_blank_not_in_the_map_has_no_pre_keys() -> None:
    parsed = _parse('preAccept:\n  state: ["/a/"]\npreReject:\n  state: ["/b/"]\n')
    other = _blank(parsed, "season")
    assert "preAccept" not in other
    assert "preReject" not in other


def test_both_maps_may_target_the_same_blank() -> None:
    parsed = _parse('preAccept:\n  state: ["/a/"]\npreReject:\n  state: ["/b/"]\n')
    blank = _blank(parsed, "state")
    assert blank["preAccept"] == ["/a/"]
    assert blank["preReject"] == ["/b/"]


def test_a_blank_in_only_one_map_has_only_that_key() -> None:
    parsed = _parse('preAccept:\n  state: ["/a/"]\npreReject:\n  season: ["/b/"]\n')
    state, season = _blank(parsed, "state"), _blank(parsed, "season")
    assert state["preAccept"] == ["/a/"]
    assert "preReject" not in state
    assert season["preReject"] == ["/b/"]
    assert "preAccept" not in season


def test_corpus_markdown_matches_its_yaml_sibling() -> None:
    from_md = mdq.load(SOURCE, kind="question")
    from_yaml = mdq.load(parsed_sibling(SOURCE), kind="question")
    assert _errors(from_md) == []
    assert from_md.document == from_yaml.document


def test_corpus_markdown_puts_the_lists_on_the_blanks() -> None:
    parsed = parse_question(SOURCE.read_text(encoding="utf-8"))
    assert _blank(parsed, "state")["preAccept"] == ["/^[A-Za-z ]+$/"]
    assert _blank(parsed, "season")["preReject"] == ["/\\d+/m"]


#
# AC2: undefined blank
#
@pytest.mark.parametrize("key", ["preAccept", "preReject"])
def test_key_that_is_not_a_blank_id_is_an_undefined_blank(key: str) -> None:
    loaded = _load(f'---\n{key}:\n  bioma: ["/a/"]\n---\n' + BODY)
    assert loaded.document is None
    [error] = _errors(loaded)
    assert error.code == "undefined-blank"
    assert error.severity == "error"
    assert tuple(error.path) == (key, "bioma")


@pytest.mark.parametrize("key", ["preAccept", "preReject"])
def test_undefined_blank_is_reported_once_even_next_to_valid_keys(key: str) -> None:
    loaded = _load(f'---\n{key}:\n  state: ["/a/"]\n  bioma: ["/a/"]\n---\n' + BODY)
    assert loaded.document is None
    assert [(d.code, tuple(d.path)) for d in _errors(loaded)] == [
        ("undefined-blank", (key, "bioma"))
    ]


@pytest.mark.parametrize("key", ["preAccept", "preReject"])
def test_undefined_blank_error_has_code_and_path(key: str) -> None:
    error = errors.UndefinedBlank("bioma", key)
    assert isinstance(error, errors.ParseError)
    assert error.code == "undefined-blank"
    assert tuple(error.path) == (key, "bioma")


#
# AC3: numeric and choice blanks, malformed maps
#
MIXED_BODY = """
The [^planet] has about [^moons] moons and a [^feature].

[^planet/short-answer]: Jupiter

[^moons/numeric]: 95 +- 5

[^feature]:
* [ ] mountain
* [*] storm
"""


@pytest.mark.parametrize("key", ["preAccept", "preReject"])
@pytest.mark.parametrize(("blank_id", "index"), [("moons", 1), ("feature", 2)])
def test_list_on_a_numeric_or_choice_blank_is_a_schema_error(
    key: str, blank_id: str, index: int
) -> None:
    loaded = _load(f'---\n{key}:\n  {blank_id}: ["/a/"]\n---\n' + MIXED_BODY)
    assert loaded.document is None
    [error] = _errors(loaded)
    assert error.code == "schema-error"
    assert error.severity == "error"
    assert tuple(error.path) == ("blanks", index, key)


@pytest.mark.parametrize("key", ["preAccept", "preReject"])
def test_map_that_is_a_list_is_a_parse_error(key: str) -> None:
    loaded = _load(f'---\n{key}:\n  - "/a/"\n---\n' + BODY)
    assert loaded.document is None
    assert "parse-error" in [d.code for d in _errors(loaded)]
