"""
`Presentation` and `ExamPresentation` (docs/public-form.md, "Presented
form"): the cases of `examples/presentation.yaml`, whose header describes
the format, the round trip of the grading vectors, and the properties of
the presented form.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
import yaml
from _corpus import EXAMPLES_ROOT
from test_public_form import VALID_QUESTIONS
import test_grading_examples as grading

from mdq import errors, load
from mdq.models import (
    BaseQuestion,
    ChoiceBlank,
    Exam,
    ExamPresentation,
    FillInQuestion,
    MultipleChoiceQuestion,
    Presentation,
)
from mdq.models._presentation import digest

CASES: list[dict[str, Any]] = yaml.safe_load(
    (EXAMPLES_ROOT / "presentation.yaml").read_text(encoding="utf-8")
)["cases"]
BY_NAME = {case["name"]: case for case in CASES}


def _question(data: object) -> BaseQuestion[Any]:
    loaded = load(data)
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    assert isinstance(loaded.document, BaseQuestion)
    return loaded.document


def _json(value: object) -> object:
    return json.loads(json.dumps(value))


def _presentation(case: dict[str, Any]) -> Presentation:
    return _question(case["question"]).presentation(
        case["seed"], shuffle=case.get("shuffle")
    )


def _label_by_id(case: dict[str, Any]) -> dict[str, str]:
    """Choice id to label, for the top-level choices of a case."""
    original = [c["id"] for c in case["question"]["choices"]]
    presented = {c["id"] for c in case["presented"]["choices"]}
    labels = {}
    for cid in original:
        for length in (8, 16, 32, 64):
            label = _digest(case["seed"], case["question"].get("id", ""), cid)[:length]
            if label in presented:
                labels[cid] = label
                break
    return labels


def _digest(seed: str, *parts: str) -> str:
    return hashlib.sha256("\0".join((seed, *parts)).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_presented_form_case(case: dict[str, Any]) -> None:
    presentation = _presentation(case)
    assert _json(presentation.public()) == case["presented"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_response_translation_case(case: dict[str, Any]) -> None:
    presentation = _presentation(case)
    for entry in case["responses"]:
        if "error" in entry:
            error = getattr(errors, entry["error"])
            with pytest.raises(error):
                if "presented" in entry:
                    presentation.to_response(entry["presented"])
                else:
                    presentation.to_presented(entry["real"])
            continue
        assert presentation.to_presented(entry["real"]) == entry["presented"]
        assert presentation.to_response(entry["presented"]) == entry["real"]


@pytest.mark.parametrize(
    "case", [c for c in CASES if "stableWith" in c], ids=lambda case: case["name"]
)
def test_labels_are_stable_when_the_question_is_edited(case: dict[str, Any]) -> None:
    other = BY_NAME[case["stableWith"]]
    assert case["seed"] == other["seed"]
    mine, theirs = _label_by_id(case), _label_by_id(other)
    changed = set(case.get("changed", []))
    shared = mine.keys() & theirs.keys()
    assert shared - changed
    assert {cid: mine[cid] for cid in shared - changed} == {
        cid: theirs[cid] for cid in shared - changed
    }
    assert all(mine[cid] != theirs[cid] for cid in shared & changed)
    # The colliding labels are the only ones that change.
    assert changed <= set(mine)


def test_only_colliding_labels_are_longer() -> None:
    lengths = {
        case["name"]: sorted(len(c["id"]) for c in case["presented"]["choices"])
        for case in CASES
        if "choices" in case["presented"]
    }
    collision = "only the colliding labels grow to 16 digits"
    assert lengths[collision] == [8, 8, 16, 16]
    assert lengths[
        "stability: a choice that collides at 8 digits changes only the two labels"
    ] == [
        8,
        8,
        16,
        16,
    ]
    assert lengths["stability: a question without a collision"] == [8, 8, 8]
    assert all(
        set(sizes) == {8}
        for name, sizes in lengths.items()
        if name
        not in (
            collision,
            "stability: a choice that collides at 8 digits changes only the two labels",
        )
    )


@pytest.mark.parametrize("shuffle", [True])
def test_sort_by_label_is_sort_by_digest(shuffle: bool) -> None:
    case = BY_NAME["only the colliding labels grow to 16 digits"]
    labels = [c["id"] for c in case["presented"]["choices"]]
    assert labels == sorted(labels)
    digests = {
        cid: _digest(case["seed"], case["question"]["id"], cid)
        for cid in (c["id"] for c in case["question"]["choices"])
    }
    by_digest = sorted(digests.values())
    assert [
        d for label in labels for d in by_digest if d.startswith(label)
    ] == by_digest


def test_digest_is_sha256_of_the_nul_joined_parts() -> None:
    expected = hashlib.sha256(
        "s3cr3t\0encontro-das-aguas\0correct".encode()
    ).hexdigest()
    assert digest("s3cr3t", "encontro-das-aguas", "correct") == expected
    assert len(expected) == 64


def test_seed_with_nul_is_rejected() -> None:
    question = _question(CASES[0]["question"])
    with pytest.raises(ValueError):
        question.presentation("a\0b")
    numeric = _question(BY_NAME["a question without choices has no scope"]["question"])
    with pytest.raises(ValueError):
        numeric.presentation("a\0b")


def test_choice_without_id_is_not_addressable() -> None:
    question = _question(
        {
            "type": "multiple-choice",
            "stem": "Qual é a capital do Brasil?",
            "choices": [{"text": "Brasília", "score": 1}, {"text": "Rio de Janeiro"}],
        }
    )
    with pytest.raises(errors.MissingIdError):
        question.presentation("seed")


def test_labels_depend_on_the_seed() -> None:
    question = _question(CASES[0]["question"])
    one = question.presentation("one").public()["choices"]
    two = question.presentation("two").public()["choices"]
    assert {c["id"] for c in one}.isdisjoint(c["id"] for c in two)


def test_labels_are_slugs_even_when_the_order_is_the_document_order() -> None:
    question = _question(
        BY_NAME["multiple choice with shuffle false keeps the document order"][
            "question"
        ]
    )
    labels = [c["id"] for c in question.presentation("seed").public()["choices"]]
    assert all(len(label) == 8 and label == label.lower() for label in labels)
    assert [c["text"] for c in question.public()["choices"]] == [
        c["text"] for c in question.presentation("seed").public()["choices"]
    ]


#
# Round trip and the absence of the original ids
#


def _choice_ids(question: BaseQuestion[Any]) -> set[str]:
    if isinstance(question, FillInQuestion):
        return {
            choice.id
            for blank in question.blanks
            if isinstance(blank, ChoiceBlank)
            for choice in blank.choices
            if choice.id is not None
        }
    return {c.id for c in getattr(question, "choices", []) if c.id is not None}


def _presented_choice_ids(presented: dict[str, Any]) -> list[str]:
    choices = list(presented.get("choices", []))
    for blank in presented.get("blanks", []):
        choices.extend(blank.get("choices", []))
    return [choice["id"] for choice in choices]


def _roundtrip_params() -> list[Any]:
    params: list[Any] = []
    for case in grading._cases("multiple-choice"):
        question = grading._question("multiple-choice", case)
        for response, expected in case["examples"].items():
            if expected != "malformed":
                params.append(
                    pytest.param(question, response, id=f"mc/{case['name']}/{response}")
                )
    for case in grading._cases("multiple-selection"):
        question = grading._question("multiple-selection", case)
        for example in case["examples"]:
            if example["score"] != "malformed":
                ticks = (
                    list(example["ticks"])
                    if "ticks" in example
                    else example["response"]
                )
                params.append(
                    pytest.param(question, ticks, id=f"ms/{case['name']}/{ticks}")
                )
    for case in grading._cases("true-false"):
        question = grading._question("true-false", case)
        for example in case["examples"]:
            if example["score"] != "malformed":
                marks = {cid: None for cid in case["choices"]} | example["marks"]
                params.append(
                    pytest.param(question, marks, id=f"tf/{case['name']}/{marks}")
                )
    for case in grading._cases("fill-in"):
        question = grading._binary_question("fill-in", case)
        for example in case["examples"]:
            scores = list((example.get("scores") or {"x": example["score"]}).values())
            if "malformed" not in scores:
                params.append(
                    pytest.param(
                        question,
                        example["response"],
                        id=f"fill-in/{case['name']}/{example['response']}",
                    )
                )
    return params


ROUNDTRIP = _roundtrip_params()


def test_there_are_roundtrip_vectors() -> None:
    assert len(ROUNDTRIP) > 50


@pytest.mark.parametrize(("question", "response"), ROUNDTRIP)
@pytest.mark.parametrize("shuffle", [True, False])
def test_grading_vectors_round_trip(
    question: BaseQuestion[Any], response: object, shuffle: bool
) -> None:
    presentation = question.presentation("ana.souza:prova", shuffle=shuffle)
    presented = presentation.to_presented(response)
    assert presentation.to_response(presented) == response
    # The presented response grades as the real one.
    try:
        expected = question.score_response(response).score
    except errors.NotAutoGradable:
        with pytest.raises(errors.NotAutoGradable):
            question.score_response(presentation.to_response(presented))
    else:
        assert (
            question.score_response(presentation.to_response(presented)).score
            == expected
        )


def _all_questions() -> list[Any]:
    params = [pytest.param(q, id=n) for n, q in VALID_QUESTIONS]
    for case in [*grading._cases("multiple-choice")]:
        params.append(
            pytest.param(
                grading._question("multiple-choice", case), id=f"mc/{case['name']}"
            )
        )
    for case in grading._cases("multiple-selection"):
        params.append(
            pytest.param(
                grading._question("multiple-selection", case), id=f"ms/{case['name']}"
            )
        )
    for case in grading._cases("true-false"):
        params.append(
            pytest.param(grading._question("true-false", case), id=f"tf/{case['name']}")
        )
    for case in grading._cases("fill-in"):
        params.append(
            pytest.param(
                grading._binary_question("fill-in", case), id=f"fill-in/{case['name']}"
            )
        )
    return params


@pytest.mark.parametrize("question", _all_questions())
@pytest.mark.parametrize("shuffle", [True, False])
def test_presented_form_holds_no_original_choice_id(
    question: BaseQuestion[Any], shuffle: bool
) -> None:
    presented = question.presentation("ana.souza:prova", shuffle=shuffle).public()
    original = _choice_ids(question)
    labels = _presented_choice_ids(presented)
    assert not original & set(labels)
    # Same shape as the public form but for the choices of each scope.
    public = question.public()
    assert presented.keys() == public.keys()
    assert {k: v for k, v in presented.items() if k not in ("choices", "blanks")} == {
        k: v for k, v in public.items() if k not in ("choices", "blanks")
    }


@pytest.mark.parametrize("question", _all_questions())
def test_without_shuffle_the_texts_keep_the_document_order(
    question: BaseQuestion[Any],
) -> None:
    presented = question.presentation("seed", shuffle=False).public()
    public = question.public()
    assert [c["text"] for c in presented.get("choices", [])] == [
        c["text"] for c in public.get("choices", [])
    ]


def test_default_shuffle_is_the_effective_shuffle() -> None:
    shuffled = _question({**CASES[0]["question"], "shuffle": True})
    plain = _question({**CASES[0]["question"], "shuffle": False})
    assert isinstance(shuffled, MultipleChoiceQuestion)

    def texts(q: BaseQuestion[Any], **kw: Any) -> list[str]:
        return [c["text"] for c in q.presentation("s3cr3t", **kw).public()["choices"]]

    assert texts(shuffled) == texts(plain, shuffle=True)
    assert texts(plain) == [c["text"] for c in plain.public()["choices"]]


#
# Exam
#


def _exam(shuffle: bool, own: object = "inherit") -> Exam:
    loaded = load(
        {
            "title": "Prova de Geografia",
            "shuffle": shuffle,
            "questions": [
                {
                    **BY_NAME[
                        "multiple choice with shuffle false keeps the document order"
                    ]["question"],
                    "shuffle": own,
                },
                BY_NAME["multiple selection translates a list of ticked ids"][
                    "question"
                ],
                BY_NAME["a question without choices has no scope"]["question"],
            ],
        },
        kind="exam",
    )
    assert isinstance(loaded.document, Exam)
    return loaded.document


def test_exam_presentation_uses_the_exam_shuffle() -> None:
    exam = _exam(True)
    presentation = exam.presentation("s3cr3t")
    assert isinstance(presentation, ExamPresentation)
    forms = presentation.public()
    assert [f["id"] for f in forms] == [
        "encontro-das-aguas",
        "biomas-do-brasil",
        "pico-da-neblina",
    ]
    labels = [c["id"] for c in forms[0]["choices"]]
    assert labels == sorted(labels)
    # The question own `shuffle` wins over the exam.
    plain = _exam(True, own=False).presentation("s3cr3t").public()[0]["choices"]
    assert [c["text"] for c in plain] == [
        c["text"]
        for c in BY_NAME["multiple choice with shuffle false keeps the document order"][
            "presented"
        ]["choices"]
    ]
    unshuffled = _exam(False).presentation("s3cr3t").public()[0]["choices"]
    assert [c["text"] for c in unshuffled] == [c["text"] for c in plain]


def test_exam_responses_round_trip() -> None:
    exam = _exam(True)
    presentation = exam.presentation("s3cr3t")
    responses = {
        "encontro-das-aguas": "correct",
        "biomas-do-brasil": ["cerrado", "caatinga", "pantanal"],
        "pico-da-neblina": 2995,
    }
    presented = presentation.to_presented_responses(responses)
    assert presented["encontro-das-aguas"] != "correct"
    assert presented["pico-da-neblina"] == 2995
    assert presentation.to_responses(presented) == responses
    assert exam.score_responses(presentation.to_responses(presented)).score == 1


def test_exam_translation_rejects_an_unknown_question_and_label() -> None:
    presentation = _exam(True).presentation("s3cr3t")
    with pytest.raises(errors.ResponseError):
        presentation.to_responses({"nope": "x"})
    with pytest.raises(errors.ResponseError):
        presentation.to_responses({"encontro-das-aguas": "correct"})
    assert presentation.to_responses({}) == {}
    assert presentation.to_responses({"encontro-das-aguas": None}) == {
        "encontro-das-aguas": None
    }


def test_exam_presentation_needs_ids() -> None:
    loaded = load(
        {
            "title": "Prova",
            "questions": [{"type": "essay", "stem": "Explique o efeito estufa."}],
        },
        kind="exam",
    )
    assert isinstance(loaded.document, Exam)
    with pytest.raises(errors.MissingIdError):
        loaded.document.presentation("seed")
