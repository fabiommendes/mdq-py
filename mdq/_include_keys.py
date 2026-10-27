"""
Hint for a key that misspells an exam include key (`include`,
`includeAll`), shared by the dict/YAML/JSON loader and the Markdown parser.
"""

from __future__ import annotations

from typing import Mapping

__all__ = ["include_key_hint", "misspelled_include_key"]

#: The include keys, written the way the spec spells them.
_INCLUDE_KEYS = ("include", "includeAll")


def _normalized_key(key: str) -> str:
    return key.replace("-", "").replace("_", "").lower()


def misspelled_include_key(entry: object) -> tuple[str, str] | None:
    """
    `(key, include_key)` for the first key of `entry` that misspells an
    include key, or None if none does.

    A key matches when it equals an include key once case, `-` and `_` are
    ignored. A key spelled exactly right is not a misspelling.
    """
    if not isinstance(entry, Mapping):
        return None
    for key in entry:
        if not isinstance(key, str) or key in _INCLUDE_KEYS:
            continue
        for include_key in _INCLUDE_KEYS:
            if _normalized_key(key) == include_key.lower():
                return key, include_key
    return None


def include_key_hint(entry: object) -> str:
    """
    ` (did you mean `includeAll` instead of `include-all`?)` for the first
    key of `entry` that misspells an include key, or `""` if none does.
    """
    found = misspelled_include_key(entry)
    if found is None:
        return ""
    key, include_key = found
    return f" (did you mean `{include_key}` instead of `{key}`?)"
