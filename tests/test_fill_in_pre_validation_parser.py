"""
Parser side of `preAccept` and `preReject` in a fill-in question
(docs/question-types/fill-in.md "Frontmatter" [^7], "Short answer blanks"
and "Additional Rules" [^8]; docs/lint-codes.md `undefined-blank`).

The corpus covers the parsed shape (`valid/fill-in/pre-validation-*`) and
the errors (`invalid/fill-in-pre-*`). Only the error class contract is here.
"""

from __future__ import annotations

import pytest

from mdq import errors


@pytest.mark.parametrize("key", ["preAccept", "preReject"])
def test_undefined_blank_error_has_code_and_path(key: str) -> None:
    error = errors.UndefinedBlank("bioma", key)
    assert isinstance(error, errors.ParseError)
    assert error.code == "undefined-blank"
    assert tuple(error.path) == (key, "bioma")
