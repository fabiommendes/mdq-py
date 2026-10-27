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
cat question.mdq.md | mdq validate -  # read from stdin (mdq by default)
mdq validate - --format yaml < question.yaml
mdq show exam.mdq.md                  # render the parsed document
mdq show exam.mdq.md --no-answer-key  # preview it as a student sees it
mdq export question.mdq.md --format gift
mdq import question.gift -o question.mdq.md
```

```
$ mdq validate capital.mdq.md
OK    capital.mdq.md
```

Every command uses the same exit codes:

| Code | Meaning |
| ---- | ------- |
| 0 | Success. Warnings do not change it. |
| 1 | The document is invalid, or a converter cannot convert it. |
| 2 | Usage or I/O: a bad option, a missing, unreadable or non-UTF-8 input, an unknown file suffix or format, an output path that cannot be written. |

Errors go to stderr as `error: <message>`, never as a traceback. `validate`
prints every diagnostic; `show` and `export` print only the first error of an
invalid document. Use `-` as the file to read from stdin (`import` also needs
`--format`). `show` and `export` infer the input format from the suffix
(`.mdq.md`, `.md`, `.mdq`, `.yaml`, `.yml` or `.json`) and exit 2 for any other.

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


## Converters

`mdq.convert.import_question(source, format=...)` and
`mdq.convert.export_question(question, format=...)` convert one question
from and to `"gift"`, `"moodle-xml"` and `"aiken"`. There is no warning
channel: a conversion that would lose or change something raises
`ValueError("cannot convert from/to <format>: ...")`. Exceptions to that rule
are listed below as "dropped".

### Text formats on import

| Source text format | MDQ text |
| ------------------ | -------- |
| GIFT `[html]`; Moodle `html` | Copied as is. CommonMark carries raw HTML. |
| GIFT `[plain]`; Moodle `plain_text` | Markdown punctuation is escaped (`*`, `_`, `[`, `<`, `&`, a leading `#` or `1.`, ...). Line breaks inside a paragraph become hard breaks. |
| GIFT `[markdown]`, GIFT without prefix (auto-format); Moodle `markdown`, `moodle_auto_format` | Copied as is. |
| Moodle `wiki_like`, an unknown value, or no `format` | Read as `html`, as Moodle does. |

Moodle XML reads the `format` of `<questiontext>`, `<answer>`, `<feedback>`,
`<generalfeedback>` and `<graderinfo>` one by one. GIFT has one format per
question. The text of a short-answer pattern or of a numeric answer is not
Markdown and is never converted.

Known caveats of copying HTML: an HTML block (`<p>`, `<div>`) runs until a blank
line, so text on the next lines is raw HTML too, and entities such as `&nbsp;`
render. Auto-format line breaks (`<br>` in Moodle) are lost: MDQ joins the
lines. Export always writes `markdown`.

### Answer key of short-answer and numeric questions

MDQ grading is binary, so GIFT credits and Moodle fractions map as follows.
This applies to GIFT, Moodle XML and the SHORTANSWER and NUMERICAL blanks of a
Moodle cloze.

| Source answer | Short answer | Numeric |
| ------------- | ------------ | ------- |
| 100% | `accept`, with its feedback | The `answer` (and tolerance). It is the 100% answer, not the first one. |
| 0% | `reject`, with its feedback | Dropped (its feedback is lost). |
| Moodle `*` at 0% with feedback | `incorrectFeedback` | `incorrectFeedback` |
| Moodle `*` at 100% (short answer) | `accept: /.*/` | `ValueError` |
| Between 0% and 100%, or negative | `ValueError` | `ValueError` |
| A `*` inside the text of a short answer | `ValueError` (Moodle reads it as a wildcard) | n/a |
| A second 100% numeric answer | n/a | Dropped if the value and tolerance are the same, `ValueError` otherwise. |

A GIFT or cloze short answer reads a lone `*` as a literal. The export writes
`accept` as 100% and `reject` as 0% (`=%0%text#feedback` in GIFT,
`fraction="0"` in Moodle XML), so the key survives a round trip. A `reject`
regex or a literal with a `*` inside raises. `incorrectFeedback` is exported
only to Moodle XML (the `*` answer at 0%). Choice questions and choice blanks
keep their partial credit.

### General feedback: `meta.generalFeedback`

MDQ has no field for the feedback shown after any response (GIFT `####`,
Moodle `<generalfeedback>`). The converters keep it in
`meta.generalFeedback`, a string. This key is defined by the converters, not by
the MDQ specification.

* Import: non-empty general feedback of any question type becomes
  `meta.generalFeedback`. The exception is the GIFT essay, where `####` stays
  the `answerKey`. A Moodle essay keeps `<graderinfo>` as `answerKey` and
  `<generalfeedback>` as `meta.generalFeedback`. A true/false group joins the
  distinct general feedback of its statements with a blank line.
* Export: `meta.generalFeedback` is written as `####` (GIFT) or
  `<generalfeedback>` (Moodle XML). A true/false group writes it on its first
  statement. It must be a string with a visible character, or the export raises
  `ValueError`. A GIFT essay with both an `answerKey` and
  `meta.generalFeedback` raises, because GIFT has one `####`. A GIFT essay with
  only `meta.generalFeedback` is written as `####` and comes back as its
  `answerKey`.

### Epilogue and missing-word spaces (GIFT)

GIFT has no epilogue. The export joins it to the stem, after a blank line, as
Moodle XML does (text after `}` would make GIFT read a missing-word question).
A fill-in question is the exception: its text after the blank is the tail, and
an epilogue is appended to the tail after a line break. A tail with a blank
line raises, since a blank line ends a GIFT block. The spaces around the
`{...}` of a missing-word question are kept in both directions.


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
