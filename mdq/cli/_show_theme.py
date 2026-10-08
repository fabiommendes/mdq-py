"""
Themes for `mdq show`: palettes, glyph sets and box styles.

A theme makes a question look like a card on a web page. `dark` and
`light` set the foreground *and* the background of the card, so the card
reads the same on any terminal background. `plain` has no colors,
no emoji and only ASCII borders and glyphs, for terminals and logs that
cannot show anything else. (Markdown bullets stay `•`: Rich draws them.)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

from rich import box
from rich.box import Box
from rich.console import Console

__all__ = ["ThemeName", "Theme", "resolve_theme"]


class ThemeName(str, Enum):
    auto = "auto"
    dark = "dark"
    light = "light"
    plain = "plain"


@dataclass(frozen=True)
class Glyphs:
    radio_off: str
    radio_on: str
    radio_partial: str
    radio_negative: str
    check_off: str
    check_on: str
    key: str
    lock: str
    note: str
    feedback: str
    handle: str
    bullet: str
    ok: str
    no: str
    include: str
    edit: str
    bar: str
    locale: str
    author: str
    course: str
    start: str
    duration: str
    grading: str
    shuffle: str
    info: str
    blank: str


UNICODE = Glyphs(
    radio_off="◯",
    radio_on="◉",
    radio_partial="◐",
    radio_negative="⊖",
    check_off="☐",
    check_on="☑",
    key="🔑",
    lock="🔒",
    note="📝",
    feedback="💬",
    handle="⠿",
    bullet="•",
    ok="✔",
    no="✘",
    include="⤷",
    edit="✎",
    bar="▎",
    locale="🌐",
    author="👤",
    course="📚",
    start="📅",
    duration="⏰",
    grading="🎯",
    shuffle="🔀",
    info="ℹ",
    blank="▭",
)

ASCII = Glyphs(
    radio_off="( )",
    radio_on="(o)",
    radio_partial="(~)",
    radio_negative="(-)",
    check_off="[ ]",
    check_on="[x]",
    key="*",
    lock="#",
    note=">",
    feedback=">",
    handle=":",
    bullet="-",
    ok="+",
    no="x",
    include="->",
    edit=">",
    bar="|",
    locale="",
    author="",
    course="",
    start="",
    duration="",
    grading="",
    shuffle="",
    info="i",
    blank="_",
)


@dataclass(frozen=True)
class Theme:
    name: str
    glyphs: Glyphs
    #: Outer card, the banner of an exam, and nested panels.
    card_box: Box
    banner_box: Box
    inner_box: Box
    #: Character of the horizontal rules between sections.
    rule_char: str = "─"
    fg: str = ""
    card_bg: str = ""
    border: str = ""
    muted: str = ""
    chip_bg: str = ""
    correct: str = ""
    correct_bg: str = ""
    wrong: str = ""
    partial: str = ""
    note: str = ""
    note_bg: str = ""
    badge_fg: str = ""
    exam_accent: str = ""
    #: Accent color of the type badge, by question type.
    accents: dict[str, str] = field(default_factory=dict)
    code_theme: str = "default"
    #: Console style of `inline code`; overrides Rich's black background.
    inline_code: str = ""

    @property
    def card_style(self) -> str:
        return f"{self.fg} on {self.card_bg}".strip() if self.card_bg else ""

    def badge_style(self, question_type: str) -> str:
        accent = self.accents.get(question_type, self.exam_accent)
        if not accent:
            return "bold reverse"
        return f"bold {self.badge_fg} on {accent}"

    @property
    def chip_style(self) -> str:
        return f"{self.fg} on {self.chip_bg}".strip() if self.chip_bg else "reverse"

    @property
    def key_style(self) -> str:
        return f"on {self.correct_bg}" if self.correct_bg else ""

    @property
    def note_style(self) -> str:
        return f"on {self.note_bg}" if self.note_bg else ""


# Catppuccin Mocha
_DARK = Theme(
    name="dark",
    glyphs=UNICODE,
    card_box=box.ROUNDED,
    banner_box=box.DOUBLE,
    inner_box=box.ROUNDED,
    fg="#cdd6f4",
    card_bg="#1e1e2e",
    border="#6c7086",
    muted="#7f849c",
    chip_bg="#313244",
    correct="#a6e3a1",
    correct_bg="#26382d",
    wrong="#f38ba8",
    partial="#f9e2af",
    note="#f9e2af",
    note_bg="#34311f",
    badge_fg="#11111b",
    exam_accent="#89b4fa",
    accents={
        "multiple-choice": "#89b4fa",
        "multiple-selection": "#cba6f7",
        "true-false": "#94e2d5",
        "short-answer": "#f9e2af",
        "numeric": "#fab387",
        "fill-in": "#f5c2e7",
        "essay": "#a6e3a1",
        "ordering": "#89dceb",
    },
    code_theme="monokai",
    inline_code="bold #f5c2e7 on #313244",
)

# Catppuccin Latte
_LIGHT = Theme(
    name="light",
    glyphs=UNICODE,
    card_box=box.ROUNDED,
    banner_box=box.DOUBLE,
    inner_box=box.ROUNDED,
    fg="#4c4f69",
    card_bg="#eff1f5",
    border="#9ca0b0",
    muted="#7c7f93",
    chip_bg="#ccd0da",
    correct="#40a02b",
    correct_bg="#d9ecd3",
    wrong="#d20f39",
    partial="#b8730f",
    note="#b8730f",
    note_bg="#f3e8cc",
    badge_fg="#eff1f5",
    exam_accent="#1e66f5",
    accents={
        "multiple-choice": "#1e66f5",
        "multiple-selection": "#8839ef",
        "true-false": "#179299",
        "short-answer": "#b8730f",
        "numeric": "#d9500b",
        "fill-in": "#c2409b",
        "essay": "#40a02b",
        "ordering": "#0a8cb8",
    },
    code_theme="default",
    inline_code="bold #c2409b on #ccd0da",
)

_PLAIN = Theme(
    name="plain",
    glyphs=ASCII,
    card_box=box.ASCII,
    banner_box=box.ASCII2,
    inner_box=box.ASCII,
    rule_char="-",
    inline_code="bold",
)

_THEMES = {"dark": _DARK, "light": _LIGHT, "plain": _PLAIN}


def resolve_theme(name: ThemeName | str | None, console: Console) -> Theme:
    """
    The theme to use for `name`.

    `auto` is `light` if `COLORFGBG` says the terminal background is
    light (the only hint terminals give), and `dark` otherwise. A console
    that cannot encode the unicode glyphs always gets `plain`.
    """
    chosen = ThemeName(name) if name is not None else ThemeName.auto
    if chosen is ThemeName.auto:
        chosen = ThemeName.light if _background_is_light() else ThemeName.dark
    if chosen is not ThemeName.plain and not _supports_unicode(console):
        chosen = ThemeName.plain
    return _THEMES[chosen.value]


def _background_is_light() -> bool:
    # `COLORFGBG` is "<foreground>;<background>" in ANSI color indexes.
    background = os.environ.get("COLORFGBG", "").rsplit(";", 1)[-1]
    return background.isdigit() and int(background) in (7, *range(9, 16))


def _supports_unicode(console: Console) -> bool:
    return console.encoding.lower().replace("-", "").startswith("utf")
