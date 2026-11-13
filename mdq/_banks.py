"""
Question banks: where an exam's `include:` and `includeAll:` blocks find
their questions.

An exam may pull in questions that live elsewhere rather than writing them
inline. Where "elsewhere" is depends entirely on the host: a directory of
files, a database, an HTTP question bank. `mdq.load` therefore never looks
anything up itself. The host calls `Exam.resolve` with a `QuestionBank`,
and this module provides the obvious filesystem and in-memory ones.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Iterator, Mapping, Protocol, runtime_checkable

from .errors import IncludeNotFound, ParseError

__all__ = [
    "IncludeNotFound",
    "QuestionBank",
    "FileLoader",
    "DictLoader",
]

#: Extensions a question document may use, in lookup order: Markdown,
#: then YAML, then JSON (question-base.md, "File names"). A question and
#: an exam share these -- they are told apart by their content, not by
#: their name. Each `.mdq.*` suffix comes before its plain form so that
#: the id of `x.mdq.md` is `x`, not `x.mdq`.
SOURCE_SUFFIXES = (
    ".mdq.md",
    ".md",
    ".mdq",
    ".mdq.yaml",
    ".mdq.yml",
    ".yaml",
    ".yml",
    ".mdq.json",
    ".json",
)


@runtime_checkable
class QuestionBank(Protocol):
    """
    The questions an exam can include, by id and by tag.

    `load` returns the question's source, not a parsed document: `str`
    for Markdown text, or a `Mapping` for already-parsed data. It raises
    `IncludeNotFound` when the id names nothing.

    `tagged` and `ids` are what an `includeAll:` query reads (see
    `mdq.models._query`). `ids` is only called for a query that selects by
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


@dataclass(frozen=True)
class _Index:
    """The ids of a bank's questions, and which of them carry each tag."""

    by_tag: Mapping[str, frozenset[str]]
    ids: frozenset[str]


class _IndexedBank:
    """
    `tagged`/`ids` for a bank that can list its sources: every source is
    read and validated once, the first time a query needs the index (the
    index is cached for the life of the bank). A source that is not a
    valid question is left out of the index, silently.
    """

    def _sources(self) -> Iterator[tuple[str, str | Mapping[str, Any]]]:
        raise NotImplementedError

    def tagged(self, tag: str) -> Collection[str]:
        return self._index.by_tag.get(tag, frozenset())

    def ids(self) -> Collection[str]:
        return self._index.ids

    @cached_property
    def _index(self) -> _Index:
        by_tag: dict[str, set[str]] = {}
        ids: set[str] = set()
        for question_id, source in self._sources():
            tags = _tags(source)
            if tags is None:
                continue
            ids.add(question_id)
            for tag in tags:
                by_tag.setdefault(tag, set()).add(question_id)
        return _Index({tag: frozenset(found) for tag, found in by_tag.items()}, frozenset(ids))


class FileLoader(_IndexedBank):
    """
    Loads questions from a directory tree on the local filesystem.

    An id resolves to `<root>/<id><suffix>`, with the suffixes of
    `SOURCE_SUFFIXES` tried in order: Markdown first, then YAML, then
    JSON. When `recursive` is set, the tree
    is searched for a file with that stem anywhere beneath the root,
    which is how a bank organised into per-topic subdirectories keeps
    working without qualifying every id.
    `tagged` and `ids` only list the files that validate as a question: a
    file that holds an exam, a question with an error, or text that is not
    UTF-8 is skipped silently. When two files share an id, only the one
    `load` would pick is listed. `load` returns the text of a Markdown
    file and the data of a YAML or JSON file, valid or not, so an explicit
    `include` of an invalid question fails when the exam is resolved.
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
        return list(dict.fromkeys(found))

    def load(self, question_id: str) -> str | Mapping[str, Any]:
        for path in self.candidates(question_id):
            if path.is_file():
                return _read(path)

        raise IncludeNotFound(
            question_id,
            f"looked for {'/'.join(s for s in SOURCE_SUFFIXES)} under {self.root}",
        )

    def _sources(self) -> Iterator[tuple[str, str | Mapping[str, Any]]]:
        paths = self.root.rglob("*") if self.recursive else self.root.iterdir()
        # The file of each id that `load` would pick: a file directly in
        # the root, then the first suffix, then the first path.
        best: dict[str, tuple[tuple[bool, int, Path], Path]] = {}
        for path in sorted(paths):
            found = _question_id(path)
            if found is None or not path.is_file():
                continue
            question_id, rank = found
            key = (path.parent != self.root, rank, path)
            if question_id not in best or key < best[question_id][0]:
                best[question_id] = (key, path)
        for question_id, (_, path) in sorted(best.items()):
            try:
                yield question_id, _read(path)
            except (UnicodeDecodeError, ParseError):
                continue


class DictLoader(_IndexedBank):
    """
    Serves questions from an in-memory mapping of id to document.

    Useful for tests, and as the shape a host with its own question store
    would implement.

    `tagged` and `ids` only list the sources that validate as a question
    (see `FileLoader`). A mapping source follows the schema, so its
    `tags` must be a list of strings; a comma-separated string is not
    split.
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


def _question_id(path: Path) -> tuple[str, int] | None:
    """
    The id a question file answers to (its name, without the suffix), and
    the position of the suffix in `SOURCE_SUFFIXES`.
    """
    for rank, suffix in enumerate(SOURCE_SUFFIXES):
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)], rank
    return None


def _read(path: Path) -> str | Mapping[str, Any]:
    """
    The source in a question file: the text of a Markdown file, the data
    of a YAML or JSON file.

    Raises:
        UnicodeDecodeError: the file is not UTF-8.
        ParseError: the YAML or JSON does not parse.
    """
    # `_loading` imports this module for `SOURCE_SUFFIXES`.
    from . import _loading

    return _loading.read_source(path)


def _tags(source: str | Mapping[str, Any]) -> list[str] | None:
    """
    The tags of a question's source, or `None` if the source is not a
    valid question.

    The source is loaded and validated as a question, so an exam, a
    document with an error and a mapping that breaks the schema (an
    unknown `type`, `tags` that is not a list) are all `None`. Warnings do
    not disqualify a source.
    """
    # `_loading` imports this module for `SOURCE_SUFFIXES`.
    from . import _loading

    question = _loading.load(source, kind="question").document
    return None if question is None else list(question.tags)
