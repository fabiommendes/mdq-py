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

- `FillInQuestion.score_blanks(response)`: the score of each blank, keyed by blank id, with `None` for a pending blank. It raises `ResponseError` like `score_response()`, but not `NotAutoGradable`, so a host can show the settled blanks of a pending response. `QuestionScore.blanks` holds the same map for a settled fill-in response (`None` for other question types).
- `public()` on every question class: the question as a student may see it, in the shape of `to_dict()`, without the answer key, feedback, comments, `author` and `meta`. A numeric question and a numeric blank get their effective `domain` and `decimalPlaces`; a short answer question, an ordering question and each short answer blank get their effective `unmatched` (a fill-in question drops its own `unmatched`); an ordering question gets a `pool` of its lines and extra lines, sorted, in place of `lines` and `extra`. A choice without an id raises `MissingIdError`: call `with_ids()` first.
- `correct_responses()` on every question class: the responses that score 1, derived from the answer key. A list of full responses; a fill-in question gives a map from blank id to the responses of that blank.

### Removed

- The lint code `stem-not-a-paragraph`: the stem may hold any block elements.

### Changed

- `normalize()` gives what a render and parse give: it strips the spaces around a choice text, a pattern, and the `feedback` and `comment` of choices, patterns and ordering alternatives; fills `domain` and `decimalPlaces` of numeric questions and numeric blanks, and the `marker` of true/false statements; and puts a numeric `answer` in the form a render and parse keep (`"100"` becomes `100`, `"1.50e3"` stays a string). `mdq.hypothesis` no longer sets these fields itself.
- A `type` in the frontmatter that disagrees with the body (for example `type: numeric` with a `[short-answer]` body) is one `parse-error` that names both types, instead of `schema-error` entries.
- GIFT and Moodle XML export escape every literal `*` of a short-answer pattern as `\*`, which Moodle reads as a literal asterisk. Before, an inner `*` raised, and a lone `` `*` `` was exported as a bare `*`, a Moodle wildcard that accepts any answer. The importers read `\*` back as a literal `*`.
- A string numeric `answer` with a space or tab around it (`" 1"`, `"1 "`) is a `malformed-numeric-answer`, in a numeric question and in a numeric blank (breaking). Before, it was trimmed and accepted, against the schema pattern. The Markdown body `[numeric]: 1` is still trimmed.
- In the fill-in frontmatter, a `null` entry in the `preAccept`, `preReject` or `incorrectFeedback` map means the field is absent for that blank (it was a `parse-error`). A `null` entry in `domain` or `decimalPlaces` no longer blocks the value inferred from the body.
- JSON loading rejects `NaN`, `Infinity` and `-Infinity` with `json-syntax-error` (breaking). Python's `json` accepted them.
- YAML follows the Core schema further (breaking). A scalar mapping key that is not a string becomes its string form, as in `js-yaml` (`1` is `"1"`, `0x1F` is `"31"`, `1e3` is `"1000"`, `null` is `"null"`), in the frontmatter and in YAML documents; a key that repeats after the conversion, or a sequence or mapping key, is a `yaml-syntax-error`. NEL, LS and PS inside a scalar are content, not line breaks. A tag outside the Core schema (`!!timestamp`, `!!binary`, `!!set`, `!!omap`) is a `yaml-syntax-error`, and `!!merge` no longer merges.
- A tag line right after content, or after a pattern or choice item, is a `parse-error` with a "blank line before the tag" message (breaking).
- A setext H1 in exam instructions, a stem or an epilogue is `forbidden-block-element` (breaking).
- Moodle XML and GIFT import split short-answer and numeric answers by credit: 100% is `accept` (or the numeric `answer`), 0% is `reject` with its feedback, and a partial credit or a `*` inside a short answer raises `ValueError` (breaking). The numeric key is the 100% answer, not the first one. A Moodle `*` at 0% with feedback becomes `incorrectFeedback`.
- Moodle XML import reads the text format of each element: a missing `format` is `html`, as in Moodle, and `moodle_auto_format` is accepted (`MoodleTextFormat` lists it instead of `moodle`). GIFT `[plain]` and Moodle `plain_text` are escaped as Markdown; other formats are copied as they are (breaking).
- GIFT export puts the epilogue before the answer body, as Moodle XML does, and raises for a missing-word tail with a blank line (breaking).
- GIFT and Moodle XML keep general feedback in `meta.generalFeedback` on import and write it back on export. GIFT and Moodle XML export write `reject` as a 0% answer and keep accept feedback.
- CLI exit codes follow one policy in every command: 0 success, 1 invalid document or failed conversion, 2 usage or I/O (breaking). `mdq show` exits 2 (was 1) for an unknown suffix or a non-UTF-8 file; `mdq import` and `mdq export` exit 2 (was 1) for an unknown format; `mdq export` exits 2 for an input with an unknown suffix instead of reading it as MDQ, and now reads `.yaml`, `.yml` and `.json` input.
- CLI errors print as `error: <message>` on stderr, without ANSI codes unless stderr is a terminal. `mdq show` and `mdq export` print `error: <code>: <message>` for the first error of an invalid document (no more `error: error`). `mdq import` and `mdq export` read stdin with `-`.
- Question banks (`FileLoader`, `DictLoader`) index only sources that validate as a question; invalid sources and exams are skipped silently. A string `tags` in a mapping source is no longer split at commas (breaking).
- `AnswerPattern` rejects an inexact pattern that starts a CommonMark block other than a paragraph (`# Brasília`, `> x`, `- x`, `1. x`, `<div>`, a lone `*`) with the new error code `block-start-pattern`, which suggests an exact literal or a regex (breaking). `render()` writes a pattern as it is: the exact-literal workaround for a list item is gone, since such a model cannot exist.
- `E` and `Y` are FALSE letters (breaking): `[E]` and `[Y]` now grade as false, with no warning for an existing document. The locale table follows the spec: `pt` and `tr` accept them, `S` leaves six rows, `D` leaves `fa`, and `G` (`ko`), `B` (`bn`, `ja`) and `K` (`gu`) are false friends. A TRUE false friend gets `false-friend-true-false-marker`.
- A Markdown `+- p%` tolerance is stored as the nearest double to the exact `p / 100` (`1000 +- 0.7%` gives `relative: 0.007`, no longer `0.006999999999999999`).
- `Tolerance` with neither field (`tolerance: {}`) is a `schema-error`. A `unit` with no visible character is `blank-text`, in `NumericQuestion` and in a numeric blank.
- The language of an ordering fence is the first word of its info string (`python {.numberLines}` gives `highlight: python`), compared with case. An empty ordering list item is a `parse-error`, also `*` with trailing spaces. `OrderingQuestion.extra` must have an entry when set (`extra: []` is a `schema-error`). An `OrderingLine` text has no leading or trailing space or tab and no line break, and is not empty with `content: text` (`empty-ordering-line`, new error code). A percentage choice marker uses `INTEGER`/`DECIMAL`: `[050%]` is a `foreign-choice-marker`.
- `Exam.lint()` applies `unsplit-tag-list` to the exam `tags`. `EssayQuestion.lint()` applies `unsafe-thematic-break` to `answerKey`. The exam parser reports the new warning `malformed-separator` for a line of `=` that is not a `===` separator. `tests/_corpus.py` lists it as a parser-only code.

