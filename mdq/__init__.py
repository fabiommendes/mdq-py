"""mdq: tools for the MDQ (Markdown Questions) file format."""

from importlib.metadata import version as _version

from ._banks import DictLoader, FileLoader, QuestionBank
from ._loading import Diagnostic, Loaded, Severity, load, parse
from ._sync import sync_question
from .errors import InvalidDocument, MdqError, SyncError
from .models import Exam, Question

__version__ = _version("mdq")
# r2: adr-0014
__all__ = [
    "load",
    "parse",
    "sync_question",
    "Loaded",
    "Diagnostic",
    "Severity",
    "Question",
    "Exam",
    "QuestionBank",
    "FileLoader",
    "DictLoader",
    "MdqError",
    "InvalidDocument",
    "SyncError",
]
