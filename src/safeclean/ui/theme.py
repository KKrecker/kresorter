"""The window's look (decision 0014, items 32-34 and 47).

The colours are the tokens of the decision's table, a light and a dark palette; the style sheet
uses no other colour. ``accent`` marks the selection and the focus, and a selected row or a chip
that is on lies on ``selection``, the likely safe badge's background (the likely safe colour is
the accent); accented text and the primary button use ``accent text``; a level's badge is its
text on its background and its dot the level's colour; ``danger`` is the purge's alone. The
parts of item 47 (cards, chips, fields, buttons, links, badges, lists, dots) have their rules
here. ``Look`` follows the colour scheme Qt reports, dark or not, and applies a change at once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from safeclean.analysis.score import Level

__all__ = [
    "DARK",
    "LIGHT",
    "Badge",
    "Look",
    "Palette",
    "contrast",
    "luminance",
    "palette_for",
    "style_sheet",
    "tint",
]


@dataclass(frozen=True)
class Badge:
    text: str
    background: str


@dataclass(frozen=True)
class Palette:
    canvas: str
    surface: str
    surface2: str
    border: str
    text: str
    secondary: str
    accent: str
    accent_text: str
    primary_text: str
    levels: Mapping[Level, str]
    badges: Mapping[Level, Badge]
    danger: str
    danger_text: str
    danger_badge: Badge

    @property
    def selection(self) -> str:
        """A selected row's and a chip's that is on: the accent's tint."""
        return self.badges[Level.LIKELY_SAFE].background

    def colours(self) -> frozenset[str]:
        badges = [*self.badges.values(), self.danger_badge]
        return frozenset(
            {
                self.canvas,
                self.surface,
                self.surface2,
                self.border,
                self.text,
                self.secondary,
                self.accent,
                self.accent_text,
                self.primary_text,
                self.danger,
                self.danger_text,
                *self.levels.values(),
                *(badge.text for badge in badges),
                *(badge.background for badge in badges),
            }
        )


LIGHT = Palette(
    canvas="#FFFFFF",
    surface="#F9F8F7",
    surface2="#F0EFED",
    border="#E6E5E3",
    text="#2C2C2B",
    secondary="#73706B",
    accent="#2783DE",
    accent_text="#1F6FC5",
    primary_text="#FFFFFF",
    levels={Level.SAFE: "#46A171", Level.LIKELY_SAFE: "#2783DE", Level.REVIEW: "#D5803B"},
    badges={
        Level.SAFE: Badge("#2F7A52", "#E8F1EC"),
        Level.LIKELY_SAFE: Badge("#1F6FBF", "#E5F2FC"),
        Level.REVIEW: Badge("#9A5418", "#FBEBDE"),
    },
    danger="#C2412F",
    danger_text="#FFFFFF",
    danger_badge=Badge("#B73A2E", "#FCE9E7"),
)

# A dark badge's text is the level's colour, on a 12 % tint of it over the canvas.
DARK = Palette(
    canvas="#191919",
    surface="#202020",
    surface2="#383836",
    border="#474747",
    text="#FFFFFF",
    secondary="#AFAFAF",
    accent="#5E9FE8",
    accent_text="#5E9FE8",
    primary_text="#191919",
    levels={Level.SAFE: "#72BC8F", Level.LIKELY_SAFE: "#5E9FE8", Level.REVIEW: "#DE9255"},
    badges={
        Level.SAFE: Badge("#72BC8F", "#242D27"),
        Level.LIKELY_SAFE: Badge("#5E9FE8", "#212932"),
        Level.REVIEW: Badge("#DE9255", "#312820"),
    },
    danger="#E97366",
    danger_text="#191919",
    danger_badge=Badge("#E97366", "#322422"),
)


def palette_for(*, dark: bool) -> Palette:
    return DARK if dark else LIGHT