- Blank ids: `FillInQuestion.lint()` reports the warning `case-variant-blank-id` for two blank ids that differ only in ASCII case, and the `undefined-blank` message for a stem reference points to a definition with another case. The `EXCEPT` parser already accepted any `TAG` as an id.
- The comment string of a Markdown frontmatter is stripped, and an empty result is not stored: `#` followed by spaces gives no comment, and `# Text  ` stores `Text`. A `comment` of only whitespace in YAML or JSON is still `blank-text`. The Hypothesis strategies generate stripped comments.

- `OrderingQuestion.unmatched` defaults to `"incorrect"` (breaking), so `automation` is `automatic` by default and `frontmatter(skip_defaults=True)` omits `unmatched: incorrect` and writes `unmatched: manual`.
- `highlight` without `content: code` on an `EssayQuestion` is a `schema-error` (breaking). The lint code `ignored-highlight` is removed. An `OrderingQuestion` with `content: code` and no `highlight` gets the info `code-content-without-highlight`.
- `OrderingQuestion.incorrect_feedback` (`incorrectFeedback`): feedback for an incorrect response that no `reject` entry gave feedback to. The Markdown frontmatter accepts it.
- Body tags (breaking): the parser follows the new convention of the specification. `[ordering]` without a colon, or with text after the colon, is a `parse-error`; `OrderingQuestion.render()` writes `[ordering]:`, and so do `mdq new` and the corpus. `[short-answer]:` and `[^id/short-answer]:` with no content (end of the body, or a blank line before the list or the text) are a `parse-error` that says the content starts on the line right after the tag. The lint code `detached-answer-list` is removed. A block with no pattern is `[short-answer]` or `[^id/short-answer]`, without a colon; `render()` writes it that way. `[short-answer/reject]` without a colon, and a list on the line right after a tag without a colon, are a `parse-error`. A tag with content on its line followed by a blank line and a list keeps the list as the epilogue.
- Tags (breaking): the parser reports a known tag in another case as a `parse-error` ("tags are lower case: write `[numeric]:`"), a reserved tag with an unknown suffix as a `parse-error` "unknown tag" (`[short-answer/preAccept]: b` included), and a list on the line right after a content list as a `parse-error`. `find_forbidden_elements` takes a line with a reserved label as a tag.
- The lint code `detached-blank-definition` is renamed `detached-tag` (breaking). Every type reports it for a known tag in the epilogue. The `forbidden-block-element` of a tag paragraph in a Markdown epilogue is now `detached-tag`.
- Exact literal in a Markdown body (breaking): a pattern that opens with a backtick and is not a complete literal is a `parse-error`, no longer a `schema-error`. The YAML, JSON and frontmatter form is unchanged.
- Regex (breaking): the body scanner of `mdq.models._regex` is an allow-list that follows the table of `patterns.md`, and it translates the body to Python `re` in the same pass. Constructs outside the table are an `invalid-regex`, including the ones Python accepts (possessive quantifiers, `\A`, `\Z`, `\a`, `{,n}`, a lone `{`, `}` or `]`, `\-` outside a class, identity escapes) and the ones JavaScript accepts (named groups, backreferences, `\0`, `[]`, `[^]`). `.` is the class `[^\n\r\u2028\u2029]`, so it no longer matches CR, U+2028 and U+2029. The `n` flag and step 3 of the inexact comparison read the `nonspacing` table of `inexact-tables.json`, not `unicodedata.category`.
- A pattern item of the Markdown body that starts a block other than a paragraph (`* > x`, `* # x`, `* - x`, `* 1. x`, `* <div>`) is a `parse-error`. `render()` writes such a pattern as an exact literal in a list item (the tag line form is unchanged). A `01.` line after a feedback line is a list start, so it is a `parse-error`, no longer feedback text.
- New warning `multi-line-pattern`: the parser reports an exact literal or a regex of the Markdown body written on more than one line. `tests/_corpus.py` lists it as a parser-only code.
- Second spec audit (2026-10-26):
  - New lint code `empty-ordering-answer` for an empty `[ordering]` block or `## [accept]` entry. An ordering `ul` item that is not one paragraph is a `parse-error`. A bare `[short-answer]` paragraph with more text, and a `>` or `!` line right after a bare short answer tag, are a `parse-error`.
  - The exam parser and model store the frontmatter comment string as `comment`. `Exam.lint()` reports `missing-title` (info) for an exam with no title.
  - Regex: shorthand classes fold under `i` (`(?-i:...)` is gone), so `/\w/i` matches `ſ` and U+212A. A `\uHHHH` escape in D800-DFFF is an `invalid-regex`.
  - `stem`, `epilogue` and `instructions` keep hard breaks byte for byte; only soft breaks join into one space.
  - The lines of a `[short-answer]:` list are syntax positions, so a non-ASCII whitespace there is reported.
  - A `[^x]` inside an autolink is literal; a definition of that id gets `unreferenced-blank`. A Markdown fill-in with no blank gives `blanks: []` and the `schema-error` at `blanks`. The `blank-text` path of a blank `incorrectFeedback` is `blanks[i].incorrectFeedback`.
  - True/false: `ru V`, `bn M` and `mr B` get `locale-mismatched-true-false-marker`; `sw K` gets `unlisted-true-false-marker`. `H` leaves the `sw` false friends, `否` joins `zh`, `fil` is its own row. A `marker` with whitespace around the letter is `malformed-true-false-marker`.
  - The message of `relative-tolerance-over-one` says that the tolerance stores a fraction.
