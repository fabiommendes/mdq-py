"""Moodle XML and the upload question: import, export and round trip."""

from __future__ import annotations

import pytest

import mdq
from mdq.convert import export_question, import_question
from mdq.convert._base import ConversionError, Report
from mdq.convert._moodle_xml import MoodleXml, MoodleXmlParser
from mdq.models import EssayQuestion, UploadQuestion

CONVERTER = MoodleXml()


def _xml(**fields: str) -> str:
    body = "".join(f"<{tag}>{value}</{tag}>" for tag, value in fields.items())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<quiz><question type="essay">'
        "<name><text>Q</text></name>"
        '<questiontext format="markdown"><text>Send it.</text></questiontext>'
        f"{body}</question></quiz>"
    )


def _import(**fields: str) -> tuple[object, list[str]]:
    report = Report("Moodle XML")
    moodle = MoodleXmlParser(_xml(**fields), report).parse()
    question = CONVERTER.to_mdq(moodle, report)
    return question, [d.code for d in report.diagnostics]


def _export(question: UploadQuestion) -> tuple[str, list[str]]:
    report = Report("Moodle XML")
    source = str(CONVERTER.from_mdq(question, report))
    return source, [d.code for d in report.diagnostics]


def _upload(**fields: object) -> UploadQuestion:
    loaded = mdq.load({"type": "upload", "stem": "Send it.", **fields}, kind="question")
    question = loaded.document
    assert isinstance(question, UploadQuestion)
    return question


# Import ----------------------------------------------------------------


def test_import_noinline_with_attachments_is_upload() -> None:
    question, codes = _import(
        responseformat="noinline",
        attachments="2",
        maxbytes="1048576",
        filetypeslist=".pdf,.zip",
        graderinfo="<text>Key</text>",
    )
    assert isinstance(question, UploadQuestion)
    assert (question.max_files, question.max_size) == (2, 1048576)
    assert question.extensions == [".pdf", ".zip"]
    assert codes == []


def test_import_graderinfo_becomes_the_answer_key() -> None:
    xml = _xml(responseformat="noinline", attachments="1").replace(
        "</question>", "<graderinfo format=\"markdown\"><text>Look at X.</text></graderinfo></question>"
    )
    report = Report("Moodle XML")
    question = CONVERTER.to_mdq(MoodleXmlParser(xml, report).parse(), report)
    assert isinstance(question, UploadQuestion)
    assert question.answer_key == "Look at X."


def test_import_unlimited_attachments_is_ten_files_with_a_warning() -> None:
    question, codes = _import(responseformat="noinline", attachments="-1")
    assert isinstance(question, UploadQuestion)
    assert question.max_files == 10
    assert codes == ["field-dropped"]


def test_import_more_than_three_attachments_is_kept() -> None:
    question, codes = _import(responseformat="noinline", attachments="7")
    assert isinstance(question, UploadQuestion)
    assert question.max_files == 7 and codes == []


@pytest.mark.parametrize("maxbytes", ["0", None])
def test_import_no_maxbytes_omits_max_size(maxbytes: str | None) -> None:
    fields = {"responseformat": "noinline", "attachments": "1"}
    if maxbytes is not None:
        fields["maxbytes"] = maxbytes
    question, _ = _import(**fields)
    assert isinstance(question, UploadQuestion)
    assert question.max_size is None


def test_import_file_types_are_normalised() -> None:
    question, codes = _import(
        responseformat="noinline", attachments="1", filetypeslist=".PDF; .zip  .Pdf,.zip"
    )
    assert isinstance(question, UploadQuestion)
    assert question.extensions == [".pdf", ".zip"]
    assert codes == []


def test_import_groups_and_mime_types_are_dropped_with_a_warning() -> None:
    question, codes = _import(
        responseformat="noinline", attachments="1", filetypeslist="image,.pdf,application/zip"
    )
    assert isinstance(question, UploadQuestion)
    assert question.extensions == [".pdf"]
    assert codes == ["field-dropped"]


@pytest.mark.parametrize("types", ["image,document", "*", "application/pdf", "", " "])
def test_import_without_extensions_accepts_any_file(types: str) -> None:
    question, codes = _import(responseformat="noinline", attachments="1", filetypeslist=types)
    assert isinstance(question, UploadQuestion)
    assert question.extensions is None
    assert codes == (["field-dropped"] if types.strip() else [])


def test_import_the_warning_of_empty_extensions_says_any_file() -> None:
    report = Report("Moodle XML")
    xml = _xml(responseformat="noinline", attachments="1", filetypeslist="image")
    CONVERTER.to_mdq(MoodleXmlParser(xml, report).parse(), report)
    assert "any file" in report.diagnostics[0].message


def test_import_required_attachments_above_one_warns() -> None:
    question, codes = _import(
        responseformat="noinline", attachments="3", attachmentsrequired="2"
    )
    assert isinstance(question, UploadQuestion)
    assert codes == ["field-dropped"]


