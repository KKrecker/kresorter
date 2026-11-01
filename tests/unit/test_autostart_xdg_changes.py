"""What an XDG entry becomes when it is disabled (step 4, commit 12a1; decision 0011, item 8).

A user's own entry is replaced by ``hidden_copy`` of it: the same bytes with ``Hidden=true`` in
its ``[Desktop Entry]`` group, so enabling it again only has to put the original back. A
system entry is hidden by ``STUB`` in the user directory; ``/etc`` is never written. Both are
read back by the reader as the same entry, disabled. Pure functions: nothing is written here.
"""

from pathlib import Path

import pytest

from safeclean.autostart.entries import MAX_ENTRY_BYTES, BrokenEntryError
from safeclean.autostart.models import Scope, entry_digest
from safeclean.autostart.xdg import parse_keys, read_xdg
from safeclean.autostart.xdg_changes import STUB, hidden_copy

APP = b"[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"


def write(directory: Path, name: str, raw: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.desktop"
    path.write_bytes(raw)
    return path


# --- hidden_copy -------------------------------------------------------------------------------


def test_hidden_is_added_right_after_the_group_header() -> None:
    assert hidden_copy(APP) == (
        b"[Desktop Entry]\nHidden=true\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"
    )


@pytest.mark.parametrize(
    "line",
    [b"Hidden=false", b"Hidden = false", b"  Hidden=false  "],
    ids=["plain", "spaced", "indented"],
)
def test_hidden_false_is_replaced_in_place(line: bytes) -> None:
    raw = b"[Desktop Entry]\nType=Application\n" + line + b"\nExec=app\n"

    assert hidden_copy(raw) == b"[Desktop Entry]\nType=Application\nHidden=true\nExec=app\n"


def test_a_last_line_without_newline_stays_without_one() -> None:
    raw = b"[Desktop Entry]\nType=Application\nExec=app\nHidden=false"

    assert hidden_copy(raw) == b"[Desktop Entry]\nType=Application\nExec=app\nHidden=true"


def test_the_line_ending_of_the_header_is_kept() -> None:
    raw = b"[Desktop Entry]\r\nType=Application\r\nExec=app\r\n"

    assert hidden_copy(raw) == b"[Desktop Entry]\r\nHidden=true\r\nType=Application\r\nExec=app\r\n"


def test_comments_and_later_groups_are_untouched() -> None:
    raw = (
        b"# Hidden=false in a comment\n\n[Desktop Entry]\nType=Application\nExec=app\n"
        b"[Desktop Action quit]\nHidden=false\nExec=app --quit\n"
    )

    assert hidden_copy(raw) == (
        b"# Hidden=false in a comment\n\n[Desktop Entry]\nHidden=true\nType=Application\n"
        b"Exec=app\n[Desktop Action quit]\nHidden=false\nExec=app --quit\n"
    )


@pytest.mark.parametrize(
    "separator",
    ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"],
    ids=["vt", "ff", "fs", "gs", "rs", "nel", "line-sep", "paragraph-sep"],
)
def test_lines_are_split_as_the_reader_splits_them(separator: str) -> None:
    # str.splitlines after UTF-8, as parse_keys does; bytes.splitlines would miss this Hidden
    # line, add a second one and give a copy the reader skips as broken.
    raw = f"[Desktop Entry]\nType=Application\nExec=app{separator}Hidden=false\n".encode()

    copy = hidden_copy(raw)

    assert copy == f"[Desktop Entry]\nType=Application\nExec=app{separator}Hidden=true\n".encode()
    assert parse_keys(copy.decode()) == {"Type": "Application", "Exec": "app", "Hidden": "true"}


def test_an_entry_already_hidden_is_refused() -> None:
    with pytest.raises(ValueError, match=r"already Hidden=true"):
        hidden_copy(b"[Desktop Entry]\nHidden=true\nType=Application\nExec=app\n")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        pytest.param(b"Type=Application\nExec=app\n", r"no \[Desktop Entry\] group", id="no-group"),
        pytest.param(
            b"[Desktop Entry]\nHidden=false\nHidden=false\n", "duplicate key Hidden", id="duplicate"
        ),
        pytest.param(b"[Desktop Entry]\nHidden=maybe\n", "Hidden is not a boolean", id="not-bool"),
        pytest.param(b"[Desktop Entry]\n\xff\n", "not UTF-8", id="not-utf8"),
    ],
)
def test_a_broken_entry_is_refused(raw: bytes, message: str) -> None:
    with pytest.raises(BrokenEntryError, match=message):
        hidden_copy(raw)


def test_a_copy_the_reader_would_skip_as_too_large_is_refused() -> None:
    raw = APP + b"#" * (MAX_ENTRY_BYTES - len(APP) - 1) + b"\n"
    assert len(raw) == MAX_ENTRY_BYTES

    with pytest.raises(BrokenEntryError, match=rf"larger than {MAX_ENTRY_BYTES} bytes"):
        hidden_copy(raw)


def test_a_copy_of_exactly_the_limit_is_accepted() -> None:
    raw = APP + b"#" * (MAX_ENTRY_BYTES - len(APP) - len(b"Hidden=true\n") - 1) + b"\n"

    assert len(hidden_copy(raw)) == MAX_ENTRY_BYTES


def test_the_copy_reads_back_as_the_same_entry_disabled(tmp_path: Path) -> None:
    user = tmp_path / "home" / ".config" / "autostart"
    copy = hidden_copy(APP)
    path = write(user, "app", copy)

    (item,) = read_xdg(user, ()).items

    assert (item.location, item.scope, item.command) == (
        str(path),
        Scope.USER,
        "/usr/bin/app --tray",
    )
    assert item.enabled is False
    assert item.digest == entry_digest(copy)


# --- STUB --------------------------------------------------------------------------------------


def test_the_stub_is_only_the_group_and_hidden() -> None:
    assert STUB == b"[Desktop Entry]\nHidden=true\n"


def test_the_stub_reads_back_as_the_system_entry_disabled(tmp_path: Path) -> None:
    user = tmp_path / "home" / ".config" / "autostart"
    system = tmp_path / "etc" / "xdg" / "autostart"
    shadowed = write(system, "app", APP)
    stub = write(user, "app", STUB)

    (item,) = read_xdg(user, (system,)).items

    assert (item.location, item.shadows, item.command) == (
        str(stub),
        str(shadowed),
        "/usr/bin/app --tray",
    )
    assert item.enabled is False
