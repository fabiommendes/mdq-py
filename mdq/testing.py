"""
Locations of the example documents the test suite runs against.

DEVELOPMENT ONLY: the examples live at the root of the source checkout,
outside the package, so they are not shipped in the built distribution.
Every path below resolves relative to the repo root and therefore means
nothing in an installed `mdq` -- the `collect_*` functions simply return
empty lists there. Import this from the test suite, never from library
or CLI code.
"""

from pathlib import Path

PY_PROJECT_ROOT = Path(__file__).resolve().parent.parent
MDQ_ROOT = PY_PROJECT_ROOT.parent
EXAMPLES_ROOT = MDQ_ROOT / "examples"
INVALID_DIR = EXAMPLES_ROOT / "invalid"
VALID_DIR = EXAMPLES_ROOT / "valid"
DOCUMENT_SUFFIXES = (".yaml", ".yml", ".json")
VALID_EXAMS_DIR = VALID_DIR / "exam"

#: Surface-syntax questions. A question and an exam share this extension
#: and are told apart by their content, not by their name.
SOURCE_SUFFIX = ".mdq.md"

#: Every extension a document's own surface syntax may use -- the
#: `.lint.json` sitting next to it is named after whichever of these its
#: filename ends with (see `lint_json_sibling`).
_DOCUMENT_SUFFIXES_ALL = (".mdq.md", ".mdq", ".yaml", ".yml", ".json")

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


def lint_json_sibling(document: Path) -> Path:
    """
    The `.lint.json` a document's expected lint diagnostics live in.

    `foo.mdq.md` and `foo.yaml` share `foo.lint.json`: both are stripped
    to the same stem before the `.lint.json` suffix is appended. Doesn't
    check that the file exists -- a missing one means zero diagnostics
    are expected, not that there's nothing to check (see
    `dev/specs/to-do/loading-module.md`, "Expected lint files").
    """
    name = document.name
    for suffix in _DOCUMENT_SUFFIXES_ALL:
        if name.endswith(suffix):
            stem = name[: -len(suffix)]
            break
    else:
        stem = document.stem
    return document.with_name(f"{stem}.lint.json")


INVALID_PARSED = collect_files(INVALID_DIR)
VALID_PARSED = collect_files(VALID_DIR)
VALID_SOURCES = collect_sources(VALID_DIR)
VALID_QUESTIONS = [
    source for source in VALID_SOURCES if not source.is_relative_to(VALID_EXAMS_DIR)
]
VALID_EXAMS = [
    source for source in VALID_SOURCES if source.is_relative_to(VALID_EXAMS_DIR)
]
