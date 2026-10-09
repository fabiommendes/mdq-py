# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This package uses [Semantic Versioning](https://semver.org/). Before 1.0.0, a
minor version can have incompatible changes.

Each release states the version of the
[MDQ specification](https://github.com/fabiommendes/mdq-spec/blob/main/CHANGELOG.md)
that it implements.

## [Unreleased]

Implements the unreleased MDQ specification.

### Changed

- The exam include block key `include-all` is renamed to `includeAll` (`IncludeAll` model alias, `IncludeAllDict`, parser, linter paths). `include-all` is now an unknown field (`unknown-include-field`).
- One severity per lint code. `non-ascii-whitespace` is always `warning`; a Unicode space in prose reports the new `non-ascii-whitespace-in-prose` (`info`). A blank `preamble`, `epilogue` or `stem` reports the new `blank-content-field` (`error`); `blank-text-field` is always `warning`.
- Empty free-text fields (`comment`, `preamble`, `epilogue`, `answerKey`, `instructions`, feedback) are now schema errors, and an empty frontmatter comment string is not stored.
- A blank exam `instructions` reports `blank-content-field` (`error`).
- Fixed: the models did not enforce several schema `minItems`/`minLength` limits. `load` now reports `schema-error` for an empty fill-in `blanks`, a choice blank with fewer than two choices, an empty `accept`/`reject`/`preAccept`/`preReject` list, an empty ordering `accept`/`reject`, and an empty `id`, `title`, `author`, exam `course`, `highlight`, include `include` or ordering alternative `feedback`/`comment`.
- Refreshed the bundled schema (description text only).

### Fixed

- A `schema-error` on a field of a bare-string shorthand (an empty pattern line, a choice text) is reported at the string, not below it: `["accept", 0]` instead of `["accept", 0, "pattern"]`.
- `normalize()` no longer trims Unicode spaces (such as U+00A0) from the ends of `stem` and `preamble`: the grammar reads them as text, and the parser keeps them.

### Added

- `mdq validate -` reads the document from stdin, as MDQ Markdown by default.
  The new `--format mdq|yaml|json` option sets the format of stdin, or
  overrides the one inferred from a file extension. Diagnostics show `<stdin>`
  as the file name.
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
  commands. `mdq show` draws a question as a card, with a type badge, radio
  buttons, checkboxes, input fields and metadata chips. `--theme` selects
  `dark`, `light` or `plain`.
- `mdq[hypothesis]` extra with Hypothesis strategies for generating
  questions and exams (`mdq.hypothesis`).
- Lint code `non-ascii-whitespace` for Unicode spaces outside code. `load`
  reports it also when the document fails to parse.

### Changed

- `mdq.hypothesis` strategies generate unique `tags`, since repeated tags are
  now rejected.
- Regex flags follow docs/references/patterns.md: `s`, `v` and `d` are now
  accepted and ignored, and `x` is an error like any other unknown flag.
- Short-answer questions and blanks lose `oneOf` and `regex` (the
  `one_of` and `regex` fields of `ShortAnswerQuestion` and
  `ShortAnswerBlank`). `accept` is the only answer list, and the Markdown
  parser always emits it: `[short-answer]: X` gives `accept: ["X"]`, and
  the pattern keeps its delimiters. A document with `oneOf` or `regex` is a
  `schema-error`; in a Markdown frontmatter they are unknown keys.
- `[short-answer]` is the accept block, and `[short-answer/accept]` is an
  alias of it. Each block takes one pattern on the tag line or a list on
  the lines right after it. Both spellings in one document, a tag with a
  pattern followed by a list, and a `[short-answer/reject]` with no pattern
  followed by a detached list are parse errors. `[short-answer]: X` with
  `accept` in the frontmatter is `conflicting-accept`.
- A list after a blank line is not part of the block. It stays in the
  `epilogue` and the parser reports the new lint code
  `detached-answer-list`. The same holds for fill-in blanks.
- Feedback and comment lines that interleave in a short-answer pattern item
  are a parse error, and so is a `[short-answer/reject]` block with no
  pattern, in questions and in fill-in blanks.
- `ShortAnswerBlank` gets `open_ended` (`openEnded`). A bare
  `[^id/short-answer]:` gives `openEnded: true` and no `accept`.
- Render writes a lone `accept` pattern without feedback or comment, and
  no `reject`, as `[short-answer]: X`. Any other `accept` is a
  `[short-answer]:` list, and `reject` is a `[short-answer/reject]:` list.
  It never writes `[short-answer/accept]`.
- GIFT and Moodle XML export a literal `accept` (backticks removed) and
  raise `ValueError` for a regex, the `*` wildcard or a missing `accept`.
  Import writes `accept`, and encloses in backticks an answer that starts
  with `/` or a backtick, or is `*`.
- `mdq show` prints the `accept`/`reject` patterns of a short-answer blank.
- Lint code `shadowed-answers` is removed. `short-answer-not-gradable`
  depends only on `accept` and `openEnded`.
- `openEnded` is removed from `ShortAnswerQuestion` and `ShortAnswerBlank`.
  Every question has a read-only `automation` property (`automatic`,
  `semi-automatic` or `manual`; `mdq.types.Automation`), derived from the
  fields and never serialized. `ShortAnswerQuestion` gains `unmatched`
  (`mdq.types.Unmatched`, with `effective_unmatched` for the default) and
  `incorrect_feedback`; `FillInQuestion` gains `unmatched`, and
  `ShortAnswerBlank` the methods `effective_unmatched(unmatched)` and
  `automation(unmatched)`. The parser, render and `mdq show` follow: the
  frontmatter keys are `unmatched` and `incorrectFeedback`, and `mdq show`
  prints the automation.
- `score_response` of a short-answer question or fill-in blank applies the
  three grading rules: accept, reject, then `unmatched`. A response that is
  not settled raises `NotAutoGradable` (it is pending) instead of scoring 0;
  `incorrect_feedback` is the feedback of an incorrect response that no
  pattern gave feedback to.
- The `*` wildcard is removed: `*` is a plain literal. The lint codes
  `accept-wildcard`, `unreachable-reject` and `short-answer-not-gradable` are
  removed; `no-correct-answer` warns when `unmatched` is `incorrect` and
  there is no `accept` pattern. `blank-text-field` also flags a value made
  of format characters such as U+200B.
- GIFT and Moodle XML export raise `ValueError` for a short-answer question
  that is not `automatic`. Moodle XML writes `incorrect_feedback` as the
  `*` answer with fraction 0 and reads it back; a `*` answer with fraction
  100 imports as `/.*/`. A lone `*` is no longer wrapped in backticks on
  import.
- The inexact comparison of a plain literal follows the six steps of
  patterns.md. A response with an invisible code point (U+200B, U+00AD, a
  control), a typographic quote or dash, or a Latin letter such as `ø` now
  matches the plain spelling. Case folding comes from a table of Unicode
  18.0.0 (`mdq/inexact-tables.json`) and not from `str.casefold()`. U+001C
  to U+001F are no longer whitespace.
- An exact literal normalizes the pattern and the response to NFC, so a
  response typed in NFD matches, and trims only the `UNICODE_SPACE` code
  points from their ends.
- `redundant-regex-anchor`, `ignored-regex-flag`, `accept-wildcard` and
  `unreachable-reject` are also reported on `preAccept`/`preReject`, at the
  paths `preAccept[i]`/`preReject[i]` (`blanks[n].preAccept[i]` in a
  fill-in blank).
- `.md` is an MDQ extension, like `.mdq.md` and `.mdq`. `load`, `parse` and
  the CLI read a `Path` ending in `.md` as MDQ Markdown, and `FileLoader`
  resolves an include to `<id>.md` if there is no `<id>.mdq.md`.
- The parser accepts only spaces and tabs where the grammar has `ws`, and
  splits lines only at `\r\n`, `\r` and `\n`. Other Unicode spaces are
  text: `[short-answer]:` followed by U+00A0 and `Brasília` gives the
  answer U+00A0 `Brasília`.
- A leading byte order mark is removed before parsing.
- A `unit` excludes `UNICODE_SPACE` instead of Python's `\s`, and an
  `includeAll` query tag excludes it too. A query with another Unicode
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
  `include` or `includeAll` with `str()`: `id: 2024` and `include: yes`
  are `schema-error`s. A null exam `id` is absent (it was `"None"`).
- A repeated key in a YAML mapping is `yaml-syntax-error`, in Markdown
  frontmatter (question, exam, exam block) and in a YAML document. A
  repeated key in a JSON object is `json-syntax-error`. Before, the last
  value won.
- A YAML document is loaded like the frontmatter, so `duration: 1:30` is
  the string `"1:30"`, not the base-60 integer 90.

- Lint code `unexpanded-stem-ellipsis` is removed with the spec feature. A
  stem of `...` is an ordinary stem.

- A `null` value in any optional field, in Markdown frontmatter, YAML or
  JSON, nested objects included, is dropped before validation: `weight:
  null` is 1, exam `duration: null` is no duration. Only `meta` keeps its
  nulls.
- `grading` and `shuffle` of the choice-based question types are
  `"inherit"` by default instead of `None`. `effective_grading()` and
  `effective_shuffle()` resolve them outside an exam. `Exam` gets
  `shuffle`, `grading_for()`, `shuffle_for()` and `resolve_question()`, and
  `score_responses()` now applies the exam's `grading` to the questions
  that inherit it.
- Lint code `provisional-true-false-marker` is renamed
  `unlisted-true-false-marker`.

- Lint code `setext-heading`: an exam's instructions, or the preamble,
  stem or epilogue of one of its questions, holds a setext heading, which
  is usually a `---` block fence with no blank line before it.

- `tests/test_grading_examples.py` reads `examples/grading/*.yaml`, which no
  test read before.

- `malformed-locale` follows the RFC 5646 grammar in full: 4-letter and
  5-8 letter primary language subtags and the grandfathered tags are
  accepted. `brasil` no longer fails.

- `code-input-without-highlight` reports `path=("highlight",)` and
  `undeclared-id-after-include-all` reports `("questions", i, "id")`.

- `BooleanChoice.correct` and `Statement.correct` are required, as the
  schema now says; the parser writes `correct: false` for a blank `[ ]`
  in a multiple-selection question instead of omitting it.

- Parse errors for `* [] text` (empty brackets), an ordering `ul` item with
  more than one line, and prose between the `[ordering]` block and a
  section. Repeated `normalizations` entries are rejected.
- From Markdown, a bad exam `start`/`duration` reports `malformed-start`/
  `invalid-duration` with its path, as YAML does. An H1 in the exam
  instructions is `forbidden-block-element`; a `---` block with broken YAML
  is `yaml-syntax-error`.
- `domain-mismatch` reports only a declared domain narrower than the values
  need; `domain: decimal` with an integer answer is fine.

- Warning `unsafe-thematic-break` for a `---` thematic break in a preamble,
  stem, epilogue or exam instructions. An exam `---` block with broken YAML
  is `yaml-syntax-error` instead of silent prose.
- `accept-reject-overlap` points at the `accept` entry a `reject` entry
  repeats (`accept[i]`) instead of the document root.
- `scripts/lint_snapshot.py` writes `[]` for a clean document instead of
  skipping it, and no longer reads an existing `.lint.json` as a document.
- A numeric response the question's domain cannot represent is a
  `ResponseError`, not a wrong answer: a non-integer value on an `integer`
  question (responses.md, "Numeric"). `numeric_matches` takes `domain`;
  `NumericQuestion` and the numeric blank expose `effective_domain`.
- `NumericResponse` includes `str`: a string response spells an exact decimal
  or fraction, in numeric questions and fill-in blanks alike.

### Fixed

- `weight` is a number by schema: `weight: "2"` is a `schema-error` instead of
  loading as a string.
- Repeated `tags` are a `schema-error`, as the schema's `uniqueItems` says.
- A YAML or JSON document whose top level is not a mapping is
  `invalid-document`, not a `schema-error` about the `type` discriminator.
- A second `## [answer-key]` section is a `parse-error`; before, it was read
  as part of the first answer key.
- A bare `#` line in the frontmatter is a comment string with no text:
  `comment` is `""`, and `blank-text-field` warns about it. Before, the field
  was dropped.
- A `schema-error` on a plain union field such as the exam `grading` has a
  clean path (`["grading"]`), and one diagnostic per path instead of one per
  union member. Before, pydantic's member labels leaked into the path.
- The feedback (`>`) and comment (`!`) blocks of an ordering section are
  read from their own lines, as the grammar says. Before, with no blank line
  between them, CommonMark folded the `!` line into the blockquote, so
  `> fb` + `! cm` loaded as the feedback "fb ! cm" with no comment, and an
  interleaved `>`, `!`, `>` loaded without error.
- An ordering `accept`/`reject` alternative needs at least one line, as the
  schema says.
- A numeric body with two absolute or two relative tolerances is a
  `parse-error`; before, the last one won.
- A negative `tolerance.absolute` or `tolerance.relative` is a `schema-error`,
  as the schema's `minimum: 0` says.
- With `domain: decimal` in the frontmatter, `decimalPlaces` is inferred
  from the body as numeric.md says; before, only an inferred decimal domain
  carried it.
- A fill-in blank marker is `[^` + `SLUG` + `]`, as the stem grammar says:
  `[^ a]`, `[^-x]` and `[^size/numeric]` are text. Before, `[^ a]` was an
  undefined blank and `[^size/numeric]` referenced `size`.
- A `[^id]` inside a code span of the stem is `misplaced-blank`. Before, it
  counted as the blank's reference and the document loaded.
- The choice list of a `[^id]:` definition must start on the next line; a
  blank line in between is a `parse-error` instead of being skipped.
- A pattern that opens with a backtick must be a complete span, as the
  schema now says; `` `math.isnan` (x) `` is a `schema-error`.
- A bare `*` list marker in a pattern list is an empty pattern line, reported
  as a `parse-error`. Before, it was read as a continuation of the previous
  item ("Brasília *").
- A choice or blank `id` must be a `SLUG`, as the schema says; `id: "são
  paulo"` is a `schema-error` instead of loading.
- An ATX heading in a preamble, stem, epilogue or answer key keeps its `#`
  markers in the parsed field. Before, `## Contexto` became the paragraph
  `Contexto`, and a forbidden `## [Rubrica]` heading went unnoticed.
- Only an H1 that starts the document, or follows the frontmatter, makes it
  an exam. An H1 after other content is a question's forbidden element,
  not an exam without questions.
- Render keeps `preAccept` and `preReject` of a short-answer question: it
  writes them in the frontmatter. Before, `str(question)` dropped them.
- `[numeric]` and `[^id/...]` tags accept spaces before the colon
  (`[numeric] : 42`), like `[short-answer] :` already did (base.md,
  "Bracketed tags").
- An ordering question with `indentation: fixed` compares indentation
  levels (ordering.md, "Grading"): `grades_indentation()` is true unless
  `dedent` is in effect. Before, only `strict` compared them, and a
  distractor differing from a key line only by its level matched it.
- `decimalPlaces` rounds the response and the answer of a `decimal`
  numeric question or blank before the tolerance test (numeric.md,
  "Decimal places"): half away from zero, in decimal arithmetic. New
  `effective_decimal_places` on `NumericQuestion` and `NumericBlank`,
  `infer_decimal_places`, and a `decimal_places` keyword on
  `numeric_matches`. The parser infers `decimalPlaces` from the absolute
  tolerance too (`0 +- 0.01` gives 2); before, only from the value.
- `Exam.score_responses(responses)` scores one attempt (exam.md, "Exam
  score"): it returns a frozen `models.ExamScore` with the exam `score`
  (None while a response is pending), a `provisional` score over the
  settled questions, every question's `QuestionScore`, the `pending` and
  `skipped` question ids, the `total_weight` and the `penalty` applied.
- The YAML loader follows the YAML 1.2 Core schema (base.md,
  "Frontmatter"): `yes`, `no`, `on`, `off`, timestamps and `1:30` are plain
  strings, `010` is the decimal 10, `0o10` is 8, and there is no merge key.
  Before, PyYAML's YAML 1.1 rules applied, so `include: yes` was a boolean
  and `start: 2026-03-10 09:00:00-03:00` a `datetime`. `start` still
  accepts a space between the date and the time.
- Render writes the `id` of a choice as `[choice-id]` after the value.
  Before, `str(question)` dropped explicit choice ids.
- A bracket followed by `(` or `[` at the start of a choice, of the stem or
  of an exam title is a markdown link, not a choice id or a slug (base.md,
  "Slug"). Before, `* [*] [Brasilia](url)` gave the choice the id `Brasilia`
  and the text `(url)`.
- A choice value outside the `value` rule of the question type, inferred
  or forced by `type`, is a `foreign-choice-marker` error with the path of
  the choice (base.md, "Type inference"): `[x]` next to `[*]`, `[ ]` in a
  true/false list, `[?]`, a Unicode space inside the brackets. Before, the
  parser read it as an unmarked choice. Also checked in a fill-in choice
  blank. New error class `errors.ForeignChoiceMarker`; new helper
  `_parser._choices.foreign_choice_index`.
- A `[ ]` choice of a multiple-choice question has no `score`, so the
  grading strategy decides its value (`symmetric` by default). Before, the
  parser wrote `score: 0`, and `symmetric` never penalized a wrong pick
  written in Markdown. `[0%]` is an explicit zero, and render writes it for
  a score of 0; a whole percentage renders without `.0` (`[-25%]`). The
  GIFT, Moodle XML and Aiken exporters write the score the strategy gives
  a choice with none, instead of refusing the question.
- Render keeps `preAccept` and `preReject` of a short answer blank of a
  fill-in question: the frontmatter gets them as maps from the blank id to
  the list (fill-in.md, "Frontmatter"), and the parser reads them back onto
  the blanks. A key that is not a declared blank is an `undefined-blank`
  error at the path of the key; a parse error now carries the `path` of the
  exception that raised it. New error class `errors.UndefinedBlank`.
- Malformed YAML in a Markdown frontmatter is a `yaml-syntax-error`
  diagnostic. Before, `load` raised PyYAML's exception.
- A null `tags` in an exam frontmatter is absent, as in a question, and a
  `tags` that is neither a list nor a string is a `schema-error`. Before,
  both raised a `TypeError`.
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
