"""
Maintain the `.lint.json` snapshots next to the examples under
`examples/valid/` (see "Expected lint files" in
`dev/specs/to-do/loading-module.md`).

A `.lint.json` records the non-error diagnostics `mdq.load` is expected
to produce for one document. `foo.mdq.md` and `foo.yaml` -- when both
exist -- share `foo.lint.json`, since they are meant to parse into the
same document. This script never hand-edits an existing file: it only
creates one that is missing, or reports a mismatch for a human to
review and, if it agrees, rewrite explicitly with `--overwrite`.

Reachable only by running this module directly (``python -m
mdq.scripts.lint_snapshot``) -- like `mdq.scripts.schema_bundle`, this is
a maintenance step for this repo, not something a user of the `mdq` CLI
ever needs.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from mdq import load

__all__ = ["diagnostics_for", "main"]

#: Every surface syntax a document may use. Longest-first, so `.mdq.md`
#: is stripped whole rather than leaving a stray `.md`.
_SOURCE_SUFFIXES = (".mdq.md", ".mdq", ".yaml", ".yml", ".json")


def diagnostics_for(path: Path) -> list[dict[str, Any]]:
    """
    The non-error diagnostics `mdq.load(path)` produces, in the
    `.lint.json` shape: `{"code", "severity", "path"}`, no message and
    no line.
    """
    loaded = load(path)
    return [
        {"code": d.code, "severity": d.severity, "path": list(d.path)}
        for d in loaded.diagnostics
        if d.severity != "error"
    ]


def main(argv: list[str] | None = None) -> int:
    """
    Entry point for `python -m mdq.scripts.lint_snapshot`.

    Args:
        argv: Command-line arguments, defaulting to `sys.argv[1:]`.

    Returns:
        0 if every existing `.lint.json` matches reality (as a
        multiset) after applying `--overwrite`; a non-zero exit status
        otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="python -m mdq.scripts.lint_snapshot",
        description=(
            "Create missing .lint.json snapshots and report stale ones. "
            "Never rewrites an existing file except one named by "
            "--overwrite."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("examples/valid"),
        help="corpus root to scan (default: examples/valid)",
    )
    parser.add_argument(
        "--overwrite",
        type=Path,
        nargs="*",
        default=None,
        metavar="PATH",
        help=(
            "rewrite exactly these .lint.json paths to match reality. "
            "There is no flag that rewrites every file."
        ),
    )
    args = parser.parse_args(argv)

    overwrite = {path.resolve() for path in (args.overwrite or [])}

    exit_code = 0
    for lint_json, paths in sorted(_group_documents(args.root).items()):
        exit_code |= _sync_one(lint_json, paths[0], overwrite)

    return exit_code


#
# Implementation
#


def _stem(path: Path) -> str:
    name = path.name
    for suffix in _SOURCE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _group_documents(root: Path) -> dict[Path, list[Path]]:
    """
    Every document under `root`, grouped by the `.lint.json` path it
    would share with its same-stem siblings (e.g. `foo.mdq.md` and
    `foo.yaml`).
    """
    groups: dict[Path, list[Path]] = {}
    if not root.exists():
        return groups
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not path.name.endswith(_SOURCE_SUFFIXES):
            continue
        lint_json = path.with_name(f"{_stem(path)}.lint.json")
        groups.setdefault(lint_json, []).append(path)
    return groups


def _multiset(entries: list[dict[str, Any]]) -> Counter:
    return Counter(json.dumps(entry, sort_keys=True) for entry in entries)


def _write(lint_json: Path, diagnostics: list[dict[str, Any]]) -> None:
    lint_json.write_text(json.dumps(diagnostics, indent=2) + "\n", encoding="utf-8")


def _sync_one(lint_json: Path, document: Path, overwrite: set[Path]) -> int:
    diagnostics = diagnostics_for(document)

    if not lint_json.exists():
        if diagnostics:
            _write(lint_json, diagnostics)
        return 0

    existing = json.loads(lint_json.read_text(encoding="utf-8"))
    if _multiset(existing) == _multiset(diagnostics):
        return 0

    if lint_json.resolve() in overwrite:
        _write(lint_json, diagnostics)
        return 0

    print(f"stale: {lint_json}")
    print(f"  file:   {existing}")
    print(f"  actual: {diagnostics}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
