"""The Settings page (decision 0014, items 27, 36, 37 and 55).

A card each, the page scrolling under its head. The language, its choice at the right: a change is
saved, then a restart is offered (decision 0018, item 3); declined, the new language applies the
next time the window opens, as its note says. The theme, on the card Appearance, its choice at the
right: a change is saved and applied at once (decision 0018, items 1 and 2). On Windows only, the
machine scope of autostart: turning it on asks first, saying what is read; turning it off asks
nothing. Each change is saved at once (``ui.settings.save``), and a change that cannot be saved says
why and leaves the setting as it was: the file is written only when the user changes a setting. The
page says when the settings file was not used. The local AI: its server, Ollama or LM Studio,
chosen here unless ``KRESORTER_LLM_SERVER`` names one (as a note says then, the choice disabled); a
change is saved, forgets the model chosen, which was the other server's, and runs Check (decision
0019, item 12). The chosen server's address and model as the environment gives them, the model
chosen here unless the server's model variable names one (as a note says then), and Check, which
runs the checks of ``kresorter llm status`` off the window's thread and shows each, in the window's
words, the server and the model each with a dot in the safe or the review colour, then how to set
up what is missing; nothing else asks the local AI. Check lists the models the server has in a
choice: one chosen is saved, and Check runs again with it (decision 0018, item 32). The card
recommends a model for the machine's memory and processors, by the server's name for it, and says
how to get it there (item 33; decision 0019, item 13). The data directory's path (from the home
folder as ``~``) is shown, read only, and under it the version (decision 0015, item 4) and the
licence: MIT, and the LGPL-3.0 of Qt and PySide6 in the Windows build (decision 0019, item 20).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLayout, QScrollArea, QWidget

from kresorter import __version__
from kresorter.llm.client import Status, status
from kresorter.llm.failure import ExplanationUnavailable, SettingRefused, Unavailable
from kresorter.llm.machine import Machine, recommended
from kresorter.llm.settings import (
    SERVER_NAMES,
    SERVER_VARIABLE,
    SERVERS,
    Server,
    installed,
    is_model_name,
    model_from,
    server_in,
    variables,
    with_model,
    with_server,
)
from kresorter.ui.dialogs import Confirmation
from kresorter.ui.i18n import Translator
from kresorter.ui.parts import (
    CheckBox,
    Choice,
    Head,
    Label,
    Note,
    button,
    card,
    dot,
    hbox,
    mark,
    tooltip,
    vbox,
)
from kresorter.ui.settings import LANGUAGE_SETTINGS, THEME_SETTINGS, Loaded, Settings, save
from kresorter.ui.shown import shown_path
from kresorter.ui.tasks import Task

if TYPE_CHECKING:
    from kresorter.ui.window import Window

__all__ = ["Found", "SettingsPage", "check_lines"]

_NOT_REACHED = frozenset({Unavailable.UNREACHABLE, Unavailable.TIMEOUT})
_INSTALL: dict[Server, str] = {"ollama": "check.install", "lmstudio": "check.install_lmstudio"}
_DOWNLOAD: dict[Server, str] = {"ollama": "check.pull", "lmstudio": "check.download_lmstudio"}
# The model's line when the server has it, and when it has not.
_FOUND: dict[Server, tuple[str, str]] = {
    "ollama": ("check.installed", "check.missing"),
    "lmstudio": ("check.listed", "check.not_listed"),
}
_RECOMMENDED: dict[Server, str] = {
    "ollama": "settings.recommended",
    "lmstudio": "settings.recommended_lmstudio",
}


def check_lines(translator: Translator, found: Status, env: Mapping[str, str]) -> list[str]:
    """What the checks found, line by line as ``kresorter llm status`` says it; when something
    is missing, the steps that set it up, the server's (decision 0019, item 12)."""
    text = translator.text
    server = found.server
    running, install = _server_line(translator, found)
    model, download = _model_line(translator, found, env)
    refused = isinstance(found.failure, SettingRefused) and found.failure.name == SERVER_VARIABLE
    name = text("settings.ai") if refused else SERVER_NAMES[server]
    lines = [text("check.server", server=name, state=running), text("check.model", state=model)]
    if found.failure is None:
        return [*lines, text("check.available")]
    none_listed = found.installed is False and found.model is None  # LM Studio lists none
    steps = [text(_INSTALL[server])] if install or none_listed else []
    steps += [] if download is None else [text(_DOWNLOAD[server], model=download)]
    steps.append(text("check.again"))
    numbered = [text("check.step", n=n, step=step) for n, step in enumerate(steps, start=1)]
    named = variables(server)
    settings = text(
        "check.settings",
        server_variable=SERVER_VARIABLE,
        url_variable=named.url,
        url=named.address.url,
        model_variable=named.model,
        model=named.default_model or text("settings.first_model"),
    )
    return [*lines, text("check.unavailable"), text("check.setup"), *numbered, settings]


