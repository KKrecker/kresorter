"""The window's look (decision 0014, items 32-34).

The colours are the tokens of the decision's table, a light and a dark palette; the style sheet
uses no other colour. ``accent`` marks the current page, the selection and the focus; accented
text and the primary button use ``accent text``; a level's badge is its text on its background
and its dot the level's colour; ``danger`` is the purge's alone. ``Look`` follows the colour
scheme Qt reports, dark or not, and applies a change at once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt
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
    rules: list[tuple[str, dict[str, str]]] = [
        ("QMainWindow, QDialog", {"background-color": p.canvas}),
        ("QWidget", {"color": p.text}),
        (
            "QListWidget#sidebar",
            {
                "background-color": p.surface,
                "border": "none",
                "border-right": f"1px solid {p.border}",
            },
        ),
        ("QListWidget#sidebar::item", {"padding": "6px 12px", "color": p.text}),
        (
            "QListWidget#sidebar::item:selected",
            {
                "background-color": p.surface2,
                "color": p.accent_text,
                "border-left": f"3px solid {p.accent}",
            },
        ),
        ('QLabel[role="secondary"]', {"color": p.secondary}),
        ('QLabel[role="accent"]', {"color": p.accent_text}),
        (
            'QFrame[role="banner"]',
            {
                "background-color": p.surface2,
                "border": f"1px solid {p.border}",
                "border-radius": "6px",
            },
        ),
        (
            "QAbstractItemView",
            {
                "background-color": p.canvas,
                "alternate-background-color": p.surface,
                "border": f"1px solid {p.border}",
            },
        ),
        (
            "QAbstractItemView::item:selected",
            {
                "background-color": p.surface2,
                "color": p.text,
                "border-top": f"1px solid {p.accent}",
                "border-bottom": f"1px solid {p.accent}",
            },
        ),
        (
            "QHeaderView::section",
            {
                "background-color": p.surface,
                "color": p.secondary,
                "border": "none",
                "border-bottom": f"1px solid {p.border}",
                "padding": "4px",
            },
        ),
        (
            "QLineEdit, QComboBox, QTextBrowser, QPlainTextEdit",
            {
                "background-color": p.canvas,
                "border": f"1px solid {p.border}",
                "border-radius": "4px",
            },
        ),
        (
            "QPushButton",
            {
                "background-color": p.surface2,
                "color": p.text,
                "border": f"1px solid {p.border}",
                "border-radius": "4px",
                "padding": "4px 12px",
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
        (
            "QPushButton:focus, QLineEdit:focus, QComboBox:focus, QAbstractItemView:focus",
            {"border": f"1px solid {p.accent}"},
        ),
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
        rules.append((f'QLabel[dot="{level.value}"]', {"color": p.levels[level]}))
    rules.append(('QLabel[badge="danger"]', _badge(p.danger_badge)))
    return rules


def _badge(badge: Badge) -> dict[str, str]:
    return {
        "color": badge.text,
        "background-color": badge.background,
        "border-radius": "4px",
        "padding": "1px 6px",
    }


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
    change of the system's scheme applied at once. It lives as long as its window."""

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
