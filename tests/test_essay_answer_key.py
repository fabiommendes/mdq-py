"""essay.md, "Answer key": the paragraph with only the tag is never a slug."""

import mdq


def test_paragraph_with_only_the_tag_is_never_a_slug() -> None:
    loaded = mdq.load("[essay]\n", kind="question")
    errors = [(d.code, tuple(d.path)) for d in loaded.diagnostics if d.severity == "error"]
    assert errors == [("parse-error", ())]
