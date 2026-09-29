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
  same `sign? value` grammar (`mdq._parser.parse_numeric_value`); a
  malformed one, or a fraction with a zero denominator, is the new
  `malformed-numeric-answer` model error.
- A fill-in choice blank now gets the choice lint rules of multiple choice:
  `blank-choice-feedback`, `blank-choice-comment`, `missing-choice-id` and
  `visually-identical-choices`.
- The models reject a numeric question's/blank's `unit` that does not match
  `^[^\s()\[\]]+$`, like the schema and the parser. The Moodle XML importer
  removes whitespace and `()[]` from a Moodle unit to make it valid.

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
