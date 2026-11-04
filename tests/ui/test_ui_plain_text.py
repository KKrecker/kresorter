"""Untrusted text is plain text (decision 0018, item 37).

A label that shows a name, a path, a detail of the system or a model's answer shows it as
plain text: every label of the window is a ``Label``, plain text whatever it is given. A
tooltip that Qt would take for rich text is escaped first, through ``tooltip``. A file named
``<img src=x>`` is shown as those characters: no tag is drawn and no image is looked for.
"""

import ast
import json
from pathlib import Path

import pytest
from PySide6.QtGui import Qt, QTextDocument
from PySide6.QtWidgets import QLabel, QTreeWidget, QWidget
from pytestqt.qtbot import QtBot

from kresorter.llm.settings import URL_VARIABLE
from kresorter.ui.dialogs import Confirmation, ConfirmDialog
from kresorter.ui.errors import ErrorDialog, Failure
from kresorter.ui.i18n import Translator
from kresorter.ui.parts import Label, Note, tooltip
from support.files import write
from support.host import posix_only
from support.ollama import TAGS, VERSION, ScriptedOllama, generated
from support.window import FakeDialogs, environment, junk_tree, make_window, scanned, wait_idle

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "src" / "kresorter" / "ui"
HOSTILE = ("<b>x</b>", "<img src=x>", '<a href="https://example.com">x</a>', "a &lt; b")
ANSWER = "<b>Bytecode</b> <img src=x> that Python makes again."


def shown(tip: str) -> str:
    """What Qt shows of a tooltip: rich text when it takes it for rich text, else the text."""
    document = QTextDocument()
    if Qt.mightBeRichText(tip):
        document.setHtml(tip)
    else:
        document.setPlainText(tip)
    return document.toPlainText()


def rich(widget: QWidget) -> list[str]:
    """Each label under ``widget`` that would take its text for rich text."""
    return [
        label.text()
        for label in widget.findChildren(QLabel)
        if label.textFormat() != Qt.TextFormat.PlainText
    ]


def tooltips(widget: QWidget) -> list[str]:
    """Every tooltip under ``widget``: of a widget, and of a row's column."""
    found = [child.toolTip() for child in widget.findChildren(QWidget) if child.toolTip()]
    for tree in widget.findChildren(QTreeWidget):
        rows = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
        found += [
            row.toolTip(column)
            for row in rows
            if row is not None
            for column in range(tree.columnCount())
            if row.toolTip(column)
        ]
    return found


# --- the guard: no label but a Label, no tooltip but through tooltip -----------------------------


