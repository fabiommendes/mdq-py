"""
Write the new state of a question back into its Markdown source with the
fewest edits: `sync_question`.

The edits come in two kinds. A field the frontmatter holds is changed in
place: the position of each YAML node (`_parser.compose_yaml`) says which
text to replace, so quotes, comments, blank lines and the order of the keys
stay as written. A field the body holds is rewritten with the canonical
`render()` of the question, the whole body at once.

Every result is checked by parsing it back. When the minimal edit does not
parse to the target, the question is rendered in full, and when that does
not either, the target cannot be written in Markdown (`SyncError`).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

import yaml

from . import _parser
from ._loading import parse
from ._markdown import SLUG_BODY_RE, split_lines, strip_bom
from ._parser import SLUG_PREFIX_RE
from .errors import SyncError
from .models import Question, can_inline_id

# Typing: `to_dict()` of a question is JSON-like data, a tree of dicts, lists
# and scalars whose shape depends on the question type. The helpers below read
# and compare that tree key by key, so `dict[str, Any]` ("any JSON value") is
# the honest type for it; the models give the typed view.

__all__ = ["sync_question"]

#: The keys of a blank that the frontmatter of a fill-in question holds, as
#: a map from the blank id to the value.
_BLANK_FRONT_KEYS = (
    "domain",
    "decimalPlaces",
    "preAccept",
    "preReject",
    "incorrectFeedback",
)

#: Keys of the dict form of a question that are not plain frontmatter fields.
_SPECIAL_KEYS = ("comment", "id", "type")

#: Whitespace that the parser skips around the blocks.
_WS = " \t\r\n"


#: A line ending.
_EOL_RE = re.compile(r"\r\n|\r|\n")

#: The name of an anchor or of an alias, after its `&` or `*`.
_ANCHOR_RE = re.compile(r"[&*]([^\s,\[\]{}]+)")


def sync_question(src: str, target: Question) -> str:
    """
    Return `src` edited so that it reads as `target`.

    The edit is minimal: a change to a field of the frontmatter touches only
    that field, and a change to the body rewrites the body. Everything else,
    such as comments, quotes, blank lines and the order of the keys, stays.
    The result satisfies two laws, with the parsed side normalized:

    * `parse(out, ids="fill").normalize().to_dict()` equals
      `target.with_ids().normalize().to_dict()`.
    * `sync_question(src, parse(src, ids="fill")) == src`, byte by byte.

    A choice id that the parse would derive from the result is not written;
    any other id is written. The status of the question is not part of the
    source.

    Args:
        src: the current source text of the question.
        target: the new state of the question.

    Raises:
        SyncError: `src` is not a valid question, or no text parses to
            `target`, even the full `render()` of it.
    """
    want = target.with_ids().normalize()
    goal = want.to_dict()
    current = _load(src)
    if current is None:
        raise SyncError("the source is not a valid question")
    if current.normalize().to_dict() == goal:
        return src

    variants = _id_variants(want)
    body_changed = _split_view(current.normalize().to_dict())[1] != _split_view(goal)[1]
    for model in variants:
        for force in (False, True) if not body_changed else (True,):
            out = _edit(src, model, goal, force)
            if out is not None and _same(out, goal):
                return out
    for model in variants:
        try:
            rendered = model.render()
        except ValueError:
            continue
        for out in (_like_source(rendered, src), rendered):
            if _same(out, goal):
                return out
    raise SyncError("Markdown cannot express the target question")


#
# Checks
#


def _load(text: str) -> Question | None:
    """The question `text` reads as, with the derived ids, or `None`."""
    try:
        document = parse(text, kind="question", ids="fill")
    except ValueError:
        return None
    return document


def _same(text: str, goal: dict[str, Any]) -> bool:
    """Law 1: `text` parses to `goal`, up to normalization."""
    document = _load(text)
    return document is not None and document.normalize().to_dict() == goal


#
# Line endings
#


def _eol_of(text: str) -> str | None:
    """The line ending that `text` uses the most (`\\n` wins a tie), or `None`."""
    counts = {"\n": 0, "\r\n": 0, "\r": 0}
    for match in _EOL_RE.finditer(text):
        counts[match.group()] += 1
    best = max(counts, key=lambda eol: counts[eol])
    return best if counts[best] else None


def _like_source(text: str, src: str) -> str:
    """`text` with the line ending and the final line break of `src`."""
    eol = _eol_of(src) or "\n"
    text = text.rstrip("\r\n")
    ends = _EOL_RE.search(src, max(len(src) - 2, 0))
    text = text.replace("\n", eol)
    return text + (ends.group() if ends else "") if src.rstrip("\r\n") != src else text


#
# Views of the dict form
#


def _front_fields(data: dict[str, Any]) -> frozenset[str]:
    return _parser.frontmatter_fields(data["type"])


def _pattern_form(entry: Any) -> Any:
    """The document form of a pattern entry: a string when only the pattern is set."""
    if isinstance(entry, dict) and set(entry) == {"pattern"}:
        return entry["pattern"]
    return entry


def _split_view(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Split the dict form of a question into the fields that come from the
    frontmatter and those that come from the body. `comment`, `id` and
    `type` are in neither. A fill-in question holds its frontmatter fields
    on the blanks: they go to the maps of the frontmatter, keyed by blank id.
    A pattern list is in its document form, a bare string for a lone pattern.
    """
    fm_keys = _front_fields(data)
    front = {k: v for k, v in data.items() if k in fm_keys and k not in _SPECIAL_KEYS}
    body = {
        k: v for k, v in data.items() if k not in fm_keys and k not in _SPECIAL_KEYS
    }
    blanks = body.get("blanks")
    if isinstance(blanks, list):
        kept = []
        for blank in blanks:
            kept.append({k: v for k, v in blank.items() if k not in _BLANK_FRONT_KEYS})
            for key in _BLANK_FRONT_KEYS:
                if key in blank:
                    value = blank[key]
                    if key in ("preAccept", "preReject"):
                        value = [_pattern_form(p) for p in value]
                    front.setdefault(key, {})[blank["id"]] = value
        body["blanks"] = kept
    return front, body


