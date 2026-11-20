"""
What the upload question and its converters share: the limits of a file
(size, extension) as upload.md defines them.
"""

from __future__ import annotations

import re
from fractions import Fraction

__all__ = [
    "ASCII_FOLD",
    "EXTENSION_RE",
    "MAX_SAFE_INTEGER",
    "size_to_bytes",
]


#: The largest integer every implementation holds exactly: 2^53 - 1.
MAX_SAFE_INTEGER = 9007199254740991

#: One extension, upload.md, "Extensions".
EXTENSION_RE = re.compile(r"\.[a-z0-9][a-z0-9._+-]*")

#: Folds only `A` to `Z`, whatever the locale: `str.lower` would also fold
#: the Kelvin sign and `İ`.
ASCII_FOLD = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}

#: The `maxSize` string of upload.md, "Size". The unit is in upper case.
_SIZE_STRING = re.compile(r"([0-9]+(?:\.[0-9]{1,3})?) ?(B|KB|MB|GB)")

#: The power of 1024 of each unit.
_UNIT_POWER = {"B": 0, "KB": 1, "MB": 2, "GB": 3}


def size_to_bytes(value: object) -> int:
    """
    The bytes of a valid `maxSize`, as written.

    Raises:
        ValueError: `value` is not an integer (a bool is not) or a size
            string, or it rounds down to 0 bytes or is larger than 2^53 - 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("must be an integer of bytes or a size such as '5 MB'")
    if isinstance(value, int):
        number = value
    else:
        match = _SIZE_STRING.fullmatch(value)
        if match is None:
            raise ValueError("must be an integer of bytes or a size such as '5 MB'")
        number = int(Fraction(match[1]) * 1024 ** _UNIT_POWER[match[2]])  # rounds down
    if not 1 <= number <= MAX_SAFE_INTEGER:
        raise ValueError(f"must be from 1 to {MAX_SAFE_INTEGER} bytes")
    return number
