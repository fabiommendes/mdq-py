# mdq-py

[![CI](https://github.com/fabiommendes/mdq-spec/actions/workflows/ci.yml/badge.svg)](https://github.com/fabiommendes/mdq-spec/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> [!WARNING]
> This is a work in progress. The MDQ specification is not stable yet, and the
> API and the CLI may change.

Python reference implementation of [MDQ](https://github.com/fabiommendes/mdq-spec),
a file format to write questions and exams in plain Markdown:

```md
What is the capital of Brazil?

* [ ] Rio de Janeiro
  > It was the capital until 1960.
* [*] Brasília
* [ ] São Paulo
```

`mdq-py` provides:

* A parser from MDQ Markdown (and from YAML/JSON) to Pydantic models.
* A linter that reports problems the schema cannot express.
* Scoring of student responses.
* Converters to and from GIFT, Aiken and Moodle XML.
* The `mdq` command line tool.

The syntax of each question type is in the
[specification](https://github.com/fabiommendes/mdq-spec/tree/main/docs).


## Installation

Requires Python 3.13 or later. The package is not on PyPI yet. Install it from
the repository:

```bash
# CLI only
uv tool install "git+https://github.com/fabiommendes/mdq-py"

# As a library
uv add "git+https://github.com/fabiommendes/mdq-py"
```


## Command line

```bash
mdq new multiple-choice               # scaffold multiple-choice.mdq.md
mdq new numeric --complete            # scaffold with every feature of the type
mdq validate question.mdq.md          # print errors and warnings
mdq validate question.mdq.md --level strict   # also print info diagnostics
mdq show exam.mdq.md                  # render the parsed document
mdq show exam.mdq.md --no-answer-key  # preview it as a student sees it
mdq export question.mdq.md --format gift
mdq import question.gift -o question.mdq.md
```

`mdq validate` exits with a non-zero code if the document has errors:

```
$ mdq validate capital.mdq.md
OK    capital.mdq.md
```

`import` and `export` support `aiken`, `gift` and `moodle-xml`. The format is
inferred from the file extension if `--format` is not given. Run `mdq --help`
or `mdq <command> --help` for all options.


## Library

`mdq.parse()` returns a validated model, or raises `InvalidDocument`:

```python
from pathlib import Path

import mdq

question = mdq.parse("""
What is the capital of Brazil?

* [ ] Rio de Janeiro
* [*] Brasília
""")

print(type(question).__name__)  # MultipleChoiceQuestion
print(question.to_dict())
```

A `str` is read as MDQ source. Pass a `Path` to read a file, or a mapping to
load an already parsed document. The `format` argument selects `"mdq"`,
`"yaml"` or `"json"` explicitly.

`mdq.load()` never raises for a problem in the document. It returns the
document together with every diagnostic, which is useful for editors and
linters:

```python
loaded = mdq.load(Path("exam.mdq.md"))
for diagnostic in loaded.diagnostics:
    print(diagnostic.severity, diagnostic.code, diagnostic.message)

exam = loaded.validate(raise_on="warning")
```

Other useful parts of the API:

* `ids="fill"` in `parse()`/`load()`, or `document.with_ids()`, derives the
  missing ids of questions and choices.
* `question.score_response(response)` scores a student response.
* `question.render()` serializes a model back to MDQ Markdown.
* `Exam.resolve()` replaces the `include` blocks of an exam with the questions
  they refer to.
* `mdq.convert.import_question()` and `mdq.convert.export_question()` convert
  from and to other formats.


## Development

The test suite reads the specification, the schema and the shared examples from
the parent [mdq-spec](https://github.com/fabiommendes/mdq-spec) repository, where
this package lives in the `mdq-py/` directory. Clone that repository to run the
tests; a standalone clone of `mdq-py` cannot run them.

```bash
git clone https://github.com/fabiommendes/mdq-spec
cd mdq-spec/mdq-py
uv sync
uv run pytest          # tests
uv run mypy mdq        # type check
uv run ruff check      # lint
```

This is the reference implementation: new features are specified in
`mdq-spec`, implemented here, and then ported to
[mdq-js](https://github.com/fabiommendes/mdq-js). See [AGENTS.md](AGENTS.md) for
the coding conventions.

See the [changelog](CHANGELOG.md) and the
[contributing guide](https://github.com/fabiommendes/mdq-spec/blob/main/CONTRIBUTING.md).


## License

[MIT](LICENSE)
