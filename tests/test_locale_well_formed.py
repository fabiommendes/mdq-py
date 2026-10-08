"""
base.md [^4]: `locale` MUST be a well-formed RFC 5646 (BCP 47) language
tag: the `langtag`, `privateuse` and grandfathered productions, taken
from the grammar alone. Whether a subtag is registered is not checked;
hosts that need validity bring their own registry.
"""

from __future__ import annotations

import pytest

import mdq

WELL_FORMED = [
    "en",
    "pt-BR",
    "zh-Hans-CN",
    "zh-Hant-TW",
    "sl-rozaj-biske",
    "de-CH-1901",
    "es-419",
    "en-US-u-ca-gregory",
    "x-interno",
    "en-x-private-use",
    "abcd",  # reserved 4-letter primary subtag
    "brasil",  # 5-8 letter primary subtag: well-formed, not registered
    "klingon",
    "i-klingon",  # grandfathered
    "en-GB-oed",
    "zh-min-nan",
    "ar-aao",  # extlang
    "PT-br",  # tags are case-insensitive
]

MALFORMED = [
    "",
    "p",
    "pt_BR",
    "pt--BR",
    "-pt",
    "pt-",
    "abcdefghi",  # 9 letters
    "123",
    "pt-B",
    "pt-12",
    "en-a",  # empty extension
    "x-",
    "pt-BR-",
]


def _load(locale: str) -> mdq.Loaded:
    return mdq.load({"type": "essay", "stem": "Disserte.", "locale": locale}, kind="question")


@pytest.mark.parametrize("locale", WELL_FORMED)
def test_well_formed_tag_is_accepted(locale: str) -> None:
    loaded = _load(locale)
    assert [d.code for d in loaded.diagnostics if d.severity == "error"] == []
    assert loaded.document.locale == locale


@pytest.mark.parametrize("locale", MALFORMED)
def test_malformed_tag_is_rejected(locale: str) -> None:
    loaded = _load(locale)
    errors = [d for d in loaded.diagnostics if d.severity == "error"]
    assert loaded.document is None
    assert [d.code for d in errors if d.code == "malformed-locale"] or [
        d.code for d in errors if d.code == "schema-error"
    ]


def test_exam_uses_the_same_rule() -> None:
    ok = mdq.load({"type": "exam", "title": "P", "locale": "brasil", "questions": []}, kind="exam")
    assert [d.code for d in ok.diagnostics if d.severity == "error"] == []
    bad = mdq.load({"type": "exam", "title": "P", "locale": "pt_BR", "questions": []}, kind="exam")
    assert "malformed-locale" in [d.code for d in bad.diagnostics]


def test_lookalike_language_is_still_an_info() -> None:
    loaded = _load("cn")
    assert "locale-lookalike-language" in [d.code for d in loaded.diagnostics]
