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
    Raised when a score is asked of a pending response (responses.md,
    "Pending"): one the question does not settle, such as any essay
    response, or a response that matches no pattern under
    `unmatched: manual`. An exam-level scorer reports these as pending
    instead; the single-question entry point has no such escape, so it
    refuses.
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


class UndefinedBlank(ParseError):
    """
    fill-in.md, "Additional Rules": a key of the frontmatter `preAccept`
    or `preReject` map is not the id of a declared blank. Carries the
    `undefined-blank` code and the `path` of the key, `(key, blank_id)`,
    so `mdq._loading._parse_error` reports it like the model does for a
    stem marker.
    """

    code = "undefined-blank"
    path: tuple[str | int, ...]

    def __init__(self, blank_id: str, key: str, node: Node | None = None):
        super().__init__(
            f"{key} has a key {blank_id!r} but no blank with that id is defined",
            node=node,
        )
        self.blank_id = blank_id
        self.key = key
        self.path = (key, blank_id)


class ForeignChoiceMarker(ParseError):
    """
    base.md, "Type inference": a choice value is not in the `value` rule
    of the question type, inferred or forced. Carries the
    `foreign-choice-marker` code and the `path` of the choice, so
    `mdq._loading._parse_error` reports where it is.
    """

    code = "foreign-choice-marker"
    path: tuple[str | int, ...]

    def __init__(
        self,
        value: str,
        question_type: str,
        path: tuple[str | int, ...],
        node: Node | None = None,
    ):
        super().__init__(
            f"[{value}] is not a {question_type} choice marker", node=node
        )
        self.value = value
        self.question_type = question_type
        self.path = path


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
