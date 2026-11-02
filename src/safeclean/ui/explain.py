"""Explain (local AI), under the detail of one result (decision 0014, item 26).

The detail of a finding, an autostart entry and a file organize leaves in place shows the button
while that result is shown. Pressed, it asks for the one subject of that result (``llm.subjects``,
0013 item 17) through ``llm.explain``, off the window's thread, and shows the answer under a
label that names the model and says it may be wrong, or why there is none (0013 item 23), in the
window's words. Nothing is asked without the button and nothing is kept: another result clears
the answer, and an answer that comes for a result no longer shown is dropped. An answer changes
no level, selection, plan or action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from safeclean.llm.explain import Explanations, explain
from safeclean.llm.subjects import Result, subjects
from safeclean.ui.i18n import Translator
from safeclean.ui.parts import Note, button, hbox, vbox
from safeclean.ui.tasks import Task

if TYPE_CHECKING:
    from safeclean.ui.window import Window

__all__ = ["ExplainPanel", "answer"]


def answer(translator: Translator, explained: Explanations) -> str:
    """The answer under its label, or why there is none."""
    failed = explained.unavailable
    if explained.explained or failed is None:  # one subject: an answer, or why there is none
        text = "\n".join(one.text for one in explained.explained)
        return translator.text("explain.answer", model=explained.model, answer=text)
    reason = translator.reason(failed.reason, failed.detail)
    return translator.text("explain.none", reason=reason)


class ExplainPanel(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._result: Result | None = None
        self.button = button(window.look, window.translator.text("explain.button"), icon="sparkles")
        self.button.clicked.connect(self._ask)
        self.answer = Note(self)
        line = hbox()
        line.addWidget(self.button)
        line.addStretch(1)
        layout = vbox(self, spacing=8)
        layout.addLayout(line)
        layout.addWidget(self.answer)
        window.add_starter(self.button, lambda: self._result is not None)

    def show_for(self, result: Result | None) -> None:
        """The result now shown, or none: its answer is not asked yet."""
        self._result = result
        self.answer.clear()
        self._window.update_starters()

    def _ask(self) -> None:
        window = self._window
        environment = window.environment
        asked = self._result
        about = subjects([] if asked is None else [asked])

        def work() -> Explanations:
            return explain(about, environment.llm_env, limits=environment.llm_limits)

        def done(explained: Explanations) -> None:
            if self._result is asked:
                self.answer.setText(answer(window.translator, explained))

        window.run(Task(window.translator.text("task.explain"), work, done))
