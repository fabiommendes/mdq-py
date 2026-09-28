"""
Hypothesis strategies used only by the test suite: generators for the
converter formats (`aiken`, `gift`, `moodle_xml`), `mdq.models._slugify`
(`slugs`), the exam `start`/`duration` grammar (`schedule`), and the
`unknown-frontmatter-key` lint rule (`frontmatter`).

`mdq.hypothesis` ships the strategies a user of the `mdq[hypothesis]`
extra needs (questions and exams); the submodules here exercise this
repo's own internals and stay out of the wheel.
"""