- Converter classes declare `supports` as a `frozenset` of question types, not a dict of directions (breaking for code that reads the dict).
- Syntax errors of the GIFT, Moodle XML and Aiken importers are `mdq.errors.ParseError` (still a `ValueError`), with the same message.

### Fixed

- The rendered frontmatter keeps non-ASCII characters (`title: Ciclo da água`, not `"Ciclo da \xE1gua"`). A string with a non-ASCII space or line break (NBSP, U+2028) is double-quoted.
- An integer absolute tolerance renders as `6 +- 1`, not `6 +- 1.0`, so the round trip of an integer numeric blank keeps its domain.
- `str()` of a model that is not a question no longer raises `NotImplementedError`.
- `load` reports the `invalid-frontmatter-field` errors together with the `parse-error` of a body that does not parse. Before, they appeared only after the body was fixed.
- GIFT export keeps the `incorrectFeedback` of a numeric question as a `*` answer worth 0%. The GIFT importer reads it back, and also reads Moodle's own form `~#feedback`.
- Moodle XML cloze short-answer blanks escape only `}` and `#`, as the Moodle cloze importer expects: `10:30` and `x=y` are written as they are (they were `10\:30` and `x\=y`, which Moodle stored with the backslash), and `\*` is not doubled. A pattern with a `~`, or with a `\` before `~`, `}`, `#` or at the end, has no cloze form and raises on export. Every cloze kind separates the alternatives with `~` (two correct options were written `=a=b`, one answer for Moodle), and a 0% answer that starts with `=` or `%` gets an explicit `%0%` (a reject `=SOMA(A1)` was read back as an accept). The importer ends an answer only at an unescaped `~`.
- `FileLoader` skips a bank file that is not UTF-8, like a file with an invalid question, instead of raising `UnicodeDecodeError`.
- `score_response` of a multiple-selection question raises `ResponseError` for a string (`"a"`) or a mapping (`{"a": True}`) instead of reading its characters or keys as ticked ids. `score_response` of an ordering question raises it for `""` and `{}` instead of grading them as the empty list.
- A trailing newline no longer passes where the grammar ends the text: `parse_numeric_answer("5\n")` and a numeric body raise `ParseError`, a `uuid` or `locale` that ends in a newline is `malformed-uuid` or `malformed-locale`, and an `id` that ends in a newline gets `unsafe-id`. The checks used `$`, which matches before a final newline; they use `fullmatch` now.
- The Markdown parser no longer drops a setext underline in the `stem` and `epilogue`. `Exam.lint()` reports `setext-heading` for the `stem` and `epilogue` of its questions.
- `Exam.render()` no longer writes `title: null` and a `# Exam` heading for an exam with no title; it writes `#`.
- The `setext-heading` message names the `===` line instead of `---`.
- GIFT missing-word import and export keep the spaces around the blank. GIFT true/false export keeps the epilogue; Moodle cloze export keeps choice feedback.
- `mdq import`, `mdq export`, `mdq show` (stdin) and `mdq new` no longer print a traceback for a non-UTF-8 input or a missing output directory. The unknown-suffix error of the CLI refers to `--format`, not to the library keyword `format=`; `mdq show` help lists the `.yaml`, `.yml` and `.json` suffixes.
- `mdq.hypothesis`: `questions()` draws every question type (it drew only essays) and `questions(type=...)` no longer raises `KeyError` for the other types. `exams()` builds valid exams from `questions()` (it raised `ValidationError`) and `max_questions` defaults to 3. The per-type builders (`multiple_choice_questions()`, ..., `fill_in_questions()`) work, and `ordering_questions()` is new. They generate a simple valid subset: no regex or exact-literal patterns, no `unit`, `tolerance`, `extra`, `accept` or `reject` of ordering, and a fill-in stem of one paragraph. A normalized question round-trips through `render()` and `parse()`.
- `mdq show` draws a blank chip only for a real `[^id]` marker: `[^x]` in a code span, indented or fenced code and `[^x](url)` stay text. Errors on a non-terminal stderr have no escape codes and are not wrapped. `--theme plain` draws code blocks with no color. New helper `mdq._markdown.locate_blank_markers` (private) returns the position of each marker.

