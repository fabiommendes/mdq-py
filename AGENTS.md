## Package layout

Public modules (each has a `docs/api/` page): `mdq`, `mdq.models`,
`mdq.types`, `mdq.errors`, `mdq.convert`, `mdq.hypothesis`. `mdq.cli`
exposes only `app`/`main` and is not API.

Everything else is a `_module`, owned by one package. Rule: a `_module`
is imported only by its parent package or its siblings -- never from
outside that package. Known exception: `cli/_show.py` imports
`models/_render.py`. Tests may import private modules directly (unit
tests of `_regex`, `_slugify`, `_query`, a converter's internals, ...);
host code and docs never do.

Where things live: `_parser/` (Markdown -> dict, one file per question
family), `models/` (dict -> Pydantic, one file per question family),
`convert/` (MDQ <-> external formats, one file per format), `cli/`
(one file per command). `tests/_corpus.py` loads the example corpus;
`tests/strategies/` holds Hypothesis strategies for the converters;
`scripts/` holds maintenance scripts run with `uv run scripts/<name>.py`.

## Typing discipline

* Use `T | None` instead of `Optional[T]` for optional types.
* Use `T | S` instead of `Union[T, S]` for union types.
* Use builtins `list`, `dict`, `tuple`, `set` instead of `List`, `Dict`, `Tuple`, `Set`.
* Check types with mypy `uv run mypy mdq`. 
* Avoid using `Any`, unless it is specifying "value can be anything" and it will still work and always document its usage.
* Model the document tree (questions, exams, grades) with Pydantic models.
* Pydantic models mirror the JSON schemas in `schema/`. They might be stricter
  than the JSON schema, if the spec has a rule that cannot be enforced by schema
  alone. Pydantic models only enforce required rules. An extra linting pass
  may be necessary to catch non-critical violations.