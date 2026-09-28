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