- The Moodle XML export of a fill-in question keeps `[^id]` in code spans, code blocks and `[^id](url)` links as text, and replaces only real blank markers.

- A fill-in frontmatter map that is not a mapping (`domain`, `decimalPlaces`, `preAccept`, `preReject`, `incorrectFeedback`) or has a badly typed entry is a `parse-error` whose `path` points at the field (`["domain"]`, `["incorrectFeedback", "river"]`), not `[]`. `ParseError` takes an optional `path`.
- The message of `foreign-choice-marker` shows an empty marker as `[ ]`, not `[]`.
- `Exam.with_ids()` and `Exam.model_copy()` keep `question.exam` pointing at the new exam. `model_copy()` copies the questions, so the original keeps its own.
- `Exam.tags` rejects a repeated entry with `schema-error`, as `BaseQuestion.tags` does.
- `score_response()` raises `ResponseError` for a response of the wrong shape (for example an `int` for a fill-in, ordering, true/false or multiple-selection question), where it raised `TypeError` or `AttributeError`.
- A `stem`, `epilogue` or `answerKey` that starts with a `---` line is no longer read as a frontmatter. `normalize()` kept only the text after the second `---`, an H1 between two thematic breaks was not reported as `forbidden-block-element`, and invalid YAML between them gave a `schema-error`.
- Choice marker values (audit findings F23 and F24): one pipeline, normalize (NFKC, then ASCII lowercase), then validate, then interpret. A character whose NFKC form is a space is `ws` in the marker, so `[U+00A0]` is `[ ]`. A true/false marker must be one code point of `LETTER` after normalization: `[ﬁ]` is a `foreign-choice-marker`, no longer a WARNING letter. New examples `valid/multiple-selection/nbsp-blank-marker`, `invalid/true-false-ligature-marker` and `invalid/true-false-nbsp-marker`.
- Ordering: `accept-outside-answer-key` and `unreachable-alternative` identify a line by text only under `indentation: lenient` and `strict` (by level and text under `fixed`), as the response check does. A `content: text` response with an invalid outline is graded under `fixed` (a wrong answer, `unmatched` applies) and stays a `ResponseError` under `lenient` and `strict`.
- Ordering: an item that only holds a nested list is not a line, it adds a level (`- - Bahia` was read as `[1, "- Bahia"]`, now `[1, "Bahia"]`); an empty `-` followed by a nested list on the next line is skipped too. A nested ordered list on the marker line is a `parse-error`. New model error `invalid-outline-level`: with `content: text`, `lines` and each `accept`/`reject` entry must start at level 0 and go at most one level deeper per line (`extra` is exempt). `OrderingQuestion.score_response` raises `ResponseError` for a text response that is not such an outline. `render()` writes an `extra` line without a parent as `* * text`.
- Ordering: the level of a `ul` line is its item's nesting depth, not the column divided by the GCD (the unit applies to code blocks only). An ordered sub-list is a `parse-error`. Trailing whitespace of each line is removed. `mdq show --no-answer-key` lists the lines at level 0 under `indentation: lenient` and `strict`.

