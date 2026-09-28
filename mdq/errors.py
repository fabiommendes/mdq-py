from markdown_it.tree import SyntaxTreeNode as Node

from ._diagnostics import Diagnostic


class MdqError(ValueError):
    """
    Base class for errors that occur during parsing of the exam markdown.
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ParseError(MdqError):
    """
    Base class for errors that occur during parsing of the exam markdown.
    """

    def __init__(self, message: str, node: Node | None = None):
        super().__init__(message)
        self.node = node


class InvalidDocument(MdqError):
    """
    Raised by `Loaded.validate` when a diagnostic meets the severity
    threshold it was asked to enforce -- or there is no document at all.

    Carries every diagnostic `load` produced, not just the ones that
    triggered it, so a caller that only catches this exception still
    sees the full picture.
    """

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        summary = "; ".join(f"{d.severity} {d.code}: {d.message}" for d in diagnostics)
        super().__init__(summary or "invalid document")


class IncludeNotFound(MdqError):
    """Raised when a bank cannot resolve an included question id."""

    def __init__(self, question_id: str, detail: str = "") -> None:
        message = f"cannot resolve included question {question_id!r}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
        self.question_id = question_id


class GradingError(MdqError):
    """
    Base class for errors raised at the grading boundary.

    Every subclass means "this document or response is not ready to be
    graded", never "the student answered badly" -- a wrong answer is a
    score, not an error. An LMS integration can catch this one class to
    separate its own bugs from its students' mistakes.
    """


class MissingIdError(GradingError):
    """
    Raised when grading a document that is not addressable, i.e. one
    where some question or choice carries no id.

    Parsing never requires ids and the schemas do not either: the system
    using the library is expected to supply them, since it knows the
    filename, the database key and the attempt, and the document does
    not.
    """


class UnresolvedInclude(GradingError):
    """
    Raised when grading an exam that still holds an `include` entry.

    Includes resolve before a document becomes a model, so reaching the
    grading boundary with one means the resolution step was skipped.
    """


class ResponseError(GradingError):
    """
    Raised when a response cannot be graded against its question.

    Covers responses the question cannot represent -- a decimal answer
    to an `integer` question, a choice id that names nothing -- and, for
    exams, keys that name no question in the exam.
    """


class NotAutoGradable(GradingError):
    """
    Raised when a score is asked of a manually-graded question.

    Essays never carry a machine-checkable answer key, and neither do
    `openEnded` short answers. An exam-level scorer routes these into a
    pending set instead; the single-question entry point has no such
    escape, so it refuses.
    """


class MissingField(ParseError):
    field: str
    _MESSAGE: str = "A required field is missing"

    def __init__(
        self, field: str, node: Node | None = None, message: str | None = None
    ):
        super().__init__(message or self._MESSAGE, node=node)
        self.field = field


class IncompleteQuestion(ParseError):
    _MESSAGE: str = "Question ended before inferring its type"

    def __init__(self, message: str | None = None):
        super().__init__(message or self._MESSAGE)


class ConflictingAnswerKey(ParseError):
    """
    short-answer.md:379: `accept`/`reject` (or their `pre*` counterparts)
    are declared both as a frontmatter field and as a `[short-answer/
    accept]`/`[short-answer/reject]` body block -- two spellings of the
    same list that would otherwise silently disagree about which one
    wins. Carries its own `code` so `mdq._loading._parse_error` can report
    it as something more specific than the generic `parse-error`.
    """

    code = "conflicting-accept"
