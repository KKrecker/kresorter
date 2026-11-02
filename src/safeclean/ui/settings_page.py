"""The Settings page (decision 0014, items 27, 36 and 37).

The language: a change is saved and applies the next time the window opens, as the page says.
On Windows only, the machine scope of autostart: turning it on asks first, saying what is read;
turning it off asks nothing. Each change is saved at once (``ui.settings.save``), and a change
that cannot be saved says why and leaves the setting as it was: the file is written only when
the user changes a setting. The page says when the settings file was not used. Check runs the
checks of ``safeclean llm status`` off the window's thread and shows each, in the window's
words, with how to set up what is missing; nothing else asks the local AI. The data directory's
path is shown, read only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from safeclean.llm.client import Status, status
from safeclean.llm.failure import ExplanationUnavailable, SettingRefused, Unavailable
from safeclean.llm.settings import (
    DEFAULT_ADDRESS,
    DEFAULT_MODEL,
    MODEL_VARIABLE,
    URL_VARIABLE,
    model_from,
)
from safeclean.ui.dialogs import Confirmation
from safeclean.ui.i18n import Translator
from safeclean.ui.settings import LANGUAGE_SETTINGS, Loaded, Settings, save
from safeclean.ui.tasks import Task

if TYPE_CHECKING:
    from safeclean.ui.window import Window

__all__ = ["SettingsPage", "check_lines"]

_NOT_REACHED = frozenset({Unavailable.UNREACHABLE, Unavailable.TIMEOUT})


def _label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def check_lines(translator: Translator, found: Status, env: Mapping[str, str]) -> list[str]:
    """What the checks found, line by line as ``safeclean llm status`` says it; when something
    is missing, the steps that set it up."""
    text = translator.text
    ollama, install = _ollama(translator, found)
    model, pull = _model(translator, found, env)
    lines = [text("check.ollama", state=ollama), text("check.model", state=model)]
    if found.failure is None:
        return [*lines, text("check.available")]
    steps = [text("check.install")] if install else []
    steps += [] if pull is None else [text("check.pull", model=pull)]
    steps.append(text("check.again"))
    numbered = [text("check.step", n=n, step=step) for n, step in enumerate(steps, start=1)]
    settings = text(
        "check.settings",
        url_variable=URL_VARIABLE,
        url=DEFAULT_ADDRESS.url,
        model_variable=MODEL_VARIABLE,
        model=DEFAULT_MODEL,
    )
    return [*lines, text("check.unavailable"), text("check.setup"), *numbered, settings]


def _ollama(translator: Translator, found: Status) -> tuple[str, bool]:
    """The Ollama line, and whether installing and starting Ollama is a step."""
    text = translator.text
    url = None if found.address is None else found.address.url
    match found.failure:
        case SettingRefused() as refused if refused.name == URL_VARIABLE:
            return _refused(translator, refused), False
        case SettingRefused():
            return text("check.not_checked"), False
        case ExplanationUnavailable() as failed if found.installed is None:
            key = "check.unreachable" if failed.reason in _NOT_REACHED else "check.not_ollama"
            return text(key, url=url, detail=failed.detail), True
        case _:
            return text("check.running", url=url, version=found.version), False


def _model(translator: Translator, found: Status, env: Mapping[str, str]) -> tuple[str, str | None]:
    """The model line, and the model to download when that is a step."""
    text = translator.text
    if found.installed is not None:
        if found.installed:
            return text("check.installed", model=found.model), None
        return text("check.missing", model=found.model), found.model
    try:
        model = model_from(env)  # read here too: the checks stop at a refused address
    except SettingRefused as refused:
        return _refused(translator, refused), None
    return text("check.model_not_checked", model=model), model


def _refused(translator: Translator, refused: SettingRefused) -> str:
    value = repr(refused.value)
    return translator.text("check.refused", name=refused.name, value=value, why=refused.why)


class SettingsPage(QWidget):
    def __init__(self, window: Window, loaded: Loaded) -> None:
        """``loaded``: the settings the window opened with, and whether the file was used."""
        super().__init__()
        self._window = window
        self._settings = loaded.settings
        translator = window.translator
        text = translator.text
        environment = window.environment

        heading = QLabel(text("page.settings"))
        heading.setProperty("role", "heading")
        why = loaded.unused
        self.unused = _label(
            ""
            if why is None
            else text("settings.unused", reason=translator.reason(why, loaded.detail))
        )
        self.unused.setHidden(why is None)
        language = QLabel(text("settings.language"))
        self.language = QComboBox()
        self.language.setAccessibleName(text("settings.language"))
        for setting in LANGUAGE_SETTINGS:
            self.language.addItem(text(f"settings.{setting}"))
        language.setBuddy(self.language)
        self.language_note = _label(text("settings.language_note"))
        self.language_note.setProperty("role", "secondary")
        self.machine = QCheckBox(text("settings.machine"))
        self.machine.setHidden(environment.autostart_context().platform != "windows")
        self.machine.clicked.connect(self._machine)
        data_dir = environment.scan_context().policy.app_data_dir
        self.data_dir = _label(text("settings.data_dir", path=data_dir))
        ai = QLabel(text("settings.ai"))
        self.check_button = QPushButton(text("settings.check"))
        self.check_button.clicked.connect(self._check)
        self.check = _label()
        self.result = _label()
        self._show()
        self.language.currentIndexChanged.connect(self._language)

        choose = QHBoxLayout()
        choose.addWidget(language)
        choose.addWidget(self.language)
        choose.addStretch(1)
        check = QHBoxLayout()
        check.addWidget(ai)
        check.addStretch(1)
        check.addWidget(self.check_button)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(self.unused)
        layout.addLayout(choose)
        layout.addWidget(self.language_note)
        layout.addWidget(self.machine)
        layout.addLayout(check)
        layout.addWidget(self.check)
        layout.addWidget(self.data_dir)
        layout.addWidget(self.result)
        layout.addStretch(1)
        window.add_starter(self.check_button)

    @property
    def current(self) -> Settings:
        """The settings as they are remembered."""
        return self._settings

    def _show(self) -> None:
        """The controls as the settings are remembered."""
        self.language.blockSignals(True)
        self.language.setCurrentIndex(LANGUAGE_SETTINGS.index(self._settings.language))
        self.language.blockSignals(False)
        self.machine.setChecked(self._settings.include_machine)

    def _language(self, index: int) -> None:
        self._save(replace(self._settings, language=LANGUAGE_SETTINGS[index]))
        self._show()

    def _machine(self, checked: bool) -> None:
        """On after a confirmation that says what is read; off at once."""
        window, text = self._window, self._window.translator.text
        asked = Confirmation(
            title=text("settings.machine_title"),
            text=text("settings.machine_confirm"),
            details=(),
            action=text("settings.machine_action"),
        )
        if not checked or window.dialogs.confirm(asked):
            self._save(replace(self._settings, include_machine=checked))
        self._show()

    def _save(self, settings: Settings) -> None:
        translator = self._window.translator
        failed = save(self._window.environment.scan_context(), settings)
        if failed is not None:
            reason = translator.reason(failed.failure, failed.detail)
            self.result.setText(translator.text("settings.not_saved", reason=reason))
            return
        self._settings = settings
        self.unused.setHidden(True)
        self.result.setText(translator.text("settings.saved"))

    def _check(self) -> None:
        window = self._window
        environment = window.environment

        def work() -> Status:
            return status(environment.llm_env, limits=environment.llm_limits)

        def done(found: Status) -> None:
            lines = check_lines(window.translator, found, environment.llm_env)
            self.check.setText("\n".join(lines))

        window.run(Task(window.translator.text("task.check"), work, done))