- Ordering: a blank line between the `[ordering]` tag and its content block is a `parse-error`. A section (`## [extra]`, `## [accept]`, `## [reject]`) with no content block is a `parse-error` with its own message ("the ## [extra] section has no content block"). Section headings in every CommonMark `H2` form (indented, trailing spaces, closing sequence, setext) were already read and are now in the corpus. In an exam, the `setext-heading` warning for a setext section heading has the path of the section (`answerKey`, `extra`, `accept`/`reject` with the index) instead of `epilogue`; the `---` error message says "a question's epilogue or section".
- Ordering: new model error `accept-outside-answer-key` (an `accept` entry holds a distractor, a foreign line or more copies of a line than `lines`, once fully normalized). `accept-reject-overlap` now also fires when a `reject` entry equals `lines` (path `("reject", index)`). New warning `unreachable-alternative` for a `reject` entry that needs lines `lines` plus `extra` do not offer (`check_ordering_unreachable_reject`). The Hypothesis strategies of the ordering tests now draw `accept` as a subset of `lines`.
- Ordering: `OrderingQuestion.score_response` raises `ResponseError` for a response with a line outside `lines` plus `extra`, with more copies of a line than that pool offers, or, under `indentation: fixed`, at a level other than the authored one (new method `check_response_lines`; `lenient` and `strict` compare by text only). A response that leaves lines out is still graded. The first matching answer in document order wins.
- Ordering: the parser reads the epilogue between the `[ordering]` block and the first section. Prose after a section is a `parse-error` (breaking: the old order, epilogue after the sections, fails). `OrderingQuestion.render()` writes the sections after the epilogue.
- Ordering `content` and `highlight` (breaking): `content` and `highlight` in the frontmatter of an ordering question are an `invalid-frontmatter-field` error; the parser always takes them from the body. `OrderingQuestion.content` has no default any more, so loading YAML or JSON without it is a `schema-error`, and `highlight` with `content: text` (or empty) is a `schema-error` at `highlight`. A section fence with a language other than the `[ordering]` fence is a `parse-error`; no language inherits it. The `ignored-highlight` check is gone from ordering; `unknown-highlight-language` stays. `OrderingQuestion.render()` already left both fields out of the frontmatter.
- Essay: the field `input` is now `content` (`EssayQuestion.content`, `EssayQuestionDict.content`, the type `EssayContent` replaces `EssayInput`, the `essay_questions(content=...)` strategy). A document with `input:` is a `schema-error`, or an `invalid-frontmatter-field` in a Markdown source. The lint code `code-input-without-highlight` is now `code-content-without-highlight`. The Moodle XML converter and `mdq show` use `content`. The `essay_questions` strategy now passes `content` to the model (it ignored it before).
- Essay: an `H1` heading (ATX or setext) in the answer key is a `forbidden-block-element` at `answerKey`, in Markdown and in a model.
- Short answer and fill-in short answer blank: a setext underline right after the content of a definition, or after the text of a pattern or choice item, is a `parse-error` (before, it was only found for the first tag, and a list item took `===` as text). A `!` line with four or more columns of indentation continues the content instead of being a `parse-error`. An exact literal that opens at the end of a line, or whose closing run starts a continuation line, is a `schema-error` (new `mdq._exact.join_pattern_lines`).
- Fill-in: a `[^id]` repeated in the stem is the error `duplicate-blank-reference`. The `parse-error` for text on the tag line of a choice blank (`[^capital]: Brasília`) now says the tag line must be empty and suggests `[^capital/short-answer]:`.
- Fill-in: a choice blank without a score on the picked choice scores like a multiple choice question (`partial`: 0; `symmetric`: the derived negative score), not always 0. `unspecified_choice_score` is shared with `MultipleChoiceQuestion`.
- Fill-in: a pending short answer blank no longer hides a malformed response to a later blank; the `ResponseError` comes first.
- Fill-in: a blank definition tag line in the epilogue is the error `detached-blank-definition`, and the stem reference of that id gives no `undefined-blank`.
- Fill-in stem: a `[^id]` in a code span is literal text (no `misplaced-blank`, no reference to a blank), as in fenced and indented code. A `[^id]` in a heading, list item, table cell, blockquote, emphasis, strong, link text or image alt text is `misplaced-blank`. `[^id](url)` and `[^id][ref]` are links, not blanks. New `mdq._markdown.find_blank_markers`.
- A numeric value with a huge exponent (`[numeric]: 1e999999999`) no longer hangs the parser: the range is checked before any `Fraction` exists. The exponent has at most 3 digits, and a value or tolerance above the largest finite double, or not zero but rounding to 0 as a double, is a `ParseError` in a body, `malformed-numeric-answer` in an `answer` and a `ResponseError` in a response (also a Python `int` beyond a double).
- Numeric: new model error `missing-decimal-places` (fraction answer, `decimal` domain, no `decimalPlaces`, no absolute tolerance with decimal places), for a numeric question and a numeric blank. The inference of `decimalPlaces` never counts the places of a fraction: the parser used to give a fraction answer 0 places and round it to 0.
- An image line (`![alt](src)`) after an ordering section tag is no longer read as a comment block, so the error no longer says that only a feedback and a comment block can follow.
- GIFT and Moodle XML import no longer reject a short answer that contains a backtick: the pattern is an exact literal with a longer fence (`` `x` `` becomes ``` `` `x` `` ```).

### Added

- Tests for the grading corpus `examples/grading/fill-in.yaml`.
- Scientific notation in a number (`6.022e23`, `1E-3`, `2.5e+4`, `1e05`): the Markdown body (value and both tolerances), `parse_numeric_string`, a string `answer` and the string of a response. A number with an exponent is `decimal`, and the inferred decimal places are `max(0, digits after the point - exponent)`, also for a string or a float (`1e-07` has 7). A value with an exponent is a float when the float gives back the digits and the mantissa has no trailing zero after the point (`1.50e3` stays a string). A fraction takes no exponent. The renderer still writes plain notation, so a large float comes back from `render()` as a string of the same value.
- A `parse-error` for U+2212, `±`, a decimal comma or a digit group separator in a numeric body says which spelling to write (`use "-"`, `use "+-"`, `use "." as the decimal separator`, `remove the digit group separator`).
- `NumericBlank.incorrect_feedback` (`incorrectFeedback` of the blank, from the fill-in frontmatter map): `FillInQuestion.score_response` adds it to the feedback of an incorrect numeric blank. A skipped blank and a correct one show none. A choice blank still rejects the map entry with a `schema-error`.
- `NumericQuestion.incorrect_feedback` (frontmatter `incorrectFeedback`): `score_response` returns it as feedback for an incorrect response, never for a correct one. A malformed response is still a `ResponseError`.
- The fill-in frontmatter maps `domain` and `decimalPlaces` set those fields of a numeric blank, over the inferred values. A key that is not a blank is `undefined-blank`; a key of a choice or short answer blank is a `schema-error` on that blank. `FillInQuestion.frontmatter()` writes them back.

### Changed

