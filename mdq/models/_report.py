"""
The runner report (docs/runner-report.md, `schema/runner-report.yaml`): the
JSON document a runner returns for the test sources of a code question.

The models are strict as the schema is: a field the schema does not define, a
value of another JSON type and a `version` this reader does not know are
errors, since grading a report in silence would hide a runner that is out of
step with MDQ. Grading turns them into `ReportError` (`mdq.errors`).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

__all__ = [
    "ReportCase",
    "ReportHashes",
    "ReportOutput",
    "ReportRunner",
    "RunnerReport",
]

#: A SHA-256 digest: 64 lowercase hexadecimal digits.
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
#: A non-empty string.
Name = Annotated[str, Field(min_length=1)]
#: A number that is not negative. Not a `bool`, as in JSON.
Measure = (
    Annotated[int, Field(strict=True, ge=0)]
    | Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
)


class _ReportModel(BaseModel):
    """
    What the objects of the report share: JSON names in camel case, no field
    outside the schema and no coercion of a JSON type into another.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", strict=True
    )


class ReportOutput(_ReportModel):
    """The captured text of a stream of a case, and whether the runner cut it."""

    text: str
    #: When omitted, the text is whole.
    truncated: bool | None = None


class ReportCase(_ReportModel):
    """
    One test case and the verdict of the runner for it. A case is binary:
    only the verdict `pass` passes.
    """

    #: The 0-based index of the test source in `tests`.
    source: Annotated[int, Field(ge=0)]
    #: The line of the source where the case is defined, from 1.
    line: Annotated[int, Field(ge=1)]
    verdict: Literal["pass", "fail", "error", "timeout", "resource-limit", "skipped"]
    id: Name | None = None
    message: str | None = None
    expected: str | None = None
    actual: str | None = None
    stdout: ReportOutput | None = None
    stderr: ReportOutput | None = None
    duration: Measure | None = None
    memory: Measure | None = None
    #: Data of the runner. MDQ ignores it.
    meta: dict[str, object] | None = None

    @property
    def passed(self) -> bool:
        """Whether the verdict is `pass`."""
        return self.verdict == "pass"


class ReportRunner(_ReportModel):
    """What ran the tests. For the host: grading does not use it."""

    name: Name
    version: Name | None = None
    language: Name | None = None
    toolchain_version: Name | None = None


class ReportHashes(_ReportModel):
    """
    The digests that tie the report to its input. Grading does not check
    them: a host MAY compare them with its own.
    """

    submission: Digest | None = None
    sources: list[Digest] | None = None


class RunnerReport(_ReportModel):
    """
    The runner report.

    `cases` is read only with the status `completed`: with another status it
    is ignored and not checked against the question.
    """

    #: The version of the format. Absent means 1; any other value is an
    #: error, as this reader does not know it.
    version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    status: Literal["completed", "build-error", "runner-error"]
    cases: list[ReportCase]
    #: The message of the compiler or of the syntax error.
    build: str | None = None
    #: A short message for a human. Grading does not use it.
    message: str | None = None
    runner: ReportRunner | None = None
    hashes: ReportHashes | None = None
    #: Data of the runner. MDQ ignores it.
    meta: dict[str, object] | None = None
