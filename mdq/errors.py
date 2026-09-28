from markdown_it.tree import SyntaxTreeNode as Node


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


class ValidationError(MdqError):
    """
    Base class for errors that occur during validation of the exam markdown.
    """


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
    `openEnded` short answers. `score_exam` routes these to
    `ExamScore.pending` instead; the single-question entry point has no
    such escape, so it refuses.
    """


class EmptyQuestions(ParseError):
    """
    Raised when an exam has no questions.
    """

    _MESSAGE = "The exam contains no questions"


class NodesRemaining(ParseError):
    node: Node
    _MESSAGE: str = "There are unparsed nodes remaining"

    def __init__(self, node: Node, message: str | None = None):
        super().__init__(message or self._MESSAGE, node=node)


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
    wins. Carries its own `code` so `mdq.loading._parse_error` can report
    it as something more specific than the generic `parse-error`.
    """

    code = "conflicting-accept"