- The `preamble` field is removed. `stem` holds every block between the frontmatter (or the slug) and the body: one or more block elements, still required. `preamble` in YAML/JSON is a `schema-error`, and in the frontmatter an `invalid-frontmatter-field`. The converters (Moodle XML, GIFT, Aiken) read the question text from `stem`. The rules for forbidden elements, `blank-text`, `unsafe-thematic-break`, `stray-choice-marker` and `setext-heading` apply to `stem` and `epilogue`. `normalize_intro` is now `normalize_stem`.
- Fill-in: a blank may appear in any ordinary paragraph of the stem, not only in its last paragraph.
- Numeric lint: `answer-outside-domain` also reports a `fraction` domain with an answer that is neither whole nor a fraction string (`0.75`, `"0.75"`). `domain-mismatch` only reports a decimal absolute tolerance under `integer` or `fraction`. `missing-tolerance` only reports a `decimal` domain (declared or inferred), so a fraction without tolerance has no diagnostic and a declared `decimal` with an integer answer has one.
- Numeric: a YAML/JSON number of whole value (`4.0`) counts 0 decimal places, as it already counted as `integer`. A number `answer` or tolerance that is not finite (`.inf`, `.nan`) is the `malformed-numeric-answer` error; before, `mdq validate` crashed with `OverflowError` or a raw error.
- Numeric responses follow the table of `docs/responses.md`: a fraction (`"1/3"`, `"4/2"`, a `Fraction` that no finite decimal spells) is malformed in a `decimal` question, and a non-finite number or a `bool` is malformed in every domain. A response string is exactly `sign? value`: `"1e3"`, `"1,5"`, `" 5"` and `"1 000"` are a `ResponseError` (before, `Fraction` read some of them).
- Numeric responses accept the `{value, unit}` form (`NumericUnitResponse`, also in a numeric blank). A unit equal to the declared one after NFC, or absent, is valid. Any other unit, or a unit on a question without one, is a `ResponseError`. `numeric_matches` takes a `unit` argument.
- A Markdown frontmatter may hold only the fields of its frontmatter table: any other key is the error `invalid-frontmatter-field` and `load` returns no document. Its message says when the key is a field of the body (`stem`, `choices`, `accept`, `unit`, ...) and shows the body syntax. It replaces the warning `unknown-frontmatter-key`, which no longer exists, for questions, exams and question blocks of an exam. The allowed keys come from the `frontmatter-<type>` schemas of the bundled `mdq.schema.json`. YAML and JSON are unchanged (an unknown key is a `schema-error`). The `accept` and `reject` of a short answer and the `unit` of a numeric question are no longer frontmatter fields: only the body sets them.
- `id` in the frontmatter and as a slug (`[Q1]`) reports the new `redundant-id` warning, with equal or different values. The frontmatter value wins.
- Removed: the `conflicting-accept` error (`ConflictingAnswerKey`) and the frontmatter `unit`, which overrode the unit of the tag.
- Converters (`literal_pattern`) join the lines of an imported answer with one space, as the continuation lines of a body block do, instead of leaving a line break in the pattern.
- A pattern string with no visible character is `blank-text`: `"   "`, an exact literal of one space (`` ` ` ``) and a lone U+200B, in every pattern list and in fill-in blanks. For an exact literal, the text between the backticks is checked. Before, `"   "` was a `schema-error` and U+200B was accepted. `""` is still a `schema-error`.
- The `patternString` schema uses explicit classes only (no `\s`), as `EXACT_TEXT` and `PLAIN_TEXT` do. A pattern string cannot contain CR or LF. Spaces and tabs at both ends of any pattern are removed before it is classified, so `"  `x`"` is the exact literal `x` (it was a `schema-error`).
- A regex pattern loses the spaces and tabs after its flags, as it already did before the opening `/`. Before, `* /abc/i ` was an `invalid-regex` (`unknown regex flag: ' '`). The last `/` still closes the regex, so an unescaped `/` in the body is valid (`/a/b/` has the body `a/b`); patterns.md now states it.
- A regex runs in code point mode and reads the shorthand classes as explicit classes (patterns.md, "Regex"): `\d` is `[0-9]`, `\w` is `[A-Za-z0-9_]`, `\s` is `UNICODE_SPACE` (no U+FEFF), `\b` and `\B` follow `\w`, inside a character class too. `i` does not widen them, so `/\w/i` rejects `ſ`. Before, Python `re` decided: `/\d/` accepted `٣`, and `\s` differed from JavaScript on U+0085, U+001C to U+001F and U+FEFF. `/\w+/` does not accept `José`: use `/\w+/n`. `\u{...}` is now valid (it was an `invalid-regex`). A shorthand class as the end of a range, such as `[a-\d]`, is an `invalid-regex`.
- A regex pattern matches the response after two steps: NFC, then removal of the `UNICODE_SPACE` code points from both ends, as for an exact literal. The `n` flag applies after them. Before, the regex saw the raw response, so `/Brasília/` rejected `Brasília ` and an NFD `Brasília`.
- A `>` line right after an empty short-answer tag (`[short-answer]:` then `> x`) is a `parse-error`, like a `!` line. Before, it went to the epilogue.
- The error for `[short-answer]: X` followed by a `---` or `===` line says that the tag line became a setext heading and suggests a blank line. Before, it was "A required field is missing".
- Short answer single-line content follows the CommonMark paragraph (also in `[^id/short-answer]` definitions). A lazy line continues the content, also after an empty tag (`[short-answer]:` then `Brasília` is `accept: ["Brasília"]`; `[short-answer/reject]:` then `Rio` is a valid reject). A continuation line is joined with one space, whatever its indentation. A line that starts with `>` or `!` (not `![`) right after the content is a `parse-error` that suggests the list form: before, `> x` went to the epilogue and `! x` was joined into the pattern. A heading, a fenced code block, an HTML block or a thematic break still ends the block and goes to the epilogue.
- An id in a response that names nothing in the question is a `ResponseError`, never ignored: a tick of `MultipleSelectionQuestion` (an element that is not a string is one too), a key of a `TrueFalseQuestion` response, and a key of a `FillInQuestion` response. Multiple choice and the exam scoring already did so. The `MultipleSelectionResponse` docs no longer mention a missing key.
- True/false letter sets follow the spec: TRUE `T V B D Đ` plus non-Latin letters, FALSE `F M` plus non-Latin letters, in `mdq._letters` (`TRUE_LETTERS`, `FALSE_LETTERS`). `S` is now a WARNING letter: it reads as true and gets `unlisted-true-false-marker`, so a marker `S` with `correct: false` is `true-false-marker-disagrees-with-correct`. `D`, `B` and `Đ` are TRUE and `M` is FALSE.
- The locale table is one data structure (`mdq._letters.LOCALE_ROWS`, 27 languages) with the letters accepted and the false friends of each row. `false-friend-true-false-marker` is table-driven (`S` under `id`, `ms` and `vi`, `E` under `pt`, `W` under `en`, ...). The rule order is: false friend, accepted by the row (no warning, even for a WARNING letter), WARNING letter (`unlisted-true-false-marker`), no row (no warning), `locale-mismatched-true-false-marker`. `T`/`F` are canonical under every `locale`.
- `grading` is per question type: `MultipleChoiceQuestion` accepts `partial` and `symmetric` only, `MultipleSelectionQuestion` also `all-or-nothing`, `TrueFalseQuestion` and `FillInQuestion` also `no-mistakes`. New aliases in `mdq.types`: `MultipleChoiceGrading`, `MultipleSelectionGrading`, `TrueFalseGrading`, `FillInGrading`, `MultipleChoiceQuestionGrading`, `MultipleSelectionQuestionGrading`; `GradingStrategy` gains `no-mistakes`. Multiple choice with `all-or-nothing` and multiple selection with `no-mistakes` are a `schema-error`.
- True/false `all-or-nothing` is 1 only when every statement is judged correctly; the old rule is the new `no-mistakes`. Fill in `no-mistakes` is 0 if a filled blank scores below 1, else the mean.
- `Exam.grading_for` translates a scalar exam `grading` per question type (`no-mistakes` is `partial` for multiple choice and `all-or-nothing` for multiple selection; `all-or-nothing` is `partial` for multiple choice). A value in the mapping form must be a strategy of its type (`schema-error`).
- `blank-text` also treats control characters (`Cc`) as invisible, as the visible character definition of the spec says.
- Lint codes `multiple-choice-no-correct-choice` and `multiple-choice-many-correct-choices` are renamed `no-correct-choice` and `many-correct-choices`, as in the spec.
- The exam include block key `include-all` is renamed to `includeAll` (`IncludeAll` model alias, `IncludeAllDict`, parser, linter paths). `include-all` is now an unknown field (`unknown-include-field`).
- `TrueFalseQuestion.score_response` raises `ResponseError` for a value that is neither a boolean nor `None` (`"T"`, `1`), as `docs/responses.md` says. `None` is still an abstention.
- One severity per lint code. `non-ascii-whitespace` is always `warning`; a Unicode space in prose reports the new `non-ascii-whitespace-in-prose` (`info`).
- The lint codes `blank-text-field`, `blank-content-field`, `blank-choice-text`, `blank-choice-feedback`, `blank-choice-comment` and `blank-tag` are replaced by `blank-text` (`error`). It reports a free-text field, or a `tags` entry, that is defined but empty or whitespace only: `title`, `author`, `comment`, `preamble`, `stem`, `epilogue`, exam `description`, `course` and `instructions`, `answerKey`, `incorrectFeedback`, and the `text`, `feedback` and `comment` of a choice, an ordering alternative or a pattern. The check is in the models, so a document loaded from YAML, JSON or a dict is covered, and building a model with a blank field raises. An empty string is no longer a `schema-error` in these fields (the models dropped their `min_length`); `null` still is, and `id`, `include`, `includeAll`, `highlight` and pattern strings keep theirs.
- A `tags` string drops the empty part after a final comma (`"cerrado, bioma,"` is `[cerrado, bioma]`). Any other empty part (`"a,, b"`, `""`) is `blank-text`.
- In Markdown, a choice with no text (`* [ ]`, `* [*] [brasilia]`) and a feedback or comment block of only empty marker lines (`>` alone) reach the `blank-text` check.
- `mdq.hypothesis.safe_texts()` no longer generates text with no visible character.
- Fixed: the models did not enforce several schema `minItems`/`minLength` limits. `load` now reports `schema-error` for an empty fill-in `blanks`, a choice blank with fewer than two choices, an empty `accept`/`reject`/`preAccept`/`preReject` list, an empty ordering `accept`/`reject`, and an empty `id`, `highlight` or include `include`.
- Refreshed the bundled schema (description text only).
- A bracket followed by `(` or `[` starts a markdown link and is not a choice marker. A list of links (`* [IBGE](https://www.ibge.gov.br)`), or a paragraph, heading or list item that starts with a link, is valid in the preamble, stem and epilogue, and is no longer a `forbidden-block-element`. A paragraph of link reference definitions (`[inpe]: https://www.inpe.br`) is not one either, unless it is an MDQ tag. `* [x](url) Rio` and `* [x][ref] Rio` are not choices.
- A choice, a fill-in choice, a pattern item or an ordering section with two feedback blocks or two comment blocks is a `parse-error`, also when a blank line or a block of the other kind separates them. Before, the blocks of a choice were merged. A nested block (a list, a heading, a fence) or a second paragraph after the text of a choice is a `parse-error` too.
- An empty marker line (`>` or `!` alone) in a feedback or comment separates two paragraphs: the value keeps a blank line there instead of joining with a space.
- A list item follows the CommonMark item content. A `>` or `!` line indented four or more columns past the item content continues the text or block before it, and `*      [x] Rio` (five or more spaces after the marker) is an indented code block, not a choice.
- The value of every choice marker is normalized (NFKC, then ASCII lowercase) before type inference and meaning. `[Ｆ]` is false, `[Ｘ]` is `x`, `[＊]` is `*`. `Statement.marker` keeps the written character.
- A true/false marker is one code point in `Lu`, `Ll`, `Lt` or `Lo`. A modifier letter such as `ˇ` or `ー` (`Lm`) is a `foreign-choice-marker` in Markdown and `malformed-true-false-marker` in a model. `Ｘ` is `reserved-true-false-marker`.
- The lint code `non-nfc-true-false-marker` is renamed `non-nfkc-true-false-marker` (message "not its own NFKC form; read as X"). It also covers `Ｆ` and `ſ`.
- New dependency `unicodedata2>=17,<18`: the letter category and NFKC of markers do not depend on the Unicode version of the interpreter.

