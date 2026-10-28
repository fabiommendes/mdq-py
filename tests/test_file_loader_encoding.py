"""`FileLoader` skips a file that is not UTF-8, as it skips an invalid question."""

from __future__ import annotations

from pathlib import Path

from mdq._banks import FileLoader

GOOD = "---\ntags: [geo]\n---\n\nQual é a capital do Brasil?\n\n- [x] Brasília\n- [ ] Rio\n"


def test_a_non_utf8_file_is_left_out_of_the_index(tmp_path: Path) -> None:
    (tmp_path / "good.mdq.md").write_text(GOOD, encoding="utf-8")
    (tmp_path / "latin.mdq.md").write_bytes(GOOD.encode("latin-1"))
    bank = FileLoader(tmp_path)
    assert set(bank.ids()) == {"good"}
    assert set(bank.tagged("geo")) == {"good"}
