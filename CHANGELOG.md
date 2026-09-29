# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This package uses [Semantic Versioning](https://semver.org/). Before 1.0.0, a
minor version can have incompatible changes.

Each release states the version of the
[MDQ specification](https://github.com/fabiommendes/mdq-spec/blob/main/CHANGELOG.md)
that it implements.

## [Unreleased]

Implements the unreleased MDQ specification.

### Added

- Parser for every question type and for exams, from MDQ Markdown, YAML and
  JSON, into Pydantic models.
- `mdq.load()` and `mdq.parse()`, with diagnostics for errors, warnings and
  lint problems.
- Derived ids for questions and choices (`with_ids()`).
- `render()` and `str()` write questions and exams as MDQ Markdown.
- Scoring of student responses.
- Import and export of GIFT, Aiken and Moodle XML
  (`mdq.convert.import_question`/`export_question`, `mdq.convert.FORMATS`).
- `mdq` CLI with the `new`, `validate`, `show`, `import` and `export`
  commands.
- `mdq[hypothesis]` extra with Hypothesis strategies for generating
  questions and exams (`mdq.hypothesis`).
- Lint code `non-ascii-whitespace` for Unicode spaces outside code. `load`
  reports it also when the document fails to parse.

### Changed

- `.md` is an MDQ extension, like `.mdq.md` and `.mdq`. `load`, `parse` and
  the CLI read a `Path` ending in `.md` as MDQ Markdown, and `FileLoader`
  resolves an include to `<id>.md` if there is no `<id>.mdq.md`.
- The parser accepts only spaces and tabs where the grammar has `ws`, and
  splits lines only at `\r\n`, `\r` and `\n`. Other Unicode spaces are
  text: `[short-answer]:` followed by U+00A0 and `Brasília` gives the
  answer U+00A0 `Brasília`.
- A leading byte order mark is removed before parsing.
- A `unit` excludes `UNICODE_SPACE` instead of Python's `\s`, and an
  `include-all` query tag excludes it too. A query with another Unicode
  space between tokens does not follow the query language.
- A short-answer pattern is a regex if it starts with `/` after stripping
  spaces, tabs and line endings. Before, every Unicode space was stripped.
- A numeric value, a fraction's numerator/denominator, and both tolerances
  no longer accept a leading zero (`007`, `00.5`, `01/2`): the parser now
  follows numeric.md's `INTEGER`/`DECIMAL` grammar instead of a bare
  `[0-9]+`.
- A numeric question's/blank's `unit` regex now matches any character
  except whitespace and the brackets `(`, `)`, `[`, `]`
  (`mdq._parser._question.UNIT_RE`), not Python's Unicode-aware `\w`,
  admitting units like `µm`, `°C`, and `km/h`.
- A numeric question's/blank's string `answer` is now checked against the
  same `sign? value` grammar (`mdq._parser.parse_numeric_answer`); a
  malformed one, or a fraction with a zero denominator, is the new
  `malformed-numeric-answer` model error.
- A fill-in choice blank now gets the choice lint rules of multiple choice:
  `blank-choice-feedback`, `blank-choice-comment`, `missing-choice-id` and
  `visually-identical-choices`.
- The models reject a numeric question's/blank's `unit` that does not match
  `^[^\s()\[\]]+$`, like the schema and the parser. The Moodle XML importer
  removes whitespace and `()[]` from a Moodle unit to make it valid.
- A numeric body's value follows numeric.md's new "Answer representation":
  a fraction is a string (`"1/3"`), an integer is an `int` inside the
  32-bit signed range and a string outside it, and a decimal is a `float`
  only if the float gives back the written digits (`"2.50"` and
  `"3.14159265358979323846"` stay strings). Before, every value became a
  float. `domain` and `decimalPlaces` are unchanged.
- `NumericQuestion.answer` and `NumericBlank.answer` keep an `int` as an
  `int` (it was widened to a `float`) and reject a `bool`
  (`NumericAnswer`).
- Numeric scoring is exact: it compares `Fraction`s, and reads a float as
  the decimal of its shortest repr. A `"1/3"` answer no longer matches the
  float `0.3333333333333333` without a tolerance, and `0.3 +- 0.1`
  accepts `0.4`.
- The GIFT and Moodle XML importers give an answer the same
  representation as the parser (`mdq._parser.parse_numeric_answer`), so
  `42` imports as an `int`.
- `mdq.hypothesis.documents.numeric_questions` draws a valid `answer`
  from the new `numeric_answers` strategy.
- The Moodle XML and GIFT exporters accept only the grades Moodle lists
  (`question_bank::fraction_options_full()`: 0, +-1, +-9/10, 5/6, 4/5,
  3/4, 7/10, 2/3, 3/5, 1/2, 2/5, 1/3, 3/10, 1/4, 1/5, 1/6, 1/7, 1/8, 1/9,
  1/10, 1/20) and write them as Moodle does (`83.33333`). Any other
  choice score, or a multiple-selection question with more than 10
  correct or incorrect choices, raises `ValueError`: Moodle would reject
  the question or move the score. Embedded answers (Cloze) keep any
  grade, since Moodle does not check them.
- The Moodle XML and GIFT importers read a listed grade as its exact
  value (`83.33333` is 5/6). Other grades are kept as written.
- The Moodle XML and GIFT exporters raise `ValueError` for a numeric
  answer that has no exact float (`"1/3"`, a long decimal, a large
  integer) and no tolerance. With a tolerance, they write the nearest
  float.
- The Moodle XML exporter raises `ValueError` for a fill-in blank with no
  answer worth 100% (for example a choice blank whose best choice scores
  0.5). Moodle rejects such an embedded answer (`fractionsnomax`).
- The Moodle XML exporter raises `ValueError` for a fill-in choice blank
  with fewer than 2 choices (Moodle's `notenoughanswers`).
- `domain-mismatch`: an integer answer also agrees with `domain:
  fraction`, and a float that is not whole agrees with `decimal` only
  (before, also with `fraction`).
- `ignored-decimal-places` fires when the declared or inferred domain is
  not `decimal`. Before, it needed a declared `integer`/`fraction`.
- `load` reports every built-in pydantic error type (`missing`,
  `extra_forbidden`, `value_error`, ...) as `schema-error`, with the same
  path and message. A named MDQ error keeps its code.
- An exam `start` that is not ISO 8601 is the `malformed-start` error, and
  a `duration` that is not a positive duration is `invalid-duration`
  (before, `value_error`).
- A true-false `marker` that is not a single letter is the
  `malformed-true-false-marker` error (before, `string_too_short`,
  `string_too_long`, or no error for a non-letter such as `1`).
- The parser no longer converts a non-string `id` (question or exam),
  `include` or `include-all` with `str()`: `id: 2024` and `include: yes`
  are `schema-error`s. A null exam `id` is absent (it was `"None"`).

### Fixed

- The path of an error inside an exam's `questions` no longer holds the
  entry kind (`questions.0.question.essay.stem` is now
  `questions.0.stem`; `questions.0.include.include` is
  `questions.0.include`).
- A line with U+0085, U+2028 or another character that `str.splitlines()`
  treats as a line break no longer shifts the line numbers of the rest of
  the document, which could drop choices or fail the parse.
- `[ short-answer ]:` and `[short-answer / accept]:` are no longer read as
  tags. base.md does not allow whitespace between the brackets.
- `answer-outside-domain` and `relative-tolerance-around-zero` now judge a
  string `answer` (`"3/2"`, `"0"`) by its value. Before, they only checked a
  number.
- A line inside a fenced or indented code block no longer acts as exam
  structure. Before, a `# comment` line in a code block made a question
  load as an exam, and `===` or `---` lines in a code block split or broke
  an exam.
- A trailing line of an indented code block that holds only Unicode
  whitespace (such as NBSP) is kept. CommonMark only treats spaces and tabs
  as blank.
- The `mdq.hypothesis` indented code block strategy no longer generates a
  line of only spaces or tabs, which is a blank line and not code.
- `accept-reject-overlap` compares ordering lines after normalization.
- `redundant-regex-anchor` respects the `f`/`b` flags, ignores an escaped
  `\$`, and also checks delimited `accept`/`reject` patterns.
- The parser derives a numeric `domain` from the value and the absolute
  tolerance (`0 +- 0.01` is decimal). `domain-mismatch` uses the same rule,
  and accepts `fraction` or `decimal` for a float answer that is not whole,
  since a float cannot show how it was written.
- Rendering a numeric answer or tolerance never writes an exponent
  (`1e-05` is `0.00001`), and a relative tolerance has no float noise
  (`0.07` is `7.0%`, not `7.000000000000001%`). An `int` answer renders
  without `.0`.
- `[numeric]: 2.0` and `[numeric]: 4/2` no longer get a false
  `domain-mismatch`.
