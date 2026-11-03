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
mdq export question.mdq.md --format gift --strict   # a warning is an error
mdq import question.gift -o question.mdq.md
mdq import question.xml --html markdown             # needs mdq[html]
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
  from and to other formats. `load_question()` and `dump_question()` do the
  same and return the diagnostics instead of raising (see "Converters").


## Converters

`mdq.convert.import_question(source, format=...)` and
`mdq.convert.export_question(question, format=...)` convert one question
from and to `"gift"`, `"moodle-xml"` and `"aiken"`.

### Diagnostics

Formats differ, so a conversion does its best and reports what it changed.
Every problem is a `mdq.Diagnostic` with a converter code (see the table
below), a `severity`, a `message` and the `path` of the field in the MDQ
question (of the source question on export, of the produced one on import):

* **error**: the output would be meaningless or rejected by the target, such
  as a short answer with no literal answer left. The first error stops the
  conversion: there is no result.
* **warning**: the target cannot hold something, and the converter did its
  best: it rounds a grade, drops a regex, drops a feedback.
* **info**: metadata that changes nothing for the student or for the grading
  (`comment`, `author`, `uuid`, `locale`, `meta` keys other than
  `generalFeedback`) is dropped.

`load_question` and `dump_question` never raise for a problem in the
document. They return a `Converted`, with the `value` (`None` if there is an
error) and the `diagnostics` in the order found:

```python
from mdq.convert import dump_question, load_question

converted = dump_question(question, format="gift")
for d in converted.diagnostics:
    print(d.severity, d.code, d.path, d.message)
text = converted.validate(raise_on="warning")  # ConversionError on a warning
```

`import_question` and `export_question` return the result, and raise
`mdq.errors.ConversionError` (a `ValueError`, with the `diagnostics`) on an
error. Each warning is emitted with `warnings.warn` as a
`mdq.errors.ConversionWarning` (its `diagnostic` has the details), so it is
never silent. Pass `strict=True` to raise on a warning too. An unknown
`format` raises `ValueError`.

