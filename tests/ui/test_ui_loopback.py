"""Every network point of the window is loopback (decision 0018, item 40).

The Check and its model list, an explanation and the grouping by meaning: every request goes
through ``llm.transport``, the one module that may open a connection (0013, item 7), to the
loopback address of 0013 item 8. An address off loopback is refused before anything is sent.
"""

from ipaddress import ip_address
from pathlib import Path
from typing import Literal

import pytest
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from kresorter.llm import client
from kresorter.llm.settings import URL_VARIABLE, Address
from kresorter.llm.transport import LIMITS, Answer, Limits, request
from kresorter.ui.window import Window
from support.files import write
from support.ollama import TAGS, VERSION, ScriptedOllama, generated
from support.window import FakeDialogs, environment, junk_tree, make_window, scanned, wait_idle

Asked = tuple[Address, str, str]


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[Asked]:
    """Every request the client hands to the transport: its address, method and path."""
    real = request
    found: list[Asked] = []

    def recording(
        address: Address,
        method: Literal["GET", "POST"],
        path: str,
        body: bytes | None = None,
        *,
        seconds: float,
        limits: Limits = LIMITS,
    ) -> Answer:
        found.append((address, method, path))
        return real(address, method, path, body, seconds=seconds, limits=limits)

    monkeypatch.setattr(client, "request", recording)
    return found


def _everything(qtbot: QtBot, window: Window, tree: dict[str, Path]) -> None:
    """The Check, an explanation, then the grouping of a folder's plan."""
    window.show_page("settings")
    wait_idle(qtbot, window)
    window.settings.check_button.click()
    wait_idle(qtbot, window)
    page = window.findings
    scanned(qtbot, window)
    page.tree.setCurrentItem(page.item(tree["m"]))
    page.explain.button.click()
    wait_idle(qtbot, window)
    window.show_page("organize")
    wait_idle(qtbot, window)
    window.organize.choose_button.click()
    wait_idle(qtbot, window)
    window.organize.group_button.click()
    wait_idle(qtbot, window)


def _window(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, url: str
) -> tuple[Window, dict[str, Path]]:
    tree = junk_tree(zone)
    folder = zone / "Downloads"
    for name in ("rome-1.jpg", "rome-2.jpg"):
        write(folder / name, name.encode())
    env = environment(tmp_path, zone, data_dir, llm_env={URL_VARIABLE: url})
    return make_window(qtbot, env, dialogs=FakeDialogs(folders=[folder])), tree


def test_every_request_goes_through_the_transport_to_loopback(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, asked: list[Asked]
) -> None:
    # [0018.40]
    grouped = generated('{"groups": [{"folder": "Rome", "files": ["rome-1.jpg", "rome-2.jpg"]}]}')
    script = (VERSION, TAGS, VERSION, TAGS, generated("Bytecode."), VERSION, TAGS, grouped)
    with ScriptedOllama(*script) as ollama:
        window, tree = _window(qtbot, tmp_path, zone, data_dir, ollama.address.url)
        _everything(qtbot, window, tree)
        seen = ollama.paths()

    assert window.findings.explain.answer.text() == "Bytecode."
    assert [card.name.text() for card in window.organize.cards] == ["Rome"]
    assert [(method, path) for _, method, path in asked] == seen
    assert len(seen) == len(script)
    assert all(ip_address(address.host).is_loopback for address, _, _ in asked)


@pytest.mark.parametrize("url", ["http://192.0.2.1:11434", "http://example.com:11434"])
def test_an_address_off_loopback_asks_nothing(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, asked: list[Asked], url: str
) -> None:
    # [0018.40] Refused as a setting (0013 item 8): the Check says so, the rest says why not.
    window, tree = _window(qtbot, tmp_path, zone, data_dir, url)
    _everything(qtbot, window, tree)
    assert asked == []
    assert any(url in label.text() for label in window.settings.findChildren(QLabel))
    assert window.organize.grouped.text().startswith("Not grouped: ")
    assert window.findings.explain.answer.text() == ""
