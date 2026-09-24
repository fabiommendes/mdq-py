"""
Resolution of `include:` references from an exam.

An exam may pull in a question that lives elsewhere rather than writing it
inline. Where "elsewhere" is depends entirely on the host: a directory of
files, a database, an HTTP question bank. The parser therefore never looks
anything up itself -- it delegates to a `QuestionLoader`, and this module
provides the obvious filesystem implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from .errors import MdqError

__all__ = [
    "IncludeNotFound",
    "QuestionLoader",
    "FileLoader",
    "DictLoader",
]

#: Extensions a question document may use. A question and an exam share
#: these -- they are told apart by their content, not by their name.
SOURCE_SUFFIXES = (".mdq.md", ".mdq")


class IncludeNotFound(MdqError):
    """Raised when a loader cannot resolve an `include:` reference."""

    def __init__(self, question_id: str, detail: str = "") -> None:
        message = f"cannot resolve included question {question_id!r}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
        self.question_id = question_id


@runtime_checkable
class QuestionLoader(Protocol):
    """
    Resolves an `include:` id to the question document it names.

    Implementations raise `IncludeNotFound` when the id names nothing.
    They return the question's source, not an already-parsed document:
    `str` for Markdown text (run through the same `load`/`parse`
    pipeline as any other Markdown source), or a `Mapping` for
    already-parsed data (skipping the parse step, exactly like a
    `Mapping` passed directly to `mdq.load`). Either way, a loader is
    free to serve questions that were never Markdown to begin with.
    """

    def load(self, question_id: str) -> str | Mapping[str, Any]: ...


class FileLoader:
    """
    Loads questions from a directory tree on the local filesystem.

    An id resolves to `<root>/<id>.mdq.md` or `<root>/<id>.mdq`. When
    `recursive` is set, the tree is searched for a file with that stem
    anywhere beneath the root, which is how a bank organised into
    per-topic subdirectories keeps working without qualifying every id.
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


class DictLoader:
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