- Short answer, essay and short answer blank: a response that is not a string (a number, a boolean, a list, a mapping) is a `ResponseError`, as `docs/responses.md` says. Before, a short answer question coerced it and an essay raised `NotAutoGradable`. `""` and a string of only spaces are graded normally. `None` still skips at exam level.
- An exact literal follows the CommonMark code span: ``` `` `date` `` ``` is the literal `` `date` ``. N backticks open it and the first run of exactly N backticks closes it, at the end of the pattern; one space is removed from each end when both ends have one. A pattern that opens with a backtick and is not a complete literal is a `schema-error` with a message that says so (it was the raw pattern of the schema). The type of the pydantic error is now `schema-error`, not `string_pattern_mismatch`. The `AnswerPattern` field `pattern` no longer carries a pydantic regex. `blank-text` checks the content of the literal after the removal of the space.
- Export to an external format (`literal_answers`) returns the content of an exact literal as the new rule reads it. Import (`literal_pattern`) still refuses an answer that needs backticks and has one.

### Fixed

- `load` validates a YAML/JSON/dict document by alias only. A Python field name such as `answer_key`, `pre_accept` or `include_all` was accepted silently; it is now a `schema-error` like any unknown key. Building a model in Python (`Essay(answer_key=...)`) still takes the field names. Requires pydantic 2.11.
- In an exam written in Markdown, a block with a key such as `include-all` (a misspelling of `include`/`includeAll`) gets the same "did you mean `includeAll`?" hint on its `parse-error` (no body) or `unknown-frontmatter-key` warning (with a body).
- An exam entry with no `type` and no `include`/`includeAll` key, and a question with no `type`, now report a clear `schema-error` message instead of pydantic's "Unable to extract tag using discriminator 'type'". A key such as `include-all` gets a "did you mean `includeAll`?" hint.
- A `schema-error` on a field of a bare-string shorthand (an empty pattern line, a choice text) is reported at the string, not below it: `["accept", 0]` instead of `["accept", 0, "pattern"]`.
- `normalize()` no longer trims Unicode spaces (such as U+00A0) from the ends of `stem` and `preamble`: the grammar reads them as text, and the parser keeps them.

