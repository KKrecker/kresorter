"""The window's motion (decision 0018, items 6-10).

A page that opens fades in over ``DURATION_MS`` (``Fade``), usable at once, the effect removed
when it ends; a switch's knob slides over the same time (``parts.Switch``); while a scan runs,
its card shows a bar that moves (``Bar``), a crossing every ``BAR_MS``. Each reads
``DURATION_MS`` when it starts: at 0 nothing moves and the end is drawn at once, as the
screenshots have it.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import (
    QAbstractAnimation,
    QObject,
    QPropertyAnimation,
    QRectF,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from kresorter.ui.theme import Look

__all__ = ["BAR_MS", "DURATION_MS", "Bar", "Fade"]

DURATION_MS = 150  # a page's fade, a switch's slide; 0: no motion at all
BAR_MS = 1200  # the scan's bar: one crossing
_SEGMENT = 0.3  # of the bar's width: the part that moves


def moving() -> bool:
    """Whether a motion that starts now moves."""
    return DURATION_MS > 0


class Fade(QObject):
    """Fades a page in, one at a time: a page that opens while another fades ends that fade."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._running: tuple[QPropertyAnimation, QGraphicsOpacityEffect] | None = None

    def fade_in(self, page: QWidget) -> None:
        self.finish()
        if not moving():
            return
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(DURATION_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.finished.connect(self.finish)
        self._running = animation, effect
        animation.start()

    def finish(self) -> None:
        """The fade that runs ends: its page as it is, without the effect."""
        if self._running is None:
            return
        animation, effect = self._running
        self._running = None
        animation.stop()
        shiboken6.delete(effect)  # which takes it off its page
        animation.deleteLater()


class Bar(QWidget):
    """A thin bar that says work goes on: while it runs, a segment in the accent crosses its
    track, again and again; with no motion, the whole bar in the accent, still. Hidden until it
    runs."""

    HEIGHT = 4

    def __init__(self, look: Look) -> None:
        super().__init__()
        self._look = look
        self.setFixedHeight(self.HEIGHT)
        self._crossing = QVariantAnimation(self)  # the segment's left edge, 0 to 1 of the way
        self._crossing.setStartValue(-_SEGMENT)
        self._crossing.setEndValue(1.0)
        self._crossing.setLoopCount(-1)
        self._crossing.valueChanged.connect(self.update)
        look.changed.connect(self.update)
        self.hide()

    def run(self) -> None:
        self.show()
        if moving():
            self._crossing.setDuration(BAR_MS)
            self._crossing.start()

    def stop(self) -> None:
        self._crossing.stop()
        self.hide()

    @property
    def is_moving(self) -> bool:
        return self._crossing.state() == QAbstractAnimation.State.Running

    def segment(self) -> QRectF:
        """The part drawn in the accent, in the bar's coordinates."""
        whole = QRectF(self.rect())
        if not self.is_moving:
            return whole
        at = float(self._crossing.currentValue())
        left = max(0.0, at) * whole.width()
        right = min(1.0, at + _SEGMENT) * whole.width()
        return QRectF(left, 0.0, right - left, whole.height())

    def paintEvent(self, event: QPaintEvent) -> None:
        palette = self._look.palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.height() / 2
        painter.setPen(QColor(palette.border))
        painter.setBrush(QColor(palette.border))
        painter.drawRoundedRect(QRectF(self.rect()), radius, radius)
        painter.setBrush(QColor(palette.accent))
        painter.setPen(QColor(palette.accent))
        painter.drawRoundedRect(self.segment(), radius, radius)
        painter.end()