def _channels(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def luminance(colour: str) -> float:
    """The relative luminance of WCAG 2 of a ``#RRGGBB`` colour."""

    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in _channels(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    """The contrast ratio of WCAG 2, from 1 to 21, whichever colour is lighter."""
    darker, lighter = sorted((luminance(first), luminance(second)))
    return (lighter + 0.05) / (darker + 0.05)


def tint(colour: str, *, over: str, amount: float) -> str:
    """``colour`` laid over ``over`` at ``amount`` (0 to 1), each channel rounded."""
    mixed = (
        round(ground + amount * (channel - ground))
        for channel, ground in zip(_channels(colour), _channels(over), strict=True)
    )
    return "#" + "".join(f"{channel:02X}" for channel in mixed)


def _rules(p: Palette) -> list[tuple[str, dict[str, str]]]:
    field = {
        "background-color": p.canvas,
        "border": f"1px solid {p.border}",
        "border-radius": "8px",
        "padding": "0px 12px",
        "min-height": "34px",
    }
    rules: list[tuple[str, dict[str, str]]] = [
        ("QMainWindow, QDialog", {"background-color": p.canvas}),
        ("QWidget", {"color": p.text, "font-size": "14px"}),
        (
            "QFrame#sidebar",
            {
                "background-color": p.surface,
                "border": "none",
                "border-right": f"1px solid {p.border}",
            },
        ),
        ("QLabel#brand", {"font-size": "16px", "font-weight": "600"}),
        ("QLabel#title", {"font-size": "24px", "font-weight": "600"}),
        ("QLabel#subtitle", {"color": p.secondary}),
        ('QLabel[role="secondary"]', {"color": p.secondary}),
        ('QLabel[role="accent"]', {"color": p.accent_text}),
        ('QLabel[role="strong"]', {"font-weight": "600"}),
        (
            'QFrame[role="card"]',
            {
                "background-color": p.canvas,
                "border": f"1px solid {p.border}",
                "border-radius": "12px",
            },
        ),
        ('QFrame[role="card"][tone="surface"]', {"background-color": p.surface}),
        ('QFrame[role="divider"]', {"background-color": p.border, "border": "none"}),
        (
            'QFrame[role="banner"]',
            {
                "background-color": p.surface2,
                "border": f"1px solid {p.border}",
                "border-radius": "8px",
                "margin": "16px 32px 0px 32px",
            },
        ),
        ("QLabel#message, QLabel#task-status", {"margin": "0px 32px 8px 32px"}),
        (
            "QAbstractItemView",
            {
                "background-color": p.canvas,
                "border": f"1px solid {p.canvas}",
                "selection-background-color": p.selection,
                "selection-color": p.text,
                "outline": "0px",
            },
        ),
        (
            "QHeaderView::section",
            {
                "background-color": p.canvas,
                "color": p.secondary,
                "border": "none",
                "border-bottom": f"1px solid {p.border}",
                "padding": "8px 12px",
                "font-size": "12px",
                "font-weight": "600",
            },
        ),
        ("QLineEdit, QComboBox", field),
        (
            "QTextBrowser, QPlainTextEdit",
            {
                "background-color": p.canvas,
                "border": f"1px solid {p.border}",
                "border-radius": "8px",
            },
        ),
        (
            "QPushButton",
            {
                "background-color": p.canvas,
                "color": p.text,
                "border": f"1px solid {p.border}",
                "border-radius": "8px",
                "padding": "0px 16px",
                "min-height": "34px",
            },
        ),
        ("QPushButton:disabled", {"color": p.secondary}),
        (
            'QPushButton[role="primary"]',
            {
                "background-color": p.accent_text,
                "color": p.primary_text,
                "border": f"1px solid {p.accent_text}",
            },
        ),
        (
            'QPushButton[role="danger"]',
            {
                "background-color": p.danger,
                "color": p.danger_text,
                "border": f"1px solid {p.danger}",
            },
        ),
        ('QPushButton[role="chip"]', {"padding": "0px 12px"}),
        (
            'QPushButton[role="chip"]:checked',
            {
                "background-color": p.selection,
                "color": p.accent_text,
                "border": f"1px solid {p.accent}",
            },
        ),
        (
            "QPushButton:focus, QLineEdit:focus, QComboBox:focus, QAbstractItemView:focus",
            {"border": f"1px solid {p.accent}"},
        ),
        (
            'QPushButton[role="link"], QPushButton[role="link"]:focus',
            {
                "background-color": "transparent",
                "color": p.accent_text,
                "border": "none",
                "padding": "0px",
                "min-height": "20px",
                "text-align": "left",
            },
        ),
        ('QPushButton[role="link"]:focus', {"text-decoration": "underline"}),
        (
            'QListWidget[role="nav"], QListWidget[role="nav"]:focus',
            {"background-color": p.surface, "border": "none"},
        ),
        ("QComboBox::drop-down", {"border": "none", "width": "24px"}),
        ('QFrame#sidebar QLabel[role="secondary"]', {"font-size": "13px"}),
        (
            "QScrollBar:vertical",
            {"background-color": p.canvas, "width": "12px", "margin": "0px", "border": "none"},
        ),
        (
            "QScrollBar:horizontal",
            {"background-color": p.canvas, "height": "12px", "margin": "0px", "border": "none"},
        ),
        (
            "QScrollBar::handle:vertical",
            {
                "background-color": p.border,
                "border-radius": "4px",
                "margin": "2px",
                "min-height": "24px",
            },
        ),
        (
            "QScrollBar::handle:horizontal",
            {
                "background-color": p.border,
                "border-radius": "4px",
                "margin": "2px",
                "min-width": "24px",
            },
        ),
        ("QScrollBar::handle:hover", {"background-color": p.secondary}),
        (
            "QScrollBar::add-line, QScrollBar::sub-line",
            {"width": "0px", "height": "0px", "border": "none", "background": "none"},
        ),
        ("QScrollBar::add-page, QScrollBar::sub-page", {"background": "none"}),
        (
            "QProgressBar",
            {
                "background-color": p.surface,
                "border": f"1px solid {p.border}",
                "border-radius": "4px",
            },
        ),
        ("QProgressBar::chunk", {"background-color": p.accent}),
        (
            "QToolTip",
            {
                "background-color": p.surface2,
                "color": p.text,
                "border": f"1px solid {p.border}",
            },
        ),
    ]
    for level in Level:
        badge = p.badges[level]
        rules.append((f'QLabel[badge="{level.value}"]', _badge(badge)))
        rules.append((f'QFrame[dot="{level.value}"]', _dot(p.levels[level])))
    rules.append(('QFrame[dot="none"]', _dot(p.secondary)))
    rules.append(('QLabel[badge="danger"]', _badge(p.danger_badge)))
    return rules


def _badge(badge: Badge) -> dict[str, str]:
    return {
        "color": badge.text,
        "background-color": badge.background,
        "border-radius": "10px",
        "padding": "0px 8px",
        "font-size": "12px",
        "font-weight": "600",
    }


def _dot(colour: str) -> dict[str, str]:
    return {"background-color": colour, "border": "none", "border-radius": "4px"}


def style_sheet(palette: Palette) -> str:
    """The window's Qt style sheet in one palette."""
    lines = (
        f"{selector} {{ "
        + " ".join(f"{key}: {value};" for key, value in declarations.items())
        + " }"
        for selector, declarations in _rules(palette)
    )
    return "\n".join(lines) + "\n"


class Look(QObject):
    """One window's palette: dark when Qt reports a dark colour scheme, light otherwise, and a
    change of the system's scheme applied at once; ``changed`` then says which. It lives as long
    as its window."""

    changed = Signal(object)

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self.palette: Palette = LIGHT
        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(self._follow)
        self._follow(hints.colorScheme())

    def _follow(self, scheme: Qt.ColorScheme) -> None:
        self.palette = palette_for(dark=scheme == Qt.ColorScheme.Dark)
        self._window.setStyleSheet(style_sheet(self.palette))
        self.changed.emit(self.palette)