`html="markdown"` (in `load_question` and `import_question`) converts every
HTML text of the source to Markdown with the optional
[markdownify](https://pypi.org/project/markdownify/) package, instead of one
HTML block (see below). Install it with the `html` extra: `mdq[html]`.
Without it, the call raises `ImportError`.

On the command line, `mdq import` and `mdq export` print each diagnostic to
stderr as `<severity>: <message> [<code>]`, followed by ` at <path>` when it
has a path. A conversion with only warnings writes the output and exits 0.
`--strict` counts a warning as an error, and an error writes nothing and
exits 1. `mdq import --html markdown` selects the Markdown conversion; if
`markdownify` is missing, the command exits 2.

### Converter diagnostics

| Code | Severity | Formats | Direction | Best-effort behavior |
| ---- | -------- | ------- | --------- | -------------------- |
| `score-rounded` | warning | GIFT, Moodle XML | export | A score that is not a grade Moodle accepts becomes the nearest grade (a tie goes to the one closer to 0). Covers choices, choice blanks and the shares of a multiple-selection question. |
| `inexact-answer` | warning | GIFT, Moodle XML | export | A numeric answer with no exact float (`1/3`) and no tolerance is written as the nearest float. |
| `manual-grading-dropped` | warning | GIFT, Moodle XML | export | A short answer (or blank) that leaves a response to the instructor is exported with its literal answers: a response that matches none gets 0. |
| `regex-dropped` | warning | GIFT, Moodle XML | export | A regex pattern of `accept` or `reject` is dropped with its feedback. |
| `no-accept` | error | GIFT, Moodle XML | export | A short answer with no literal `accept` answer: no response could be correct. |
| `general-feedback-dropped` | warning | GIFT, Moodle XML | export | `meta.generalFeedback` that is not a visible string is dropped. In a GIFT essay with an `answerKey`, `meta.generalFeedback` is dropped (GIFT has one `####`). |
| `unsupported-type` | error | all | export, import | The format has no such question type (GIFT: multiple selection, ordering; Moodle XML: ordering and any `type` MDQ cannot read, such as matching; Aiken: all but multiple choice). |
| `too-many-choices` | error | Aiken | export | More than 26 choices. |
| `multiple-blanks` | error | GIFT | export | A fill-in question with a number of blanks other than 1: GIFT has one answer body. |
| `blank-marker-mismatch` | error | GIFT, Moodle XML | export | The blanks and the markers of the stem disagree. A guard: a valid model never does it. |
| `no-full-credit` | error | Moodle XML, GIFT, cloze | export, import | Export: a cloze blank with no answer worth 100% (Moodle rejects it). Import: a numeric answer with no positive credit. |
| `cloze-text-changed` | warning | Moodle XML | export | In a cloze choice or feedback, `~` and a backslash before `~`, `}`, `#` or at the end are written as the character references `&#126;` and `&#92;`. |
| `invalid-xml-character` | error | Moodle XML | export | The text has a character that XML 1.0 cannot hold, such as a form feed. Dropping it would change an answer or a stem, so the export stops. |
| `grading-changed` | warning | Moodle XML | export, import | Moodle grades a multiple-selection question by its own scheme (1/n for each correct choice ticked, -1/m for a wrong one, never below 0). The mapping `correct` = positive fraction is kept. One per question. |
| `diacritics-not-folded` | warning | GIFT, Moodle XML | export | An inexact literal with a diacritic: Moodle compares diacritics, MDQ folds them by default. |
| `line-breaks-dropped` | warning | Aiken | export | A line break inside a choice is written as a space. |
| `indentation-lost` | warning | GIFT | export | A text has a line, other than the first, that starts with a space or tab. Moodle trims every line. |
| `field-dropped` | warning | all | export, import | A field with a value that changes what the student sees or how the response is graded has no place in the target (`id`, `tags`, `weight`, `shuffle`, `grading`, `domain`, `decimalPlaces`, `preAccept`, and so on, by format), or an import drops a Moodle element (`<correctfeedback>`, `<hint>`) or a field of a later statement of a true or false group. One per field. |
| `metadata-dropped` | info | all | export | `comment`, `author`, `uuid`, `locale` or a `meta` key other than `generalFeedback` is dropped. |
| `partial-credit-dropped` | warning | all | export, import | Import: a short-answer entry with partial or negative credit is a `reject` answer; a numeric one is dropped, and without a 100% answer the best positive one is the answer. Aiken export: the first choice with the highest score is the only correct one. |
| `answer-dropped` | warning | GIFT, Moodle XML | import, export | Import: a 0% numeric answer, a second 100% one or a `*` at 100% is dropped. Export: a short-answer literal of a cloze blank that has no cloze form (`~`, a backslash before `~`, `}`, `#` or at the end) is dropped. |
| `wildcard-to-regex` | warning | GIFT, Moodle XML | import | A `*` inside a short answer is Moodle's wildcard: it becomes an MDQ regex that matches the whole response (`*` is any text, other characters are literal, case is ignored). |
| `feedback-dropped` | warning | GIFT, Moodle XML | import | The feedback of the 100% numeric answer: a numeric question has no field for it. |
| `multiple-questions` | error | GIFT, Moodle XML | import | The source has several questions that are not a true or false group. |
| `no-question` | error | GIFT, Moodle XML | import | The source has no question. |
| `missing-word-joined` | warning | GIFT | import | An essay with text after `{}`: the stem is the stem, a space and the text. |
| `blank-in-html-block` | error | GIFT, Moodle XML | import | A `[^id]` marker inside an HTML block other than `<p>`. Use `html="markdown"`. |
| `syntax-error` | error | all | import | The source has a syntax error. `line` is 1-based. |
| `not-a-number` | error | GIFT, Moodle XML | import | A numeric answer that is not a number. |
| `invalid-question` | error | all | import | The converter built a question the models reject. |
| `unsupported-cloze-kind` | error | Moodle XML | import | A cloze kind MDQ has no blank for (`MULTIRESPONSE`, ...). |
| `case-sensitivity-dropped` | warning | Moodle XML | import | A case sensitive short answer (`SHORTANSWER_C`, `<usecase>1`): MDQ literals ignore case. |
| `blank-weight-dropped` | warning | Moodle XML | import | The weight of a cloze blank other than 1. |
| `unit-changed` | warning | Moodle XML | import | A numerical unit with characters MDQ cannot hold (they are removed), a multiplier other than 1, or more than one unit (the first with multiplier 1 is kept). |
| `embedded-file-dropped` | warning | Moodle XML | import | A `<file>` or an `@@PLUGINFILE@@` reference: the text is kept as it is. One per question. |
| `gift-blank-line` | warning | GIFT | import | A blank line before the `{` or inside the answer body: Moodle splits the question there. The importer keeps reading it. |

### Text formats on import

| Source text format | MDQ text |
| ------------------ | -------- |
| GIFT `[html]`; Moodle `html` | A stem without blanks, a general feedback and a grader info are wrapped in one `<div>...</div>` HTML block (see below). Choices, inline feedback and text with blanks are copied as is. With `html="markdown"`, every HTML text becomes Markdown. |
| GIFT `[plain]`; Moodle `plain_text` | Markdown punctuation is escaped (`*`, `_`, `[`, `<`, `&`, a leading `#` or `1.`, ...). Line breaks inside a paragraph become hard breaks. |
| GIFT `[markdown]`, GIFT without prefix (auto-format); Moodle `markdown`, `moodle_auto_format` | Copied as is. |
| Moodle `wiki_like`, an unknown value, or no `format` | Read as `html`, as Moodle does. |

Moodle XML reads the `format` of `<questiontext>`, `<answer>`, `<feedback>`,
`<generalfeedback>` and `<graderinfo>` one by one. GIFT has one format per
question. The text of a short-answer pattern or of a numeric answer is not
Markdown and is never converted.

An HTML stem without blanks, a general feedback and a grader info become one
CommonMark HTML block, so Markdown never reads any part of them (`*`, indented
code, ...). An HTML block ends at a blank line, so the importer removes them:
outside `<pre>` and `<textarea>`, each run of whitespace with a blank line
becomes one line break (HTML collapses whitespace anyway); inside them, a blank
line is joined to the next line as `&#10;`. Entities such as `&nbsp;` render, as
in HTML.

Choice text and inline feedback (of a choice, a pattern or
`incorrectFeedback`) are copied as is: they are inline text. Cloze and
missing-word `html` text holds `[^blank]` markers, which an HTML block would
turn into literal text, so each top-level `<p>...</p>` becomes a Markdown
paragraph (attributes such as `class`, `dir` and `style` are dropped; a line
break inside it becomes a space). Inline tags stay as inline HTML. Any other
block-level tag (`<div>`, `<table>`, `<ul>`, `<pre>`, ...) that opens an HTML
block with a marker is rejected with an error. Known caveat: Markdown-active
characters in the text of such a paragraph are not escaped.

With `html="markdown"`, the HTML text is converted with `markdownify`
instead. A cloze or missing-word text is converted as a whole, with each blank
replaced by a placeholder that is put back as `[^blankN]` afterwards, so no
HTML element is split. The option does not apply to short-answer or numeric
answer texts.

Known caveat: auto-format line breaks (`<br>` in Moodle) are lost: MDQ joins the
lines. Export always writes `markdown`.

### Answer key of short-answer and numeric questions

MDQ grading is binary, so GIFT credits and Moodle fractions map as follows.
This applies to GIFT, Moodle XML and the SHORTANSWER and NUMERICAL blanks of a
Moodle cloze.

| Source answer | Short answer | Numeric |
| ------------- | ------------ | ------- |
| 100% | `accept`, with its feedback | The `answer` (and tolerance). It is the 100% answer, not the first one. Its feedback is dropped (`feedback-dropped`). |
| 0% | `reject`, with its feedback | Dropped, with its feedback (`answer-dropped`). |
| `*` at 0% with feedback | `incorrectFeedback` | `incorrectFeedback` |
| `*` at 100% | `accept: /.*/` | Dropped (`answer-dropped`) |
| Between 0% and 100%, or negative | `reject`, worth 0 (`partial-credit-dropped`) | Dropped (`partial-credit-dropped`). With no 100% answer, the one with the highest positive credit is the answer. |
| A `*` inside the text of a short answer | A regex that matches the whole response (`wildcard-to-regex`) | n/a |
| A second 100% numeric answer | n/a | Dropped (`answer-dropped`): the first one is the answer. |

GIFT, like Moodle XML and Moodle itself, reads a lone `*` short answer as
"any other answer". The export writes `accept` as 100% and `reject` as 0%
(`=%0%text#feedback` in GIFT, `fraction="0"` in Moodle XML), so the key
survives a round trip. `incorrectFeedback`, of a short answer and of a
short-answer or numeric blank, is the `*` answer at 0%
(`=%0%*#feedback` in GIFT). A literal `*` answer is written `\*` (`\\*` in a GIFT
file, where the backslash is escaped). A `reject` regex is dropped
(`regex-dropped`). Choice questions and choice blanks keep their partial
credit.

### General feedback: `meta.generalFeedback`

MDQ has no field for the feedback shown after any response (GIFT `####`,
Moodle `<generalfeedback>`). The converters keep it in
`meta.generalFeedback`, a string. This key is defined by the converters, not by
the MDQ specification.

* Import: non-empty general feedback of any question type becomes
  `meta.generalFeedback`. The exception is the GIFT essay, where `####` stays
  the `answerKey`. A Moodle essay keeps `<graderinfo>` as `answerKey` and
  `<generalfeedback>` as `meta.generalFeedback`. A true or false group joins the
  distinct general feedback of its statements with a blank line.
* Export: `meta.generalFeedback` is written as `####` (GIFT) or
  `<generalfeedback>` (Moodle XML). A true or false group writes it on its first
  statement. A value that is not a string with a visible character is dropped
  (`general-feedback-dropped`). A GIFT essay with both an `answerKey` and
  `meta.generalFeedback` writes the `answerKey` (GIFT has one `####`) and drops
  the other. A GIFT essay with only `meta.generalFeedback` is written as `####`
  and comes back as its `answerKey`.

### GIFT text escapes

Moodle splits a GIFT file at every blank line and trims every line. The export
never writes a blank line inside a question: each blank line of a text is
written as the escape `\n` at the end of the line before it (`a`, a blank
line and `b` are the two lines `a\n` and `b`), which Moodle reads back as a line
feed. A line other than the first that starts with a space or a tab loses
that indentation in Moodle (`indentation-lost`).

The import reads the escapes of Moodle: `\\`, `\:`, `\#`, `\=`, `\{`, `\}` and
`\~` lose the backslash, and `\n` is a line feed. Any other backslash stays
(`\*` in a stem is a Markdown escape). Blank lines before the `{` and inside
the answer body are read, with a warning (`gift-blank-line`).

### Epilogue and missing-word spaces (GIFT)

GIFT has no epilogue. The export joins it to the stem, after a blank line, as
Moodle XML does (text after `}` would make GIFT read a missing-word question).
A fill-in question is the exception: its text after the blank is the tail, and
an epilogue is appended to the tail after a line break. The spaces around the
`{...}` of a missing-word question are kept in both directions. A true or false
answer (`{T}`, `{F}`) with a tail is a fill-in question with one choice blank,
`True` and `False`.

### True or false groups

GIFT and Moodle XML have one statement per question, so a true or false
question is exported as one question per statement, with the stem of the
group in each. Moodle XML gives each statement the `defaultgrade` of the
`weight` divided by the number of statements, and the import sums them. The
import keeps the title, id, tags and shuffle of the first statement
(`field-dropped` for a later one that differs).


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
