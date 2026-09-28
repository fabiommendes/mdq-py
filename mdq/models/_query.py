"""
The query language docs/exam.md recommends for `include-all`.

    query     : logic ("EXCEPT" slugs)?
    logic     : logic "OR" logic_and | logic_and
    logic_and : logic_and "AND" logic_not | logic_not
    logic_not : "NOT" logic_not | atom
    atom      : TAG | "(" logic ")"

A tag matches a question when it is equal to one of the question's
`tags`. The keywords are uppercase only: `and` is an ordinary tag.

`Query.select` evaluates a query against a `TagIndex` with set operations.
Each subquery evaluates to a set of ids or to the complement of one, so
`biome AND NOT draft` is `tagged("biome") - tagged("draft")`, and the index
only has to list every id (`TagIndex.ids`) when the whole query is a
complement, like `NOT draft`.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Protocol
from dataclasses import dataclass
from typing import NoReturn

from ..errors import MdqError

__all__ = [
    "Query",
    "QuerySyntaxError",
    "TagIndex",
    "parse_query",
    "is_standard_query",
]

KEYWORDS = frozenset({"AND", "OR", "NOT", "EXCEPT"})
_PUNCTUATION = frozenset("(),")

#: A token is a parenthesis, a comma, or a run of anything else that is
#: not whitespace.
_TOKEN_RE = re.compile(r"[(),]|[^\s(),]+")


class QuerySyntaxError(MdqError):
    """Raised when an `include-all` query does not follow the language."""


class TagIndex(Protocol):
    """The part of a question bank that a query reads."""

    def tagged(self, tag: str) -> Collection[str]:
        """The ids of the questions that carry `tag`."""
        ...

    def ids(self) -> Collection[str]:
        """The ids of every question. Only read for a query like `NOT draft`."""
        ...


@dataclass(frozen=True)
class _Ids:
    """A set of ids, or the complement of one when `negated` is set."""

    ids: frozenset[str]
    negated: bool = False

    def __invert__(self) -> _Ids:
        return _Ids(self.ids, not self.negated)

    def __and__(self, other: _Ids) -> _Ids:
        match self.negated, other.negated:
            case False, False:
                return _Ids(self.ids & other.ids)
            case False, True:
                return _Ids(self.ids - other.ids)
            case True, False:
                return _Ids(other.ids - self.ids)
            case _:
                return _Ids(self.ids | other.ids, negated=True)

    def __or__(self, other: _Ids) -> _Ids:
        # De Morgan: a | b == ~(~a & ~b).
        return ~(~self & ~other)


@dataclass(frozen=True)
class Tag:
    name: str

    def matches(self, tags: Collection[str]) -> bool:
        return self.name in tags

    def select(self, index: TagIndex) -> _Ids:
        return _Ids(frozenset(index.tagged(self.name)))


@dataclass(frozen=True)
class Not:
    operand: Expr

    def matches(self, tags: Collection[str]) -> bool:
        return not self.operand.matches(tags)

    def select(self, index: TagIndex) -> _Ids:
        return ~self.operand.select(index)


@dataclass(frozen=True)
class And:
    left: Expr
    right: Expr

    def matches(self, tags: Collection[str]) -> bool:
        return self.left.matches(tags) and self.right.matches(tags)

    def select(self, index: TagIndex) -> _Ids:
        return self.left.select(index) & self.right.select(index)


@dataclass(frozen=True)
class Or:
    left: Expr
    right: Expr

    def matches(self, tags: Collection[str]) -> bool:
        return self.left.matches(tags) or self.right.matches(tags)

    def select(self, index: TagIndex) -> _Ids:
        return self.left.select(index) | self.right.select(index)


type Expr = Tag | Not | And | Or


@dataclass(frozen=True)
class Query:
    """A parsed `include-all` query."""

    expr: Expr
    excluded: frozenset[str] = frozenset()

    def matches(self, tags: Collection[str], question_id: str) -> bool:
        """Report whether a question with these tags and id is selected."""
        return question_id not in self.excluded and self.expr.matches(tags)

    def select(self, index: TagIndex) -> set[str]:
        """Return the ids of the questions in `index` that match the query."""
        result = self.expr.select(index)
        if result.negated:
            selected = set(index.ids()) - result.ids
        else:
            selected = set(result.ids)
        return selected - self.excluded


def parse_query(text: str) -> Query:
    """
    Parse an `include-all` query.

    Raises:
        QuerySyntaxError: If `text` does not follow the language.

    Example:
        >>> query = parse_query("recursion AND NOT draft EXCEPT r-07")
        >>> query.matches({"recursion"}, "r-01")
        True
        >>> query.matches({"recursion"}, "r-07")
        False
    """
    return _Parser(text).parse()


def is_standard_query(text: str) -> bool:
    """Report whether `text` follows the recommended query language."""
    try:
        parse_query(text)
    except QuerySyntaxError:
        return False
    return True


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = _TOKEN_RE.findall(text)
        self.position = 0

    def parse(self) -> Query:
        expr = self._logic()
        excluded: frozenset[str] = frozenset()
        if self._accept("EXCEPT"):
            excluded = self._slugs()
        if self._peek() is not None:
            self._fail(f"unexpected {self._peek()!r}")
        return Query(expr, excluded)

    def _logic(self) -> Expr:
        expr = self._logic_and()
        while self._accept("OR"):
            expr = Or(expr, self._logic_and())
        return expr

    def _logic_and(self) -> Expr:
        expr = self._logic_not()
        while self._accept("AND"):
            expr = And(expr, self._logic_not())
        return expr

    def _logic_not(self) -> Expr:
        if self._accept("NOT"):
            return Not(self._logic_not())
        return self._atom()

    def _atom(self) -> Expr:
        if self._accept("("):
            expr = self._logic()
            if not self._accept(")"):
                self._fail("missing ')'")
            return expr
        token = self._peek()
        if token is None or token in KEYWORDS or token in _PUNCTUATION:
            self._fail(f"expected a tag, found {token or 'the end'!r}")
        self.position += 1
        return Tag(token)

    def _slugs(self) -> frozenset[str]:
        slugs = [self._slug()]
        while self._accept(","):
            slugs.append(self._slug())
        return frozenset(slugs)

    def _slug(self) -> str:
        token = self._peek()
        if token is None or token in KEYWORDS or token in _PUNCTUATION:
            self._fail(f"expected a question id, found {token or 'the end'!r}")
        self.position += 1
        return token

    def _peek(self) -> str | None:
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return None

    def _accept(self, token: str) -> bool:
        if self._peek() == token:
            self.position += 1
            return True
        return False

    def _fail(self, detail: str) -> NoReturn:
        raise QuerySyntaxError(f"invalid include-all query {self.text!r}: {detail}")