def _choice_lists(data: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """The lists of choices of a question: its own and those of its blanks."""
    lists = []
    if isinstance(data.get("choices"), list):
        lists.append(data["choices"])
    for blank in data.get("blanks") or []:
        if isinstance(blank.get("choices"), list):
            lists.append(blank["choices"])
    return lists


def _id_variants(want: Question) -> list[Question]:
    """
    `want` without the choice ids that the parse derives anyway, then `want`.
    An id goes only when the derivation of the others, which keep their ids,
    gives it back: an id that is not derived is written.
    """
    data = want.to_dict()
    stripped = copy.deepcopy(data)
    flat = [c for choices in _choice_lists(stripped) for c in choices]
    full = [c.get("id") for c in flat]
    try:
        for choice in flat:
            if "id" not in choice:
                continue
            saved = choice.pop("id")
            derived = type(want).model_validate(stripped).with_ids().to_dict()
            if [c.get("id") for lst in _choice_lists(derived) for c in lst] != full:
                choice["id"] = saved
        if stripped == data:
            return [want]
        return [type(want).model_validate(stripped), want]
    except ValueError:
        return [want]


#
# Text layout and edits
#


@dataclass
class _Edit:
    """Replace `text[start:end]` by `text`."""

    start: int
    end: int
    text: str
    #: A required edit stays even when the parse does not need it: the inline
    #: `[id]` is updated together with the `id` of the frontmatter.
    required: bool = False
    #: A smaller edit to try when the edit is needed, such as the removal of
    #: a key whose new value the parse infers anyway.
    alt: _Edit | None = None


def _apply(text: str, edits: list[_Edit]) -> str:
    """Apply edits that do not overlap, from the last to the first."""
    order = sorted(
        enumerate(edits),
        key=lambda pair: (pair[1].start, pair[1].end, pair[0]),
        reverse=True,
    )
    for _, edit in order:
        text = text[: edit.start] + edit.text + text[edit.end :]
    return text


@dataclass(frozen=True)
class _Layout:
    """Where the frontmatter and the body are in a source text."""

    #: Offset of the first character of the frontmatter, after the opening
    #: fence line; `None` when there is no frontmatter.
    fm_start: int | None
    #: Offset of the closing fence line.
    fm_end: int | None
    #: Offset of the first character after the frontmatter.
    body_start: int
    #: The line ending of the frontmatter; of the whole source when it has none.
    front_eol: str
    #: The line ending of the body; of the whole source when it is empty.
    body_eol: str
    #: The line ending of the whole source.
    eol: str


def _layout(text: str) -> _Layout:
    bom = len(text) - len(strip_bom(text))
    lines = split_lines(text[bom:], keepends=True)
    eol = _eol_of(text) or "\n"
    if lines and lines[0].rstrip("\r\n") == "---":
        offset = bom + len(lines[0])
        start = offset
        for line in lines[1:]:
            if line.rstrip("\r\n") == "---":
                body_start = offset + len(line)
                return _Layout(
                    start,
                    offset,
                    body_start,
                    _eol_of(text[:body_start]) or eol,
                    _eol_of(text[body_start:]) or eol,
                    eol,
                )
            offset += len(line)
    return _Layout(None, None, bom, eol, eol, eol)


def _edit(
    src: str, model: Question, goal: dict[str, Any], force_body: bool
) -> str | None:
    """
    The minimal edit of `src` towards `goal`, or `None` when none is found.
    `model` is the question to render when the body changes, and the edits of
    the frontmatter and of the body are applied together and checked once.
    The fields to write come from the difference of the current question and
    `goal`, not from the frontmatter of the canonical render.
    """
    current = _load(src)
    assert current is not None
    current_data = current.normalize().to_dict()
    original = _layout(src)
    virtual = original.fm_start is None
    try:
        front = None if virtual else _Front(src, original)
    except (ValueError, yaml.YAMLError):
        return None
    node = front.node if front is not None else None

    current_front = _split_view(current_data)[0]
    goal_front = _split_view(goal)[0]
    stored = _scalar_front_value(node, "type")
    if stored is not None:
        current_front = {"type": stored, **current_front}
    want_type = model.frontmatter(skip_defaults=True).get("type")
    if want_type is not None:
        goal_front = {"type": want_type, **goal_front}

    id_in_front = node is not None and any(str(k.value) == "id" for k, _ in node.value)
    current_id, goal_id = current_data.get("id"), goal.get("id")
    valid = isinstance(goal_id, str) and re.fullmatch(SLUG_BODY_RE, goal_id) is not None
    inline_old = _inline_span(src, original)
    inline_id: str | None = None
    if force_body and inline_old is not None and valid and can_inline_id(model.stem):
        inline_id = str(goal_id)
    if force_body:
        inline_written = inline_id is not None
    else:
        inline_written = inline_old is not None and (valid or current_id == goal_id)
    id_changed = current_id != goal_id or (
        force_body and inline_old is not None and not inline_written
    )
    if id_changed and (id_in_front or (goal_id is not None and not inline_written)):
        if id_in_front:
            current_front = {"id": current_id, **current_front}
        if goal_id is not None:
            goal_front = {"id": goal_id, **goal_front}

    inline_new = (
        virtual
        and id_changed
        and inline_old is None
        and valid
        and can_inline_id(model.stem)
        and _front_is_only_id(current_front, goal_front, current_data, goal)
    )
    if inline_new:
        # The canonical render writes a lone `id` inline, and writes no frontmatter.
        inline_id = str(goal_id)

    def body_edits(text: str, layout: _Layout) -> list[_Edit]:
        if force_body:
            return [_body_edit(text, layout, model, inline_id)]
        span = _inline_span(text, layout)
        if inline_new:
            body = text[layout.body_start :]
            at = layout.body_start + len(body) - len(body.lstrip(_WS))
            return [_Edit(at, at, f"[{goal_id}] ")]
        if span is None or not id_changed:
            return []
        start, end, slug_start, slug_end = span
        if valid:
            return [_Edit(slug_start, slug_end, str(goal_id), required=True)]
        return [_Edit(start, end, "", required=True)]

    if inline_new:
        return _prune_apply(src, body_edits(src, original), goal)
    if virtual:
        at = original.body_start
        eol = original.eol
        text = src[:at] + f"---{eol}---{eol}{eol}" + src[at:]
        layout = _layout(text)
        try:
            front = _Front(text, layout)
        except (ValueError, yaml.YAMLError):
            return None
        node = front.node
    else:
        text, layout = src, original
    assert front is not None
    front.diff_comment(current_data.get("comment"), goal.get("comment"))
    front.diff_root(node, current_front, goal_front)
    edits = front.edits + body_edits(text, layout)

    kept = _prune(text, edits, goal)
    if kept is None:
        return None
    if virtual and all(edit.start >= layout.body_start for edit in kept):
        # No key to write: the source gets no frontmatter.
        plain = _prune(src, body_edits(src, original), goal)
        if plain is not None:
            return _apply(src, plain)
    return _apply(text, kept)


def _prune_apply(text: str, edits: list[_Edit], goal: dict[str, Any]) -> str | None:
    kept = _prune(text, edits, goal)
    return None if kept is None else _apply(text, kept)


def _body_edit(
    text: str, layout: _Layout, model: Question, inline_id: str | None
) -> _Edit:
    """
    The edit that replaces the body of `text` by the canonical render of
    `model`. The whitespace between the frontmatter and the body stays as the
    source has it, and so does the line break at the end. `inline_id`, when
    set, is written as an inline `[id]`.
    """
    rest = text[layout.body_start :]
    lead = rest[: len(rest) - len(rest.lstrip(_WS))] if rest.strip(_WS) else ""
    body = _body_text(model, inline_id)
    if layout.body_eol != "\n":
        body = body.replace("\n", layout.body_eol)
    ending = _EOL_RE.search(rest, max(len(rest) - 2, 0))
    tail = ending.group() if ending else ""
    body = body.rstrip("\r\n")
    return _Edit(layout.body_start, len(text), lead + body + tail)


def _body_text(model: Question, inline_id: str | None) -> str:
    """The canonical render of `model` without its frontmatter and `id`."""
    plain = model.model_copy(update={"id": None, "comment": None})
    text = plain.render()
    layout = _layout(text)
    if layout.fm_start is not None:
        text = text[layout.body_start :]
    text = text.lstrip("\r\n")
    return f"[{inline_id}] {text}" if inline_id else text


def _inline_match(text: str, layout: _Layout) -> re.Match[str] | None:
    """The inline `[id]` at the start of the body, matched in the body slice."""
    body = text[layout.body_start :]
    return SLUG_PREFIX_RE.match(body.lstrip(_WS))


def _inline_span(text: str, layout: _Layout) -> tuple[int, int, int, int] | None:
    """
    Offsets in `text` of the inline `[id]`: the start and the end of the
    prefix, and the start and the end of the slug.
    """
    match = _inline_match(text, layout)
    if match is None:
        return None
    body = text[layout.body_start :]
    shift = layout.body_start + len(body) - len(body.lstrip(_WS))
    return (
        shift,
        shift + match.end(),
        shift + match.start("slug"),
        shift + match.end("slug"),
    )


#
# Frontmatter edits
#


class _Front:
    """The nodes of the frontmatter, and the edits that change them."""

    def __init__(self, text: str, layout: _Layout) -> None:
        assert layout.fm_start is not None and layout.fm_end is not None
        self.text = text
        self.base = layout.fm_start
        self.end = layout.fm_end
        self.eol = layout.front_eol
        self.source = text[self.base : self.end]
        self.edits: list[_Edit] = []
        node = _parser.compose_yaml(self.source)
        if node is not None and not isinstance(node, yaml.MappingNode):
            raise ValueError("the frontmatter is not a mapping")
        self.node = node
        defs: set[str] = set()
        uses: set[str] = set()
        if node is not None:
            self._names(node, defs, uses, set())
        #: Whether the frontmatter has an anchor or an alias.
        self.anchored = bool(defs or uses)

    # Anchors and aliases.

    def _names(
        self, node: yaml.Node, defs: set[str], uses: set[str], seen: set[int]
    ) -> None:
        """Collect the anchors defined, and the aliases used, below `node`."""
        if id(node) in seen:
            return
        seen.add(id(node))
        mark = self._abs(node.start_mark)
        sigil = self.text[mark : mark + 1]
        found = _ANCHOR_RE.match(self.text, mark) if sigil in ("&", "*") else None
        if found is not None:
            (defs if sigil == "&" else uses).add(found.group(1))
        if sigil == "*":
            return
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                self._names(key, defs, uses, seen)
                self._names(value, defs, uses, seen)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                self._names(item, defs, uses, seen)

    # Positions: absolute offsets in `self.text`.

    def _abs(self, mark: yaml.Mark) -> int:
        return self.base + mark.index

    def content_end(self, node: yaml.Node) -> int:
        """Offset after the last character of content of `node`."""
        if isinstance(node, yaml.MappingNode) and node.value and not node.flow_style:
            key, value = node.value[-1]
            end = max(self.content_end(key), self.content_end(value))
        elif isinstance(node, yaml.SequenceNode) and node.value and not node.flow_style:
            end = self.content_end(node.value[-1])
        else:
            end = max(self._abs(node.start_mark), self._abs(node.end_mark))
        return len(self.text[:end].rstrip())

    def line_end(self, offset: int) -> int:
        """Offset after the line break that ends the line of `offset`."""
        found = _EOL_RE.search(self.text, offset)
        return len(self.text) if found is None else found.end()

    def line_start(self, offset: int) -> int:
        return (
            max(self.text.rfind("\n", 0, offset), self.text.rfind("\r", 0, offset)) + 1
        )

    # Text of values.

    def pair_text(self, key: str, value: Any, column: int) -> str:
        """`key: value` as YAML lines, the first one without indentation."""
        dump = _parser.dump_yaml({key: value}, sort_keys=False).rstrip("\n")
        lines = dump.split("\n")
        pad = " " * column
        text = lines[0] + "".join("\n" + pad + line for line in lines[1:])
        return text.replace("\n", self.eol)

    def scalar_text(self, value: Any, column: int) -> str:
        text = self.pair_text("k", value, column)
        return text[len("k: ") :]

    def insertion(self, key: str, value: Any, column: int) -> str:
        return " " * column + self.pair_text(key, value, column) + self.eol

    # Edits.

    def _removal(self, key_node: yaml.Node, value_node: yaml.Node) -> _Edit:
        start = self.line_start(self._abs(key_node.start_mark))
        end = self.line_end(self.content_end(value_node))
        return _Edit(start, end, "")

    def _alt(self, key_node: yaml.Node, value_node: yaml.Node) -> _Edit | None:
        """The removal of a pair to try instead of a new value. `id` stays put."""
        if str(key_node.value) == "id":
            return None
        return self._removal(key_node, value_node)

    def remove(self, key_node: yaml.Node, value_node: yaml.Node) -> None:
        self.edits.append(self._removal(key_node, value_node))

    def replace_pair(
        self, key_node: yaml.Node, value_node: yaml.Node, goal: Any
    ) -> None:
        """Write the whole pair again, with `goal` as its value."""
        start = self._abs(key_node.start_mark)
        end = max(self.content_end(value_node), self.content_end(key_node))
        text = self.pair_text(str(key_node.value), goal, key_node.start_mark.column)
        self.edits.append(_Edit(start, end, text, alt=self._alt(key_node, value_node)))

    def diff_value(
        self, key_node: yaml.Node, value_node: yaml.Node, current: Any, goal: Any
    ) -> None:
        """Edit the value of one pair so that it reads as `goal`."""
        if current == goal:
            return
        column = key_node.start_mark.column
        if (
            isinstance(value_node, yaml.MappingNode)
            and not value_node.flow_style
            and value_node.value
            and isinstance(current, dict)
            and isinstance(goal, dict)
            and goal
        ):
            before = len(self.edits)
            if self.diff_map(value_node, current, goal):
                # Every entry goes: drop the key, not just its entries.
                del self.edits[before:]
                self.remove(key_node, value_node)
            return
        scalar_old = isinstance(
            value_node, yaml.ScalarNode
        ) and value_node.style not in ("|", ">")
        if scalar_old and not isinstance(goal, dict | list):
            start = self._abs(value_node.start_mark)
            end = self._abs(value_node.end_mark)
            text = self.scalar_text(goal, column)
            if start == end:
                # An empty value: `key:`.
                start = end = self.content_end(key_node) + 1
                text = " " + text
            self.edits.append(
                _Edit(start, end, text, alt=self._alt(key_node, value_node))
            )
            return
        self.replace_pair(key_node, value_node, goal)

    def diff_root(
        self,
        node: yaml.MappingNode | None,
        current: dict[str, Any],
        goal: dict[str, Any],
    ) -> None:
        """
        Edit the top mapping. With anchors and aliases, a node of the tree
        may stand for text elsewhere, so a pair that changes is written again
        as a whole, together with the pairs that share an anchor with it.
        """
        if node is None or not self.anchored:
            self.diff_map(node, current, goal)
            return
        pairs = []
        for key_node, value_node in node.value:
            defs: set[str] = set()
            uses: set[str] = set()
            self._names(value_node, defs, uses, set())
            key = str(key_node.value)
            changed = (key in goal and current.get(key) != goal[key]) or (
                key not in goal and key in current
            )
            pairs.append([key, key_node, value_node, defs, uses, changed])
        grew = True
        while grew:
            grew = False
            hot_defs = set().union(*(p[3] for p in pairs if p[5]))
            hot_uses = set().union(*(p[4] for p in pairs if p[5]))
            for pair in pairs:
                if not pair[5] and (pair[4] & hot_defs or pair[3] & hot_uses):
                    pair[5] = True
                    grew = True
        for key, key_node, value_node, _defs, _uses, changed in pairs:
            if not changed:
                continue
            if key in goal:
                self.replace_pair(key_node, value_node, goal[key])
            elif key in current:
                self.remove(key_node, value_node)
        self._append_added(node, current, goal, {str(k.value) for k, _ in node.value})

    def diff_map(
        self,
        node: yaml.MappingNode | None,
        current: dict[str, Any],
        goal: dict[str, Any],
    ) -> bool:
        """
        Edit a mapping so that it reads as `goal`. Keys keep their order.
        Return whether every entry of the mapping goes, and nothing is added.
        """
        present: dict[str, tuple[yaml.Node, yaml.Node]] = {}
        if node is not None:
            for key_node, value_node in node.value:
                present[str(key_node.value)] = (key_node, value_node)
        stays = False
        for key, (key_node, value_node) in present.items():
            if key not in goal:
                if key in current:
                    self.remove(key_node, value_node)
                else:
                    stays = True
            else:
                stays = True
                self.diff_value(key_node, value_node, current.get(key), goal[key])
        added = self._append_added(node, current, goal, set(present))
        return bool(present) and not stays and not added

    def _append_added(
        self,
        node: yaml.MappingNode | None,
        current: dict[str, Any],
        goal: dict[str, Any],
        present: set[str],
    ) -> bool:
        """Add the keys of `goal` that the mapping lacks. Report if any."""
        added = [k for k in goal if k not in present and current.get(k) != goal[k]]
        if not added:
            return False
        if node is not None and node.value:
            column = node.value[0][0].start_mark.column
            at = self.line_end(self.content_end(node))
        else:
            column = 0
            at = self.end
        self.edits.append(
            _Edit(at, at, "".join(self.insertion(k, goal[k], column) for k in added))
        )
        return True

    def diff_comment(self, current: str | None, goal: str | None) -> None:
        """Rewrite the leading `#` lines, only when the comment changed."""
        if current == goal:
            return
        lines = split_lines(self.source, keepends=True)
        i = 0
        offset = 0
        while i < len(lines) and lines[i].strip(" \t\r\n") == "":
            offset += len(lines[i])
            i += 1
        first = offset
        while i < len(lines) and lines[i].startswith("#"):
            offset += len(lines[i])
            i += 1
        new = (
            "".join(f"# {line}{self.eol}" for line in goal.split("\n")) if goal else ""
        )
        self.edits.append(_Edit(self.base + first, self.base + offset, new))


def _scalar_front_value(node: yaml.MappingNode | None, key: str) -> str | None:
    """The text of a scalar value of the frontmatter, or `None`."""
    if node is None:
        return None
    for key_node, value_node in node.value:
        if str(key_node.value) == key and isinstance(value_node, yaml.ScalarNode):
            return str(value_node.value)
    return None


def _front_is_only_id(
    current_front: dict[str, Any],
    goal_front: dict[str, Any],
    current_data: dict[str, Any],
    goal: dict[str, Any],
) -> bool:
    """Whether the frontmatter would hold the `id` alone."""
    return {k: v for k, v in goal_front.items() if k != "id"} == {
        k: v for k, v in current_front.items() if k != "id"
    } and current_data.get("comment") == goal.get("comment")


def _prune(text: str, edits: list[_Edit], goal: dict[str, Any]) -> list[_Edit] | None:
    """
    Drop each edit that the parse does not need, and swap an edit for its
    `alt` when that is enough. The edits left give `goal`, or this is `None`.
    """
    kept = list(edits)
    if not _same(_apply(text, kept), goal):
        return None
    for edit in edits:
        if edit.required:
            continue
        trial = [e for e in kept if e is not edit]
        if _same(_apply(text, trial), goal):
            kept = trial
        elif edit.alt is not None:
            trial = [edit.alt if e is edit else e for e in kept]
            if _same(_apply(text, trial), goal):
                kept = trial
    return kept
