"""What an XDG entry becomes when it is disabled (decision 0011, items 8 and 63). Pure.

A user's own entry is replaced by ``hidden_copy`` of it: the original bytes with
``Hidden=true`` in the ``[Desktop Entry]`` group, so enabling it again only has to put the
original back. A system entry is hidden by ``STUB`` in the user directory; ``/etc`` is never
written. Nothing is written here.
"""

from __future__ import annotations

from safeclean.autostart.entries import MAX_ENTRY_BYTES, BrokenEntryError, decode
from safeclean.autostart.xdg import GROUP, parse_keys

STUB = b"[Desktop Entry]\nHidden=true\n"
_HIDDEN = "Hidden=true"


def hidden_copy(raw: bytes) -> bytes:
    """``raw`` with ``Hidden=true`` in its ``[Desktop Entry]`` group; every other byte kept.

    An existing ``Hidden`` line is replaced in place, keeping its line ending; else one is
    added right after the group header, with the header's. The text is split into lines
    exactly as ``parse_keys`` splits it, so the copy reads back with the same keys.
    """
    keys = parse_keys(decode(raw))
    if keys.get("Hidden") == "true":
        raise ValueError("the entry is already Hidden=true")
    lines = decode(raw).splitlines(keepends=True)
    header = 0
    while lines[header].strip() != GROUP:  # parse_keys has found it
        header += 1
    index = header + 1
    while index < len(lines) and not lines[index].strip().startswith("["):
        if lines[index].partition("=")[0].strip() == "Hidden":
            lines[index] = _HIDDEN + _ending(lines[index])
            break
        index += 1
    else:
        newline = _ending(lines[header]) or "\n"
        lines[header] = lines[header].splitlines()[0] + newline
        lines.insert(header + 1, _HIDDEN + newline)
    copy = "".join(lines).encode("utf-8")
    if len(copy) > MAX_ENTRY_BYTES:
        raise BrokenEntryError(f"the disabled copy would be larger than {MAX_ENTRY_BYTES} bytes")
    return copy


def _ending(line: str) -> str:
    """The line break ``str.splitlines`` found at the end of ``line``, if any."""
    return line[len(line.splitlines()[0]) :]
