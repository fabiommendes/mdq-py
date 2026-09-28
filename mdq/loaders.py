"""
Question banks: where an exam's `include:` and `include-all:` blocks find
their questions.

An exam may pull in questions that live elsewhere rather than writing them
inline. Where "elsewhere" is depends entirely on the host: a directory of
files, a database, an HTTP question bank. `mdq.load` therefore never looks
anything up itself. The host calls `Exam.resolve` with a `QuestionBank`,
and this module provides the obvious filesystem and in-memory ones.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path
from typing import Any, Iterator, Mapping, Protocol, runtime_checkable

from . import _parser
from .errors import IncludeNotFound, MdqError

__all__ = [
    "IncludeNotFound",
    "QuestionBank",
    "FileLoader",
    "DictLoader",
]

#: Extensions a question document may use. A question and an exam share
#: these -- they are told apart by their content, not by their name.
SOURCE_SUFFIXES = (".mdq.md", ".mdq")


@runtime_checkable
class QuestionBank(Protocol):
    """
    The questions an exam can include, by id and by tag.

    `load` returns the question's source, not a parsed document: `str`
    for Markdown text, or a `Mapping` for already-parsed data. It raises
    `IncludeNotFound` when the id names nothing.

    `tagged` and `ids` are what an `include-all:` query reads (see
    `mdq.query`). `ids` is only called for a query that selects by
    exclusion alone, like `NOT draft`, so a large bank can serve most
    queries from a tag index without listing every question.
    """

    def load(self, question_id: str) -> str | Mapping[str, Any]:
        """The source of the question with this id."""
        ...

    def tagged(self, tag: str) -> Collection[str]:
        """The ids of the questions that carry `tag`."""
        ...

    def ids(self) -> Collection[str]:
        """The ids of every question in the bank."""
        ...


class _IndexedBank:
    """
    `tagged`/`ids` for a bank that can list its sources: every question
    is read once, the first time a query needs the index.
    """

    _index: dict[str, set[str]] | None = None
    _ids: set[str] | None = None

    def _sources(self) -> Iterator[tuple[str, str | Mapping[str, Any]]]:
        raise NotImplementedError

    def tagged(self, tag: str) -> Collection[str]:
        self._build_index()
        assert self._index is not None
        return self._index.get(tag, set())

    def ids(self) -> Collection[str]:
        self._build_index()
        assert self._ids is not None
        return self._ids

    def _build_index(self) -> None:
        if self._index is not None:
            return
        index: dict[str, set[str]] = {}
        ids: set[str] = set()
        for question_id, source in self._sources():
            tags = _tags(source)
            if tags is None:
                continue
            ids.add(question_id)
            for tag in tags:
                index.setdefault(tag, set()).add(question_id)
        self._index, self._ids = index, ids


class FileLoader(_IndexedBank):
    """
    Loads questions from a directory tree on the local filesystem.

    An id resolves to `<root>/<id>.mdq.md` or `<root>/<id>.mdq`. When
    `recursive` is set, the tree is searched for a file with that stem
    anywhere beneath the root, which is how a bank organised into
    per-topic subdirectories keeps working without qualifying every id.
    A file that holds an exam, or that does not parse, is not a question
    of the bank.
    """

    def __init__(self, root: Path | str, recursive: bool = True) -> None:
        self.root = Path(root)
        self.recursive = recursive

    def candidates(self, question_id: str) -> list[Path]:
        """Every path this loader would accept for `question_id`."""
        found = [self.root / f"{question_id}{suffix}" for suffix in SOURCE_SUFFIXES]
        if self.recursive:
            for suffix in SOURCE_SUFFIXES:
                found.extend(sorted(self.root.rglob(f"{question_id}{suffix}")))
        # Preserve order while dropping the duplicates rglob reintroduces
        # for files sitting directly in the root.
        seen, unique = set(), []
        for path in found:
            if path not in seen:
                seen.add(path)
                unique.append(path)
        return unique

    def load(self, question_id: str) -> str:
        for path in self.candidates(question_id):
            if path.is_file():
                return path.read_text(encoding="utf-8")

        raise IncludeNotFound(
            question_id,
            f"looked for {'/'.join(s for s in SOURCE_SUFFIXES)} under {self.root}",
        )

    def _sources(self) -> Iterator[tuple[str, str]]:
        paths = self.root.rglob("*") if self.recursive else self.root.iterdir()
        for path in sorted(paths):
            question_id = _question_id(path)
            if question_id is not None and path.is_file():
                yield question_id, path.read_text(encoding="utf-8")


class DictLoader(_IndexedBank):
    """
    Serves questions from an in-memory mapping of id to document.

    Useful for tests, and as the shape a host with its own question store
    would implement.
    """

    def __init__(self, questions: Mapping[str, str | Mapping[str, Any]]) -> None:
        self.questions = questions

    def load(self, question_id: str) -> str | Mapping[str, Any]:
        try:
            return self.questions[question_id]
        except KeyError:
            raise IncludeNotFound(question_id, "not in the mapping") from None

    def _sources(self) -> Iterator[tuple[str, str | Mapping[str, Any]]]:
        yield from self.questions.items()


def _question_id(path: Path) -> str | None:
    """The id a question file answers to: its name, without the suffix."""
    for suffix in SOURCE_SUFFIXES:
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    return None


def _tags(source: str | Mapping[str, Any]) -> list[str] | None:
    """The tags of a question's source, or `None` if it is not a question."""
    if isinstance(source, str):
        if _parser.is_exam(source):
            return None
        try:
            source = _parser.parse_question(source)
        except MdqError:
            return None
    if source.get("type") == "exam":
        return None
    tags = source.get("tags", [])
    if isinstance(tags, str):
        return [tag.strip() for tag in tags.split(",") if tag.strip()]
    return [str(tag) for tag in tags]
