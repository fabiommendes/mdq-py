from __future__ import annotations

import importlib
from typing import Any, ClassVar, Literal

from ..models import Question
from ..types import QuestionType

CONVERSION_REGISTRY: dict[str, ConversionBase | str] = {}


#: The stem of a true/false question built from a group of statements that
#: share no leading paragraph. MDQ requires a stem with a visible character
#: (docs/question-types/base.md, "Additional Rules").
TRUE_FALSE_FALLBACK_STEM = "Mark each statement as true or false."


class ConversionBase[Q]:
    """
    Base class for conversion types.
    """

    supports: ClassVar[dict[QuestionType, Literal["import", "export", "both"]]]

    def to_mdq(self, external: Q, /) -> Question:
        """
        Import question to a MDQ representation.
        """
        raise NotImplementedError

    def from_mdq(self, mdq: Question, /) -> Q:
        """
        Convert MDQ question to the external question format
        """
        raise NotImplementedError

    def render(self, external: Q, /) -> str:
        """
        Render the external format as a string.
        """
        return str(external)

    def parse(self, source: str, /) -> Q:
        """
        Parse source code in the external format into the internal
        representation.
        """
        raise NotImplementedError


def register_format(format: str, *, converter: str | ConversionBase):
    """
    Associate a format to the given conversion class instance.
    """
    CONVERSION_REGISTRY[format.lower()] = converter


def load_converter(format: str) -> ConversionBase[Any]:
    """
    Load a conversion instance from the registry.
    """
    format = format.lower()
    try:
        converter = CONVERSION_REGISTRY[format]
    except KeyError:
        raise ValueError(f"Unknown format: {format}")

    if isinstance(converter, str):
        mod_name, cls_name = converter.split(":")
        mod = importlib.import_module(mod_name)
        converter_cls = getattr(mod, cls_name)
        if not (
            isinstance(converter_cls, type) and issubclass(converter_cls, ConversionBase)
        ):
            msg = f"invalid registry: {format} is not a valid converter"
            raise RuntimeError(msg)
        converter = converter_cls()
        CONVERSION_REGISTRY[format] = converter

    return converter


def import_question(source: str, /, *, format: str) -> Question:
    """
    Load a question in the given format from source.

    Args:
        source: Source code from the external question.
        format: The external question format.
    """

    converter = load_converter(format)
    external = converter.parse(source)
    return converter.to_mdq(external)


def export_question(question: Question, /, *, format: str):
    """
    Convert a mdq question to a different format.

    Renders the resulting source code.

    Args:
        source: Source code from the external question.
        format: The external question format.
    """
    converter = load_converter(format)
    if question.type not in converter.supports:
        msg = f"{format!r} does not support {question.type!r} questions"
        raise TypeError(msg)
    external = converter.from_mdq(question)
    return converter.render(external)
