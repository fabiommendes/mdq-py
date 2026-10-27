"""
Locations of the example documents the test suite runs against.

Every path below resolves relative to the repository root -- one level
up from `mdq-py/` -- so it means nothing outside this checkout. Import
this from the test suite only, never from library or CLI code.

Files that sit in the corpus but are not documents, each with its own
runner (`collect_files` leaves them out):

* `<name>.lint.json` -- the diagnostics of the document of the same name
  (`test_lint_corpus.py`, `test_invalid_sources.py`).
* `valid/exam/<name>.resolved.yaml` -- an exam with includes after
  `resolve` and `with_ids`: the `questions` ids in order,
  `diagnostics`, and optionally `fields` (an inherited field -> its value
  per position, e.g. `locale`) and `lint` (the diagnostics of
  `Exam.lint()` on the resolved exam, with paths under `questions[i]`)
  (`test_exam_resolution_corpus.py`).
* `valid/**/<name>.ids.yaml` -- the ids of the document of the same name
  after `with_ids()`, shared by its `.mdq.md` and `.yaml` siblings:
  `id` (question), `choices` (ids in order), `blanks` (fill-in: blank id
  -> choice ids) or, for an exam, `questions` (ids in order). A key
  absent from the file is not checked (`test_ids_corpus.py`).

Files outside `valid/` and `invalid/` that are test vectors, not
documents (`EXAMPLES_ROOT`):

* `normalize.yaml` -- `load(input).document.to_dict()` of inputs the
  models normalize (`test_normalize_corpus.py`).
* `matching/query.yaml` -- the `includeAll` query language
  (`test_query_corpus.py`).
"""

import json
from pathlib import Path
from typing import Any

PY_PROJECT_ROOT = Path(__file__).resolve().parent.parent
MDQ_ROOT = PY_PROJECT_ROOT.parent
EXAMPLES_ROOT = MDQ_ROOT / "examples"
INVALID_DIR = EXAMPLES_ROOT / "invalid"
VALID_DIR = EXAMPLES_ROOT / "valid"

#: Invalid examples JSON Schema cannot reject on its own -- a rule like
#: "unique by field" -- so the schema accepts them and only `load`
#: (the pydantic models) rejects them. Every other example under
#: `examples/invalid/` must fail both (see dev/specs/to-do/unique-ids.md).
INVALID_MODEL_ONLY_DIR = INVALID_DIR / "model-only"
#: Invalid examples that are not documents at all: YAML or JSON that does
#: not parse, repeats a key, or is not a mapping at the top level. Only
#: `load` sees them (`yaml-syntax-error`, `json-syntax-error`,
#: `invalid-document`); the schema tests leave them out.
INVALID_SYNTAX_DIR = INVALID_DIR / "syntax"
DOCUMENT_SUFFIXES = (".yaml", ".yml", ".json")
VALID_EXAMS_DIR = VALID_DIR / "exam"

#: Surface-syntax questions. A question and an exam share this extension
#: and are told apart by their content, not by their name.
SOURCE_SUFFIX = ".mdq.md"

VALID_SOURCES: list[Path]
VALID_PARSED: list[Path]
INVALID_PARSED: list[Path]


def collect_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in DOCUMENT_SUFFIXES
        and not path.name.endswith(".lint.json")
        and not path.name.endswith(".resolved.yaml")
        and not path.name.endswith(".ids.yaml")
    )


def relative_id(path: Path) -> str:
    return ".".join(path.relative_to(EXAMPLES_ROOT).parts[1:])


def collect_sources(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name.endswith(SOURCE_SUFFIX)
    )


#: The .yaml a source document is expected to parse into.
def parsed_sibling(source: Path) -> Path:
    return source.with_name(source.name[: -len(SOURCE_SUFFIX)] + ".yaml")


INVALID_MODEL_ONLY_PARSED = collect_files(INVALID_MODEL_ONLY_DIR)
INVALID_SYNTAX = collect_files(INVALID_SYNTAX_DIR)
INVALID_PARSED = [
    path
    for path in collect_files(INVALID_DIR)
    if not path.is_relative_to(INVALID_MODEL_ONLY_DIR)
    and not path.is_relative_to(INVALID_SYNTAX_DIR)
]
VALID_PARSED = collect_files(VALID_DIR)
VALID_SOURCES = collect_sources(VALID_DIR)

#: Surface-syntax documents `load` must reject. Each has a `.lint.json`
#: listing every diagnostic `load` reports for it (errors included); a
#: `.yaml` sibling, when present, must report the same ones.
INVALID_SOURCES = collect_sources(INVALID_DIR)
VALID_QUESTIONS = [
    source for source in VALID_SOURCES if not source.is_relative_to(VALID_EXAMS_DIR)
]
VALID_EXAMS = [
    source for source in VALID_SOURCES if source.is_relative_to(VALID_EXAMS_DIR)
]


#: The bundled schema shipped with the package. `scripts/schema_bundle.py`
#: at the repository root builds it from `schema/*.yaml`.
SCHEMA_BUNDLE_PATH = PY_PROJECT_ROOT / "mdq" / "mdq.schema.json"


def load_schema_bundle() -> dict[str, Any]:
    """Load the bundled schema shipped with the package."""
    return json.loads(SCHEMA_BUNDLE_PATH.read_text(encoding="utf-8"))


def bundled_types(bundle: dict[str, Any]) -> set[str]:
    """
    The document types the bundle validates on their own: `exam` and each
    question type. Each one is a `$defs` key of the bundle.
    """
    return {
        entry["$ref"].rsplit("/", 1)[-1].removesuffix(".yaml")
        for entry in bundle["oneOf"]
    }


#: Codes only the Markdown parser produces, since they need the source
#: layout. A `.yaml`/`.json` sibling of a source example shares its
#: `.lint.json` but can never report them.
PARSER_ONLY_CODES = frozenset(
    {
        "redundant-id",
        "separator-before-include",
        "malformed-separator",
        "non-ascii-whitespace",
        "non-ascii-whitespace-in-prose",
        "multi-line-pattern",
    }
)