def offences(source: str, *, defines_label: bool = False) -> list[tuple[int, str]]:
    """Each place in ``source`` that could show text as rich text: a ``QLabel`` made directly,
    a subclass of ``QLabel`` (but ``Label`` where it is defined), a tooltip not given through
    ``tooltip``, and a message box."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "QLabel":
                found.append((node.lineno, name))
            elif name == "setToolTip" and not _through_tooltip(node):
                found.append((node.lineno, "setToolTip"))
        elif isinstance(node, ast.Attribute) and node.attr in ("QMessageBox", "showText"):
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.Name) and node.id == "QMessageBox":
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.ClassDef):
            bases = [base.id if isinstance(base, ast.Name) else "" for base in node.bases]
            if "QLabel" in bases and not (defines_label and node.name == "Label"):
                found.append((node.lineno, f"class {node.name}(QLabel)"))
    return found


def _through_tooltip(call: ast.Call) -> bool:
    last = call.args[-1] if call.args else None
    return (
        isinstance(last, ast.Call) and isinstance(last.func, ast.Name) and last.func.id == "tooltip"
    )


@pytest.mark.parametrize(
    ("snippet", "offence"),
    [
        ("label = QLabel(name)", "QLabel"),
        ("label = QtWidgets.QLabel()", "QLabel"),
        ("class Title(QLabel):\n    pass", "class Title(QLabel)"),
        ("class Label(QLabel):\n    pass", "class Label(QLabel)"),
        ("button.setToolTip(path)", "setToolTip"),
        ("row.setToolTip(0, str(path))", "setToolTip"),
        ("row.setToolTip(0, html(path))", "setToolTip"),
        ("QMessageBox.warning(None, title, text)", "QMessageBox"),
        ("box = QtWidgets.QMessageBox(parent)", "QMessageBox"),
        ("QToolTip.showText(point, text)", "showText"),
    ],
)
def test_the_guard_names_each_way_to_rich_text(snippet: str, offence: str) -> None:
    # [0018.37]
    assert [name for _, name in offences(snippet)] == [offence]


def test_the_guard_lets_plain_ways_be() -> None:
    # [0018.37]
    source = (
        "class Label(QLabel):\n    pass\n"
        "class Note(Label):\n    pass\n"
        "label = Label(name)\nbutton.setToolTip(tooltip(path))\n"
        "row.setToolTip(0, tooltip(shown))\nitem.setText(0, name)\n"
    )
    assert offences(source, defines_label=True) == []


def test_no_module_of_the_window_shows_text_as_rich_text() -> None:
    # [0018.37]
    found = [
        f"{path.name}:{line}: {name}"
        for path in sorted(UI.glob("*.py"))
        for line, name in offences(
            path.read_text(encoding="utf-8"), defines_label=path.name == "parts.py"
        )
    ]
    assert found == []


# --- a label, a tooltip ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", HOSTILE)
def test_a_label_shows_its_text_as_those_characters(qtbot: QtBot, text: str) -> None:
    # [0018.37]
    parent = QWidget()
    qtbot.addWidget(parent)
    label, note = Label(text, parent), Note(parent, text)
    assert (label.text(), note.text()) == (text, text)
    assert label.textFormat() == note.textFormat() == Qt.TextFormat.PlainText
    assert isinstance(note, Label)


def test_a_label_made_empty_is_plain_text_too(qtbot: QtBot) -> None:
    # [0018.37]
    label = Label()
    qtbot.addWidget(label)
    label.setText("<b>x</b>")
    assert label.textFormat() == Qt.TextFormat.PlainText


@pytest.mark.parametrize(
    "text", [*HOSTILE, "~/<b>x</b>/a & b", "two\nlines <i>x</i>", "  <b>x</b>", "<!doctype x>"]
)
def test_a_tooltip_qt_would_take_for_rich_text_is_escaped(text: str) -> None:
    # [0018.37]
    assert shown(tooltip(text)) == text


@pytest.mark.parametrize("text", ["~/Downloads", "a & b", "Tom & Jerry <3", "x > y", ""])
def test_a_tooltip_qt_takes_for_plain_text_is_left_as_it_is(text: str) -> None:
    # [0018.37]
    assert tooltip(text) == text
    assert shown(text) == text


# --- the window -----------------------------------------------------------------------------------


def _hostile(zone: Path) -> dict[str, Path]:
    """A finding in a folder named ``<img src=x>``, one under ``<b>x</b>``, and a folder there
    to organize, its files named as tags."""
    tags = zone / "<b>x<" / "b>"
    return {
        "img": write(zone / "<img src=x>" / "Thumbs.db", b"bytecode"),
        "bold": write(tags / "ehthumbs.db", b"other bytecode!"),
        "folder": tags,
        "photo": write(tags / "<img src=x>.jpg", b"jpeg"),
        "document": write(tags / "<i>notes<.pdf", b"pdf"),
    }


@posix_only("Windows names hold no < or >")
def test_names_and_paths_are_shown_as_those_characters_everywhere(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.37]
    tree = _hostile(zone)
    dialogs = FakeDialogs(folders=[tree["folder"]])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    scanned(qtbot, window)
    page = window.findings
    page.tree.setCurrentItem(page.item(tree["img"]))
    wait_idle(qtbot, window)
    detail = page.detail
    assert detail.name.text() == "Thumbs.db"
    assert "<img src=x>" in detail.folder.text()

    window.show_page("organize")
    wait_idle(qtbot, window)
    window.organize.choose_button.click()
    wait_idle(qtbot, window)
    organize = window.organize
    assert organize.folder.text().endswith("<b>x</b>")
    names = sorted(card.names.text() for card in organize.cards)
    assert names == ["<i>notes<.pdf", "<img src=x>.jpg"]
    organize.move_button.click()
    wait_idle(qtbot, window)
    batches = [tip for tip in tooltips(organize) if "<b>x<" in shown(tip)]
    assert batches
    assert all(shown(tip).endswith("<b>x</b>") for tip in batches)

    for name in ("overview", "findings", "organize", "autostart", "quarantine", "settings"):
        window.show_page(name)
        wait_idle(qtbot, window)
        assert rich(window) == []


def test_every_label_of_the_window_is_plain_text(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.37]
    junk_tree(zone)
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    scanned(qtbot, window)
    for name in ("overview", "findings", "organize", "autostart", "quarantine", "settings"):
        window.show_page(name)
        wait_idle(qtbot, window)
        assert rich(window) == []
    assert all(shown(tip) == tip or "<" in shown(tip) for tip in tooltips(window))


def test_a_model_s_answer_is_shown_as_those_characters(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.37] The answer is cleaned of escapes (0013), not of tags: it is shown as it is.
    tree = junk_tree(zone)
    with ScriptedOllama(VERSION, TAGS, generated(ANSWER)) as ollama:
        env = environment(tmp_path, zone, data_dir, llm_env={URL_VARIABLE: ollama.address.url})
        window = make_window(qtbot, env)
        page = window.findings
        scanned(qtbot, window)
        page.tree.setCurrentItem(page.item(tree["m"]))
        page.explain.button.click()
        wait_idle(qtbot, window)

    assert page.explain.answer.text() == ANSWER
    assert page.explain.answer.textFormat() == Qt.TextFormat.PlainText
    assert rich(window) == []


def test_an_error_s_message_is_shown_as_those_characters(qtbot: QtBot) -> None:
    # [0018.37]
    parent = QWidget()
    qtbot.addWidget(parent)
    found = Failure("ValueError", "<b>x</b> <img src=x>", "Traceback ...\n")
    dialog = ErrorDialog(parent, Translator("en"), found)
    assert dialog.what.text() == "ValueError: <b>x</b> <img src=x>"
    assert rich(dialog) == []


def test_a_confirmation_s_names_are_shown_as_those_characters(qtbot: QtBot) -> None:
    # [0018.37]
    parent = QWidget()
    qtbot.addWidget(parent)
    asked = Confirmation("<b>Move</b>", "Move <img src=x>?", ("/q/<b>x</b>",), "Move")
    dialog = ConfirmDialog(parent, Translator("en"), asked)
    assert (dialog.question.text(), dialog.text.text()) == ("<b>Move</b>", "Move <img src=x>?")
    assert rich(dialog) == []
    assert json.dumps(dialog.details.toPlainText()) == json.dumps("/q/<b>x</b>")
