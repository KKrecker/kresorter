"""Explain (local AI), under the detail of one result (decision 0014, items 26 and 54).

The detail of a finding, an autostart entry and a file organize leaves in place shows the
explanation card while that result is shown, with the button. Pressed, it asks for the one
subject of that result (``llm.subjects``, 0013 item 17) through ``llm.explain``, off the window's
thread, and shows the answer with a note that names the model and says it may be wrong, under
the card's advisory badge, or why there is none (0013 item 23), in the window's words. The
answer is asked in the window's language (decision 0019, item 1). Nothing
is asked without the button and nothing is kept: another result clears the answer, and an answer
that comes for a result no longer shown is dropped. An answer changes no level, selection, plan
or action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame

from kresorter.llm.explain import Explanations, explain
from kresorter.llm.subjects import Result, subjects
from kresorter.ui.i18n import Translator
from kresorter.ui.parts import Icon, Label, Note, badge, button, hbox, vbox
from kresorter.ui.tasks import Task
from kresorter.ui.theme import Palette

if TYPE_CHECKING:
    from kresorter.ui.window import Window

__all__ = ["ExplainPanel", "answer"]


def answer(translator: Translator, explained: Explanations) -> tuple[str, str]:
    """The answer and the note under it, the model and that it may be wrong; or no answer and
    why there is none."""
    failed = explained.unavailable
    if explained.explained or failed is None:  # one subject: an answer, or why there is none
        text = "\n".join(one.text for one in explained.explained)
        return text, translator.text("explain.model", model=explained.model)
    reason = translator.reason(failed.reason, failed.detail)
    return "", translator.text("explain.none", reason=reason)


def _accent(palette: Palette) -> str:
    return palette.accent_text


class ExplainPanel(QFrame):
    """The explanation card (item 54), on surface: the sparkles icon, "AI explanation" in
    semibold and the ``advisory`` badge; Explain (local AI) until it is asked, then the
    ``answer`` and the ``note`` in secondary text."""

    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._result: Result | None = None
        look, text = window.look, window.translator.text
        self.setProperty("role", "card")
        self.setProperty("tone", "surface")
        self.icon = Icon(look, "sparkles", _accent)
        self.title = Label(text("explain.title"))
        self.title.setProperty("role", "strong")
        self.advisory = badge(text("explain.advisory"), "advisory")
        self.button = button(look, text("explain.button"), icon="sparkles")
        self.button.clicked.connect(self._ask)
        self.answer = Note(self)
        self.note = Note(self, role="secondary")
        head = hbox(spacing=8)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.title, 1)
        head.addWidget(self.advisory, 0, Qt.AlignmentFlag.AlignVCenter)
        layout = vbox(self, margins=(16, 16, 16, 16), spacing=8)
        layout.addLayout(head)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.answer)
        layout.addWidget(self.note)
        window.add_starter(self.button, lambda: self._result is not None)

    def show_for(self, result: Result | None) -> None:
        """The result now shown, or none: its answer is not asked yet."""
        self._result = result
        self.answer.clear()
        self.note.clear()
        self.button.show()
        self._window.update_starters()

    def _ask(self) -> None:
        window = self._window
        environment, env = window.environment, window.llm_env
        asked = self._result
        about = subjects([] if asked is None else [asked])

        language, limits = window.translator.language, environment.llm_limits

        def work() -> Explanations:
            return explain(about, env, language=language, limits=limits)

        def done(explained: Explanations) -> None:
            if self._result is asked:
                said, note = answer(window.translator, explained)
                self.button.hide()
                self.answer.setText(said)
                self.note.setText(note)

        window.run(Task(window.translator.text("task.explain"), work, done))