### Added

- Lint info `unmatchable-regex-escape`: under the `n` flag, a regex has an escape (`\uXXXX`, `\xXX`, `\u{...}`) for a code point that the diacritics strip changes, such as U+00E1 or a combining mark. The escape is always the exact code point and `n` never strips it, so it cannot match the stripped response. `/água/n` accepts `agua` and `água`; `/\u00e1gua/n` accepts neither.
- Lint warning `stray-choice-marker`: an unordered list in the preamble, stem or epilogue in which some, not all, items start with a choice marker. One warning per item whose marker is a choice value (`[ ]`, `[x]`, `[*]`, a percentage, a letter) or empty (`[]`). It runs on the models, so YAML, JSON and dict documents are covered.
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
- `ShortAnswerQuestion.prevalidate(response)` returns `(valid, feedback)` by the pre-validation rules of short-answer.md. `ShortAnswerBlank.prevalidate(response, diacritics=...)` does the same for a fill-in blank.
- `ShortAnswerBlank.incorrect_feedback` (`incorrectFeedback`): a fill-in short answer blank shows it for an incorrect response that no pattern gave feedback to. The fill-in frontmatter takes it as a map from blank id to string; an unknown id is `undefined-blank`. `frontmatter()` and `render()` write the map.
- `tests/test_grading_examples.py` runs the `feedback` key of the short answer vectors and the new `examples/grading/short-answer-prevalidation.yaml`.

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