def _server_line(translator: Translator, found: Status) -> tuple[str, bool]:
    """The server's line, and whether installing and starting the server is a step."""
    text = translator.text
    url = None if found.address is None else found.address.url
    match found.failure:
        case SettingRefused() as refused if refused.name in (
            SERVER_VARIABLE,
            variables(found.server).url,
        ):
            return _refused(translator, refused), False
        case SettingRefused():
            return text("check.not_checked"), False
        case ExplanationUnavailable() as failed if found.installed is None:
            if failed.reason in _NOT_REACHED:
                return text("check.unreachable", url=url, detail=failed.detail), True
            server = SERVER_NAMES[found.server]
            return text("check.not_server", url=url, server=server, detail=failed.detail), True
        case _ if found.version is None:
            return text("check.running_unversioned", url=url), False  # LM Studio says none
        case _:
            return text("check.running", url=url, version=found.version), False


def _model_line(
    translator: Translator, found: Status, env: Mapping[str, str]
) -> tuple[str, str | None]:
    """The model line, and the model to download when that is a step."""
    text = translator.text
    has, has_not = _FOUND[found.server]
    if found.installed is not None:
        if found.installed:
            return text(has, model=found.model), None
        if found.model is None:
            return text("check.none_listed"), None
        return text(has_not, model=found.model), found.model
    try:
        model = model_from(env)  # read here too: the checks stop at a refused address
    except SettingRefused as refused:
        if refused.name == SERVER_VARIABLE:
            return text("check.not_checked"), None
        return _refused(translator, refused), None
    if model is None:  # LM Studio's first model, which only a check finds
        return text("check.not_checked"), None
    return text("check.model_not_checked", model=model), model


def _in_use(server: Server, model: str | None, name: str) -> bool:
    """Whether ``name``, as the server lists it, is ``model``: LM Studio's exactly (decision
    0019, item 7)."""
    if model is None:
        return False
    return name == model if server == "lmstudio" else installed(model, (name,))


def _refused(translator: Translator, refused: SettingRefused) -> str:
    value = repr(refused.value)
    return translator.text("check.refused", name=refused.name, value=value, why=refused.why)


class Found(QWidget):
    """A line of what a check found, with a dot: safe when it passed, review when it did not."""

    def __init__(self) -> None:
        super().__init__()
        self.dot = dot("none")
        self.line = Note(self)
        beside = vbox(margins=(0, 8, 0, 0))  # the dot at the middle of the first line
        beside.addWidget(self.dot)
        beside.addStretch(1)
        layout = hbox(self, spacing=8)
        layout.addLayout(beside)
        layout.addWidget(self.line, 1)
        self.hide()  # until a check ran

    def text(self) -> str:
        return self.line.text()

    def show_found(self, line: str, *, passed: bool) -> None:
        self.line.setText(line)
        mark(self.dot, "safe" if passed else "review")
        self.show()


