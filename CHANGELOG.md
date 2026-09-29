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

### Changed

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

### Fixed

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