def test_import_required_attachments_of_one_is_silent() -> None:
    _, codes = _import(responseformat="noinline", attachments="3", attachmentsrequired="1")
    assert codes == []


def test_import_required_attachments_of_zero_is_still_an_upload_without_warning() -> None:
    question, codes = _import(responseformat="noinline", attachments="2", attachmentsrequired="0")
    assert isinstance(question, UploadQuestion)
    assert codes == []


@pytest.mark.parametrize(
    "response_format", ["editor", "editorfilepicker", "plain", "monospaced", "noinline"]
)
def test_import_essay_with_invalid_attachments_stays_essay(response_format: str) -> None:
    question, _ = _import(responseformat=response_format, attachments="abc")
    assert isinstance(question, EssayQuestion)


@pytest.mark.parametrize("response_format", ["editor", "editorfilepicker", "plain", "monospaced"])
def test_import_text_essay_with_attachments_stays_essay(response_format: str) -> None:
    report = Report("Moodle XML")
    moodle = MoodleXmlParser(_xml(responseformat=response_format, attachments="2"), report).parse()
    question = CONVERTER.to_mdq(moodle, report)
    assert isinstance(question, EssayQuestion)
    attached = [d for d in report.diagnostics if "files that the student attaches" in d.message]
    assert [(d.code, d.path) for d in attached] == [("field-dropped", ())]


@pytest.mark.parametrize("attachments", [{"attachments": "0"}, {}])
def test_import_noinline_without_attachments_stays_essay(attachments: dict[str, str]) -> None:
    question, codes = _import(responseformat="noinline", **attachments)
    assert isinstance(question, EssayQuestion)
    assert codes == ["field-dropped"]


def test_import_essay_without_attachments_is_silent() -> None:
    question, codes = _import(responseformat="editor", attachments="0")
    assert isinstance(question, EssayQuestion)
    assert codes == []


# Export ----------------------------------------------------------------


def test_export_upload_is_a_noinline_essay() -> None:
    source, codes = _export(
        _upload(maxFiles=2, maxSize="5 MB", extensions=[".pdf", ".zip"], answerKey="Key")
    )
    assert codes == []
    assert '<question type="essay">' in source
    for expected in (
        "<responseformat>noinline</responseformat>",
        "<responserequired>0</responserequired>",
        "<attachments>2</attachments>",
        "<attachmentsrequired>1</attachmentsrequired>",
        "<maxbytes>5242880</maxbytes>",
        "<filetypeslist>.pdf,.zip</filetypeslist>",
        "Key",
    ):
        assert expected in source


def test_export_without_limits() -> None:
    source, codes = _export(_upload())
    assert codes == []
    assert "<attachments>1</attachments>" in source
    assert "<maxbytes>0</maxbytes>" in source
    assert "filetypeslist" not in source


def test_export_many_files_is_unlimited_with_a_warning() -> None:
    source, codes = _export(_upload(maxFiles=5))
    assert "<attachments>-1</attachments>" in source
    assert codes == ["field-dropped"]


# Round trip ------------------------------------------------------------


def _round_trip(question: UploadQuestion) -> tuple[object, list[str]]:
    report = Report("Moodle XML")
    source = CONVERTER.render(CONVERTER.from_mdq(question, report))
    moodle = MoodleXmlParser(source, report).parse()
    return CONVERTER.to_mdq(moodle, report), [d.code for d in report.diagnostics]


@pytest.mark.parametrize("max_files", [1, 2, 3])
def test_round_trip_keeps_max_files(max_files: int) -> None:
    question = _upload(maxFiles=max_files, extensions=[".pdf"], answerKey="Key")
    again, codes = _round_trip(question)
    assert isinstance(again, UploadQuestion)
    assert (again.max_files, again.extensions, again.answer_key) == (max_files, [".pdf"], "Key")
    assert codes == []


def test_round_trip_five_files_becomes_ten_with_two_warnings() -> None:
    again, codes = _round_trip(_upload(maxFiles=5))
    assert isinstance(again, UploadQuestion)
    assert again.max_files == 10
    assert codes == ["field-dropped", "field-dropped"]


def test_round_trip_size_string_becomes_bytes() -> None:
    again, _ = _round_trip(_upload(maxSize="5 MB"))
    assert isinstance(again, UploadQuestion)
    assert again.max_size == 5242880


def test_round_trip_no_limits() -> None:
    again, _ = _round_trip(_upload())
    assert isinstance(again, UploadQuestion)
    assert (again.max_size, again.extensions) == (None, None)


# Other formats refuse upload --------------------------------------------


@pytest.mark.parametrize("format", ["gift", "aiken"])
def test_other_formats_refuse_upload(format: str) -> None:
    with pytest.raises(ConversionError) as info:
        export_question(_upload(), format=format)
    assert [d.code for d in info.value.diagnostics] == ["unsupported-type"]


def test_public_api_round_trip() -> None:
    source = export_question(_upload(maxFiles=1), format="moodle-xml")
    assert isinstance(import_question(source, format="moodle-xml"), UploadQuestion)