class SettingsPage(QWidget):
    def __init__(self, window: Window, loaded: Loaded) -> None:
        """``loaded``: the settings the window opened with, and whether the file was used."""
        super().__init__()
        self._window = window
        self._settings = loaded.settings
        translator = window.translator
        text = translator.text
        environment = window.environment

        look = window.look
        self.controls = QWidget()
        why = loaded.unused
        self.unused = Note(
            self.controls,
            ""
            if why is None
            else text("settings.unused", reason=translator.reason(why, loaded.detail)),
        )
        self.language_card, language_inside = card()
        language = _title(text("settings.language"))
        self.language = Choice(look)
        self.language.setAccessibleName(text("settings.language"))
        for setting in LANGUAGE_SETTINGS:
            self.language.addItem(text(f"settings.{setting}"))
        language.setBuddy(self.language)
        self.language_note = Note(self, text("settings.language_note"), role="secondary")
        self.appearance_card, appearance_inside = card()
        appearance = _title(text("settings.appearance"))
        self.theme = Choice(look)
        self.theme.setAccessibleName(text("settings.appearance"))
        for theme in THEME_SETTINGS:
            self.theme.addItem(text(f"settings.theme_{theme}"))
        appearance.setBuddy(self.theme)
        self.machine_card, machine_inside = card()
        self.machine_card.setHidden(environment.autostart_context().platform != "windows")
        self.machine = CheckBox(look, text("settings.machine"))
        self.machine.setHidden(self.machine_card.isHidden())
        self.machine.clicked.connect(self._machine)
        self.ai_card, ai_inside = card()
        env = environment.llm_env
        self._found_machine = environment.machine()
        self.server_title = Label(text("settings.server"))  # a field's label, as the model's
        self.server = Choice(look)
        self.server.setAccessibleName(text("settings.server"))
        self.server.addItems([SERVER_NAMES[server] for server in SERVERS])
        self.server_title.setBuddy(self.server)
        named = env.get(SERVER_VARIABLE)
        overridden = text("settings.server_env", variable=SERVER_VARIABLE, server=named)
        self.server_note = Note(self, "" if named is None else overridden, role="secondary")
        self.address = Note(self, role="secondary")
        self.model_title = Label(text("settings.model"))  # a field's label, not a card's title
        self.model = Choice(look)
        self.model.setAccessibleName(text("settings.model"))
        self.model_title.setBuddy(self.model)
        self.model_note = Note(self, role="secondary")  # the server's model variable, when set
        self.recommended = Note(self, role="secondary")  # for the server chosen
        self.check_button = button(look, text("settings.check"))
        self.check_button.clicked.connect(self._check)
        self.found = (Found(), Found())  # the server, then the model
        self.check = Note(self)
        self.data_card, data_inside = card()
        data_dir = environment.scan_context().policy.app_data_dir
        self.data_dir = Note(self, shown_path(Path(data_dir), Path.home()), role="secondary")
        self.data_dir.setToolTip(tooltip(str(data_dir)))
        self.version = Note(self, text("settings.version", version=__version__), role="secondary")
        self.licence = Note(self, text("settings.licence"), role="secondary")
        self.result = Note(self.controls)
        self._show()
        self.language.currentIndexChanged.connect(self._language)
        self.theme.currentIndexChanged.connect(self._theme)
        self.server.currentIndexChanged.connect(self._server)
        self._list(())
        self.model.currentIndexChanged.connect(self._model)

        language_inside.addLayout(_titled(language, self.language))
        language_inside.addWidget(self.language_note)
        appearance_inside.addLayout(_titled(appearance, self.theme))
        machine_inside.addWidget(_title(text("page.autostart")))
        machine_inside.addWidget(self.machine)
        ai_inside.addLayout(_titled(_title(text("settings.ai")), self.check_button))
        ai_inside.addLayout(_titled(self.server_title, self.server))
        ai_inside.addWidget(self.server_note)
        ai_inside.addWidget(self.address)
        ai_inside.addWidget(self.model_note)
        ai_inside.addLayout(_titled(self.model_title, self.model))
        ai_inside.addWidget(self.recommended)
        for found in self.found:
            ai_inside.addWidget(found)
        ai_inside.addWidget(self.check)
        data_inside.addWidget(_title(text("settings.data_dir")))
        data_inside.addWidget(self.data_dir)
        data_inside.addWidget(self.version)
        data_inside.addWidget(self.licence)
        inside = vbox(self.controls, margins=(32, 16, 32, 32), spacing=16)
        for part in (
            self.unused,
            self.language_card,
            self.appearance_card,
            self.machine_card,
            self.ai_card,
            self.data_card,
            self.result,
        ):
            inside.addWidget(part)
        inside.addStretch(1)
        self.area = QScrollArea()
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setWidgetResizable(True)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area.setWidget(self.controls)
        self.controls.setAutoFillBackground(False)  # setWidget fills it: the page shows through
        self.area.viewport().setAutoFillBackground(False)

        self.head = Head(text("page.settings"), text("head.settings"))
        top = vbox(margins=(32, 32, 32, 0), spacing=0)
        top.addWidget(self.head)
        layout = vbox(self, spacing=0)
        layout.addLayout(top)
        layout.addWidget(self.area, 1)
        window.add_starter(self.check_button)
        window.add_starter(self.server, lambda: SERVER_VARIABLE not in env)
        window.add_starter(self.model, lambda: variables(server_in(self.llm_env)).model not in env)

    @property
    def current(self) -> Settings:
        """The settings as they are remembered."""
        return self._settings

    @property
    def llm_env(self) -> Mapping[str, str]:
        """The local AI's settings: the environment's, with the server chosen here unless it
        names one (decision 0019, item 12), and the model chosen here, which is that server's,
        unless the environment names one or another server (decision 0018, item 32)."""
        env = with_server(self._window.environment.llm_env, self._settings.server)
        chosen = env[SERVER_VARIABLE] == self._settings.server
        return with_model(env, self._settings.model if chosen else None)

    def _show(self) -> None:
        """The controls as the settings are remembered, the server's address, model and
        recommendation among them."""
        translator, env = self._window.translator, self.llm_env
        text = translator.text
        server = server_in(env)
        named = variables(server)
        model = env.get(named.model, named.default_model)
        url = env.get(named.url, named.address.url)
        shown = text("settings.first_model") if model is None else model
        self.address.setText(text("settings.address", url=url, model=shown))
        given = self._window.environment.llm_env.get(named.model)
        overridden = text("settings.model_env", variable=named.model, model=given)
        self.model_note.setText("" if given is None else overridden)
        self.recommended.setText(_recommendation(translator, self._found_machine, server))
        names = [self.model.itemText(index) for index in range(self.model.count())]
        in_use = next((n for n, name in enumerate(names) if _in_use(server, model, name)), -1)
        for choice, index in (
            (self.language, LANGUAGE_SETTINGS.index(self._settings.language)),
            (self.theme, THEME_SETTINGS.index(self._settings.theme)),
            (self.server, SERVERS.index(server)),
            (self.model, in_use),
        ):
            choice.blockSignals(True)
            choice.setCurrentIndex(index)
            choice.blockSignals(False)
        self.machine.setChecked(self._settings.include_machine)

    def _language(self, index: int) -> None:
        """Saved, then a restart offered (decision 0018, item 3); declined, the new language
        applies the next time the window opens."""
        language = LANGUAGE_SETTINGS[index]
        self._save(replace(self._settings, language=language))
        self._show()
        if self._settings.language == language:
            self._offer_restart()

    def _offer_restart(self) -> None:
        window, text = self._window, self._window.translator.text
        asked = Confirmation(
            title=text("settings.restart_title"),
            text=text("settings.restart_text"),
            details=(),
            action=text("settings.restart_action"),
        )
        if window.dialogs.confirm(asked):
            window.restart()

    def _theme(self, index: int) -> None:
        """Saved, then applied at once; a theme that cannot be saved is not applied."""
        self._save(replace(self._settings, theme=THEME_SETTINGS[index]))
        self._window.look.choose(self._settings.theme)
        self._show()

    def _server(self, index: int) -> None:
        """Saved, the model chosen forgotten (it was the other server's), then checked; a server
        that cannot be saved is not used."""
        server = SERVERS[index]
        self._save(replace(self._settings, server=server, model=None))
        self._show()
        if self._settings.server == server:
            self._list(())  # the other server's
            self._window.show_ai(None)
            self._check()

    def _model(self, index: int) -> None:
        """Saved, then checked again; a model that cannot be saved is not used."""
        model = self.model.itemText(index)
        self._save(replace(self._settings, model=model))
        self._show()
        if self._settings.model == model:
            self._window.show_ai(None)
            self._check()

    def _list(self, models: tuple[str, ...]) -> None:
        """The models the server listed, those a model may be named; none, no choice."""
        names = [name for name in models if is_model_name(name)]
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(names)
        self.model.blockSignals(False)
        self.model.setHidden(not names)
        self.model_title.setHidden(not names)
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

    def remember(self, settings: Settings) -> str | None:
        """Save ``settings``, then they are the ones remembered; when they cannot be saved,
        why, in the window's words, and nothing changes."""
        translator = self._window.translator
        failed = save(self._window.environment.scan_context(), settings)
        if failed is not None:
            reason = translator.reason(failed.failure, failed.detail)
            return translator.text("settings.not_saved", reason=reason)
        self._settings = settings
        self.unused.clear()
        return None

    def _save(self, settings: Settings) -> None:
        refused = self.remember(settings)
        self.result.setText(refused or self._window.translator.text("settings.saved"))

    def _check(self) -> None:
        window = self._window
        env, limits = self.llm_env, window.environment.llm_limits

        def work() -> Status:
            return status(env, limits=limits)

        def done(found: Status) -> None:
            server, model, *rest = check_lines(window.translator, found, env)
            self.found[0].show_found(server, passed=found.running)
            self.found[1].show_found(model, passed=found.installed is True)
            self.check.setText("\n".join(rest))
            self._list(found.models)
            window.show_ai(found.failure is None)

        window.run(Task(window.translator.text("task.check"), work, done))


def _recommendation(translator: Translator, machine: Machine, server: Server) -> str:
    """The model recommended for ``machine``, what that comes from, and how to get it from
    ``server``."""
    text = translator.text
    memory = (
        text("settings.memory_unknown")
        if machine.memory is None
        else text("settings.memory", size=translator.size(machine.memory))
    )
    processors = (
        text("settings.processors_unknown")
        if machine.processors is None
        else translator.count("processor", machine.processors)
    )
    model = recommended(machine, server)
    return text(_RECOMMENDED[server], memory=memory, processors=processors, model=model)


def _title(text: str) -> Label:
    """A card's title, in semibold."""
    title = Label(text)
    title.setProperty("role", "card-title")
    return title


def _titled(title: Label, control: QWidget) -> QLayout:
    """A card's title, and its control at the right."""
    row = hbox(spacing=12)
    row.addWidget(title)
    row.addStretch(1)
    row.addWidget(control)
    return row
