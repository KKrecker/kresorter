"""The README installs Kresorter (decision 0015, item 29).

Its section Install comes before the console's usage: Windows first, the installer or the
portable zip from the releases, how to pass SmartScreen and how to check ``SHA256SUMS.txt``;
then Linux, with pipx, the window and the commands or the commands only; then what each system
can do, organize on Windows and Linux and not on macOS, and how to check an installation with
the self-test. Uninstalling has its own section (item 15). No Qt is needed here.
"""

from pathlib import Path

from support.markdown import blocks, headings, section

ROOT = Path(__file__).resolve().parents[1]
RELEASES = "https://github.com/KKrecker/kresorter/releases"


def readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def install() -> list[str]:
    return section(readme(), "Install")


def part(title: str) -> list[str]:
    return section("\n".join(install()), title)


def flat(lines: list[str]) -> str:
    return " ".join(" ".join(lines).split())


def test_install_comes_before_the_console_s_usage() -> None:
    # [0015.29]
    titles = [title for level, title, _ in headings(readme()) if level == 2]
    assert titles.index("Install") < titles.index("Usage (console)")


def test_windows_first_then_linux_then_what_each_system_can_do() -> None:
    # [0015.29]
    titles = [title for level, title, _ in headings("\n".join(install())) if level == 3]
    assert titles == ["Windows", "Linux", "What each system can do"]


def test_windows_the_installer_or_the_portable_zip_from_the_releases() -> None:
    # [0015.29] the names the windows job gives them (items 13 and 14)
    text = flat(part("Windows"))
    for words in (
        f"]({RELEASES})",
        "`Kresorter-<version>-setup.exe`",
        "`Kresorter-<version>-portable.zip`",
        r"`%LOCALAPPDATA%\Programs\Kresorter`",
        "no administrator rights",
        "`Kresorter.exe`",
        "pipx",
    ):
        assert words in text, words


def test_windows_how_to_pass_smartscreen() -> None:
    # [0015.29] unsigned (an accepted limitation of 0015)
    text = flat(part("Windows"))
    for words in ("SmartScreen", "not signed", "**More info**", "**Run anyway**"):
        assert words in text, words


def test_windows_how_to_check_the_sums() -> None:
    # [0015.29] SHA256SUMS.txt of the same release (item 23)
    lines = part("Windows")
    assert "`SHA256SUMS.txt`" in flat(lines)
    (shown,) = blocks(lines, "powershell")
    assert shown == ["Get-FileHash .\\Kresorter-<version>-setup.exe -Algorithm SHA256"]


def test_linux_with_pipx_the_window_and_the_commands_or_the_commands_only() -> None:
    # [0015.29] and Qt's libraries, as the desktop app's section names them
    commands = [
        line.split("#")[0].split() for block in blocks(part("Linux"), "bash") for line in block
    ]
    assert ["pipx", "install", '"kresorter[ui]"'] in commands
    assert ["pipx", "install", "kresorter"] in commands
    assert "[Desktop app](#desktop-app-optional)" in flat(part("Linux"))


def table(lines: list[str]) -> dict[str, list[str]]:
    """The rows of the one table in ``lines``, by their first cell; the header row's too."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in lines
        if line.startswith("|") and not set(line) <= set("|-: ")
    ]
    return {row[0]: row[1:] for row in rows}


def test_organize_on_windows_and_linux_not_on_macos() -> None:
    # [0015.29] macOS has no build and no CI; everything else the commands do, it does
    rows = table(part("What each system can do"))
    assert rows[""] == ["Windows", "Linux", "macOS"]
    assert rows["Organize"] == ["yes", "yes", "no: refused"]
    assert all(len(cells) == 3 for cells in rows.values())
    assert rows["The window"][2] == "with pipx, untested"


def test_an_installation_is_checked_with_the_self_test() -> None:
    # [0015.29] the one CI runs on each build (items 17 and 22)
    text = flat(install())
    assert "`Kresorter.exe --self-test report.txt`" in text
    assert "`kresorter-ui --self-test report.txt`" in text
