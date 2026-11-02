"""
The presented form of a question (docs/public-form.md, "Presented form"):
the public form with opaque choice labels in place of the choice ids, in
an order that depends on a seed, and the translation of the responses
between the labels and the ids.

`Presentation` is one question for one seed. `ExamPresentation` is the
same for each question of an exam. Both keep no state beyond the label
maps, so a host can build them again at each request.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from ..errors import ResponseError
from ._base import BaseQuestion
from ._choice import (
    MultipleChoiceQuestion,
    MultipleSelectionQuestion,
    TrueFalseQuestion,
    require_choice_id,
)
from ._fill_in import ChoiceBlank, FillInQuestion

__all__ = ["Presentation", "ExamPresentation", "digest"]

#: The lengths of a label, in hex digits. A choice gets the shortest one
#: whose prefix of its digest no other choice of the scope shares.
LABEL_LENGTHS = (8, 16, 32, 64)


def digest(seed: str, *parts: str) -> str:
    """
    The SHA-256 of `seed` and the key `parts`, joined by U+0000 and
    encoded in UTF-8, as 64 lowercase hex digits.

    Raises:
        ValueError: `seed` or a part holds U+0000.
    """
    if any("\0" in part for part in (seed, *parts)):
        raise ValueError("a seed and a key part cannot hold U+0000")
    return hashlib.sha256("\0".join((seed, *parts)).encode("utf-8")).hexdigest()


class _Scope:
    """The choices that get their labels together, and their presented order."""

    def __init__(
        self, seed: str, prefix: tuple[str, ...], ids: Sequence[str], *, shuffle: bool
    ) -> None:
        digests = {cid: digest(seed, *prefix, cid) for cid in ids}
        self.labels = {
            cid: next(
                (
                    d[:n]
                    for n in LABEL_LENGTHS
                    if all(
                        o[:n] != d[:n] for other, o in digests.items() if other != cid
                    )
                ),
                d,
            )
            for cid, d in digests.items()
        }
        #: Label to choice id.
        self.ids = {label: cid for cid, label in self.labels.items()}
        self.order = sorted(ids, key=self.labels.__getitem__) if shuffle else list(ids)

    def present(self, choices: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """`choices` (public form) in the presented order, with labels as ids."""
        by_id = {choice["id"]: choice for choice in choices}
        return [{**by_id[cid], "id": self.labels[cid]} for cid in self.order]

    def lookup(self, value: object, *, to_label: bool) -> str:
        """
        The label of the id `value` (`to_label`), or else the id of the label.

        Raises:
            ResponseError: `value` is not a known id (or label).
        """
        table = self.labels if to_label else self.ids
        if not isinstance(value, str) or value not in table:
            kind = "choice id" if to_label else "choice label"
            raise ResponseError(f"unknown {kind} in a response: {value!r}")
        return table[value]


class Presentation:
    """
    The labels and the order of the choices of one question, for one seed.

    The labels are the prefix of SHA-256(seed, question id, [blank id,]
    choice id), see "Presented form" in `docs/public-form.md`. The seed
    must be unpredictable for the student: the host derives it, for
    example with an HMAC of a secret. This class does not handle secrets.

    Raises:
        ValueError: `seed` holds U+0000.
        MissingIdError: a choice has no id.
    """

    def __init__(
        self, question: BaseQuestion[Any], seed: str, *, shuffle: bool | None = None
    ) -> None:
        """
        `shuffle` overrides the effective `shuffle` of the question, which
        is the default. A fill-in question applies it to every choice blank.
        """
        digest(seed)  # rejects a seed with U+0000, even with no scope.
        if shuffle is None:
            effective = getattr(question, "effective_shuffle", None)
            shuffle = effective() if effective is not None else False
        qid = question.id or ""
        self._question = question
        self._scope: _Scope | None = None
        self._blanks: dict[str, _Scope] = {}
        if isinstance(
            question,
            (MultipleChoiceQuestion, MultipleSelectionQuestion, TrueFalseQuestion),
        ):
            ids = [require_choice_id(choice) for choice in question.choices]
            self._scope = _Scope(seed, (qid,), ids, shuffle=shuffle)
        elif isinstance(question, FillInQuestion):
            for blank in question.blanks:
                if isinstance(blank, ChoiceBlank):
                    ids = [require_choice_id(choice) for choice in blank.choices]
                    self._blanks[blank.id] = _Scope(
                        seed, (qid, blank.id), ids, shuffle=shuffle
                    )

    def public(self) -> dict[str, Any]:
        """
        The presented form: the public form of the question with the
        choices of each scope in the presented order and a label in the
        place of each choice id.

        Raises:
            MissingIdError: a choice has no id.
        """
        public = self._question.public()
        if self._scope is not None:
            public["choices"] = self._scope.present(public["choices"])
        for blank in public.get("blanks", []):
            scope = self._blanks.get(blank["id"])
            if scope is not None:
                blank["choices"] = scope.present(blank["choices"])
        return public

    def to_response(self, presented: object) -> object:
        """
        Translate a presented response (with labels) into the response
        that grading takes (with ids).

        Raises:
            ResponseError: a label is not in its scope, or the response
                has the wrong shape for a choice question.
        """
        return self._translate(presented, to_label=False)

    def to_presented(self, response: object) -> object:
        """
        Translate a response (with ids) into a presented response (with
        labels), to show a stored response again.

        Raises:
            ResponseError: an id is not in its scope, or the response has
                the wrong shape for a choice question.
        """
        return self._translate(response, to_label=True)

    def _translate(self, response: object, *, to_label: bool) -> object:
        if response is None:
            return None
        question = self._question
        scope = self._scope
        if isinstance(question, MultipleChoiceQuestion) and scope is not None:
            return scope.lookup(response, to_label=to_label)
        if isinstance(question, MultipleSelectionQuestion) and scope is not None:
            if not isinstance(response, (list, tuple, set, frozenset)):
                raise ResponseError(
                    f"A multiple selection response must be a list of ids, found "
                    f"{type(response).__name__}"
                )
            return [scope.lookup(item, to_label=to_label) for item in response]
        if isinstance(question, TrueFalseQuestion) and scope is not None:
            if not isinstance(response, Mapping):
                raise ResponseError(
                    f"A true/false response must be a mapping of statement ids, found "
                    f"{type(response).__name__}"
                )
            return {
                scope.lookup(key, to_label=to_label): value
                for key, value in response.items()
            }
        if isinstance(question, FillInQuestion):
            if not isinstance(response, Mapping):
                raise ResponseError(
                    f"A fill-in response must be a mapping of blank ids, found "
                    f"{type(response).__name__}"
                )
            return {
                key: (
                    self._blanks[key].lookup(value, to_label=to_label)
                    if key in self._blanks and value is not None
                    else value
                )
                for key, value in response.items()
            }
        return response


class ExamPresentation:
    """
    The presentation of each question of a resolved exam, in the order of
    the exam (docs/public-form.md, "Presented form"). Get one with
    `Exam.presentation`.
    """

    def __init__(self, presentations: Mapping[str, Presentation]) -> None:
        """`presentations` maps each question id to its presentation, in exam order."""
        self._presentations = dict(presentations)

    def public(self) -> list[dict[str, Any]]:
        """The presented form of each question, in the order of the exam."""
        return [presentation.public() for presentation in self._presentations.values()]

    def to_responses(self, presented: Mapping[str, object]) -> dict[str, object]:
        """
        Translate the presented responses of an attempt (question id to
        response) into the responses that grading takes.

        Raises:
            ResponseError: a key names no question of the exam, or a
                response does not translate.
        """
        return self._translate(presented, to_label=False)

    def to_presented_responses(
        self, responses: Mapping[str, object]
    ) -> dict[str, object]:
        """
        Translate the responses of an attempt (question id to response)
        into presented responses.

        Raises:
            ResponseError: a key names no question of the exam, or a
                response does not translate.
        """
        return self._translate(responses, to_label=True)

    def _translate(
        self, responses: Mapping[str, object], *, to_label: bool
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, response in responses.items():
            presentation = self._presentations.get(key)
            if presentation is None:
                raise ResponseError(f"response for unknown question {key!r}")
            result[key] = presentation._translate(response, to_label=to_label)
        return result
