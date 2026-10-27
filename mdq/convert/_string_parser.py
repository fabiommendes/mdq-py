from __future__ import annotations

import re
from collections import deque
from re import Pattern
from typing import NoReturn

from ..errors import ParseError

WS_REGEX = re.compile(r"\s+")


class ParserError(ParseError):
    """
    A syntax error of an external format, with its place in the source.

    It is a `ParseError`, and so a `ValueError`. `lineno` and `colno` are
    0-based.
    """

    def __init__(self, message: str, lineno: int, colno: int):
        super().__init__(message)
        self.lineno = lineno
        self.colno = colno

    def __str__(self) -> str:
        return f"[line {self.lineno + 1}, col {self.colno + 1}]: {self.message}"


def fail_at(source: str, offset: int, message: str) -> NoReturn:
    """Raise a `ParserError` located at the character `offset` of `source`."""
    prefix = source[:offset]
    raise ParserError(message, prefix.count("\n"), offset - prefix.rfind("\n") - 1)


class StringParser[T]:
    """
    Parser primitives for string-based formats.

    The parser always break on lines.
    """

    def __init__(self, source: str):
        self.source = source
        self.original_lines = source.splitlines()
        self.lineno = 0
        self.colno = 0
        self.lines = deque(self.original_lines)

    def parse(self) -> T:
        """
        Parse question.
        """
        result = self.start()
        self.ws()
        if self.lines:
            i = self.lineno + 1
            j = len(self.lines)
            raise ParserError(f"unparsed lines: {i}:{j}", self.lineno, self.colno)
        return result

    def start(self) -> T:
        """
        Start the recursive descent.
        """
        raise NotImplementedError

    def peek(self) -> str:
        """
        Peek the next line.
        """
        try:
            return self.lines[0]
        except IndexError:
            return ""

    def read(self) -> str:
        """
        Read the next line.
        """
        try:
            result = self.lines.popleft()
        except IndexError:
            self.error("EOF reached")

        self.lineno += 1
        self.colno = 0
        return result

    def ws(self) -> None:
        """
        Consume whitespace and empty lines.
        """
        while self.lines and (not self.lines[0] or self.lines[0].isspace()):
            self.read()
        if m := WS_REGEX.match(self.peek()):
            self.colno += m.end()
            self.lines[0] = self.lines[0][m.end() :]

    def expect(
        self,
        pattern: str | Pattern[str],
        /,
        message: str | None = None,
        *,
        full: bool = False,
        raw: bool = False,
    ) -> str:
        """
        Expect pattern and raise ParserError if not match.
        """
        match = self.match(pattern, full=full, raw=raw)
        if match is None:
            if message is None:
                message = f"expect: {pattern!r}"
            self.error(message)
        return match

    def match(
        self, pattern: str | Pattern[str], /, *, full: bool = False, raw: bool = False
    ) -> str | None:
        """
        Match line against regex pattern.

        Consume the string and return it, if match. Return None if there is no Match.
        """

        if raw and isinstance(pattern, str):
            if full:
                return self.read() if self.peek() == pattern else None

            if self.peek().startswith(pattern):
                if self.lines[0] == pattern:
                    return self.read()
                self.lines[0] = self.lines[0][len(pattern) :]
                self.colno += len(pattern)
                return pattern
            return None

        if not isinstance(pattern, Pattern):
            pattern = re.compile(pattern)

        result = self.match_group(pattern, full=full)
        return None if result is None else result[""]

    def match_group(
        self, pattern: Pattern[str], /, *, full: bool = False
    ) -> dict[str, str] | None:
        """
        Match line against regex pattern.

        Consume the string and return it, if match. Return None if there is no Match.
        """

        go = pattern.fullmatch if full else pattern.match

        if m := go(self.peek()):
            start, end = m.span()
            value = m.group(0)
            self.lines[0] = self.lines[0][end:]
            self.colno += end

            if not self.lines[0]:
                self.lines.popleft()
                self.lineno += 1
                self.colno = 0

            return {**m.groupdict(), "": value}

        return None

    def error(self, message: str) -> NoReturn:
        """
        Raise error
        """
        raise ParserError(message, self.lineno, self.colno)
