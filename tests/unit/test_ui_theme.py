"""The window's look: the tokens, the contrast, the style sheet (decision 0014, items 32, 33 and
46-48)."""

import re
from pathlib import Path

import pytest

from kresorter.analysis.score import Level
from kresorter.ui.theme import (
    DARK,
    LIGHT,
    Badge,
    Palette,
    contrast,
    luminance,
    palette_for,
    style_sheet,
    tint,
)

DECISION = Path(__file__).resolve().parents[2] / "docs" / "decisions" / "0014-ui.md"
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
LEVEL_ROWS = {"safe": Level.SAFE, "likely safe": Level.LIKELY_SAFE, "review": Level.REVIEW}


def _table() -> dict[str, tuple[str, str]]:
    """The rows of the decision's table of tokens: name, light cell, dark cell."""
    lines = DECISION.read_text(encoding="utf-8").splitlines()
    start = lines.index("| Token | Light | Dark |") + 2
    rows: dict[str, tuple[str, str]] = {}
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        name, light, dark = (cell.strip() for cell in line.strip("|").split("|"))
        rows[name] = (light, dark)
    return rows


def _row(palette: Palette, name: str, dark: bool) -> list[str]:
    """The colours of one row of the table, in the order it writes them."""
    simple = {
        "canvas": palette.canvas,
        "surface": palette.surface,
        "surface 2": palette.surface2,
        "border": palette.border,
        "text": palette.text,
        "secondary text": palette.secondary,
        "accent": palette.accent,
    }
    if name in simple:
        return [simple[name]]
    if name == "accent text, primary button":
        return [palette.accent_text, palette.primary_text]
    label = name.split(":")[0]
    if label == "danger":
        badge, first = palette.danger_badge, [palette.danger, palette.danger_text]
    else:
        badge, first = palette.badges[LEVEL_ROWS[label]], [palette.levels[LEVEL_ROWS[label]]]
    # In the dark palette a badge's text is not written: it is the level's colour.
    return [*first, badge.background] if dark else [*first, badge.text, badge.background]


def _rules(sheet: str) -> list[tuple[str, dict[str, str]]]:
    rules: list[tuple[str, dict[str, str]]] = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
        declarations = (part.split(":", 1) for part in body.split(";") if part.strip())
        pairs = {key.strip(): value.strip() for key, value in declarations}
        rules.append((selector.strip(), pairs))
    return rules


# --- the tokens ----------------------------------------------------------------------------------


def test_the_tokens_are_those_of_the_table() -> None:
    # [0014.32]
    table = _table()
    assert len(table) == 12
    for name, (light, dark) in table.items():
        assert [c.upper() for c in HEX.findall(light)] == _row(LIGHT, name, dark=False), name
        assert [c.upper() for c in HEX.findall(dark)] == _row(DARK, name, dark=True), name


def test_a_dark_badge_is_the_level_colour_on_a_12_percent_tint_of_it() -> None:
    # [0014.32]
    for level in Level:
        badge = DARK.badges[level]
        assert badge.text == DARK.levels[level]
        assert badge.background == tint(DARK.levels[level], over=DARK.canvas, amount=0.12)
    assert DARK.danger_badge == Badge(DARK.danger, tint(DARK.danger, over=DARK.canvas, amount=0.12))


def test_a_tint_mixes_each_channel_and_rounds() -> None:
    # [0014.32]
    assert tint("#72BC8F", over="#191919", amount=0.12) == "#242D27"
    assert tint("#FFFFFF", over="#000000", amount=0.5) == "#808080"
    assert tint("#123456", over="#ABCDEF", amount=0.0) == "#ABCDEF"
    assert tint("#123456", over="#ABCDEF", amount=1.0) == "#123456"


def test_the_system_decides_which_palette() -> None:
    # [0014.34]
    assert palette_for(dark=True) is DARK
    assert palette_for(dark=False) is LIGHT


def test_every_colour_of_a_palette() -> None:
    # [0014.32]
    for palette in (LIGHT, DARK):
        colours = palette.colours()
        assert {palette.canvas, palette.accent, palette.danger} <= colours
        assert {badge.background for badge in palette.badges.values()} <= colours
        assert palette.danger_badge.background in colours
        assert all(HEX.fullmatch(colour) and colour == colour.upper() for colour in colours)


# --- readable ------------------------------------------------------------------------------------


def test_the_contrast_ratio_of_wcag_2() -> None:
    # [0014.33]
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#FFFFFF", "#000000") == pytest.approx(21.0)
    assert contrast("#2783DE", "#2783DE") == pytest.approx(1.0)
    assert contrast("#767676", "#FFFFFF") == pytest.approx(4.54, abs=0.01)
    assert luminance("#000000") == 0.0
    assert luminance("#FFFFFF") == pytest.approx(1.0)
    assert luminance("#0A0A0A") == pytest.approx(10 / 255 / 12.92)


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_text_badges_and_buttons_are_readable(palette: Palette) -> None:
    # [0014.33]
    grounds = (palette.canvas, palette.surface, palette.surface2)
    pairs = [(palette.text, ground) for ground in grounds]
    pairs += [
        (colour, ground)
        for colour in (palette.secondary, palette.accent_text)
        for ground in (palette.canvas, palette.surface)
    ]
    pairs += [(badge.text, badge.background) for badge in palette.badges.values()]
    pairs += [(palette.danger_badge.text, palette.danger_badge.background)]
    pairs += [(palette.primary_text, palette.accent_text), (palette.danger_text, palette.danger)]
    assert len(pairs) == 13
    low = [(a, b, round(contrast(a, b), 2)) for a, b in pairs if contrast(a, b) < 4.5]
    assert low == []


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_accent_and_the_level_colours_stand_out_on_the_canvas(palette: Palette) -> None:
    # [0014.33]
    colours = [palette.accent, *palette.levels.values()]
    assert len(colours) == 4
    assert all(contrast(colour, palette.canvas) >= 3.0 for colour in colours)


# --- the style sheet -----------------------------------------------------------------------------


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_style_sheet_uses_no_other_colour(palette: Palette) -> None:
    # [0014.32]
    sheet = style_sheet(palette)
    assert {colour.upper() for colour in HEX.findall(sheet)} <= palette.colours()
    assert re.findall(r"#[0-9A-Fa-f]{3,8}\b", sheet) == HEX.findall(sheet)
    assert not re.search(r"\b(rgba?|hsla?|hsv|qlineargradient|qradialgradient)\(", sheet)
    assert _rules(sheet)
    assert all(declarations for _, declarations in _rules(sheet))


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_accent_marks_the_selection_and_the_focus(palette: Palette) -> None:
    # [0014.32] A selected row and a chip that is on are on the accent's tint: the likely safe
    # badge's background, the likely safe colour being the accent.
    rules = _rules(style_sheet(palette))
    found = dict(rules)
    assert palette.levels[Level.LIKELY_SAFE] == palette.accent
    assert palette.selection == palette.badges[Level.LIKELY_SAFE].background
    assert found["QAbstractItemView"]["selection-background-color"] == palette.selection
    chip = found['QPushButton[role="chip"]:checked']
    assert chip["background-color"] == palette.selection
    assert chip["border"] == f"1px solid {palette.accent}"
    focus = [d for s, d in rules if ":focus" in s and "link" not in s and "nav" not in s]
    assert focus
    assert all(d["border"] == f"1px solid {palette.accent}" for d in focus)
    primary = [d for s, d in rules if s == 'QPushButton[role="primary"]']
    assert primary == [
        {
            "background-color": palette.accent_text,
            "color": palette.primary_text,
            "border": f"1px solid {palette.accent_text}",
            "font-weight": "600",
        }
    ]
    danger = [d for s, d in rules if s == 'QPushButton[role="danger"]']
    assert [d["font-weight"] for d in danger] == ["600"]


def test_the_dark_selection_is_a_12_percent_tint_of_the_accent() -> None:
    # [0014.32]
    assert DARK.selection == tint(DARK.accent, over=DARK.canvas, amount=0.12)


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_a_badge_is_its_text_on_its_background_and_a_dot_the_level_colour(
    palette: Palette,
) -> None:
    # [0014.32]
    rules = dict(_rules(style_sheet(palette)))
    for level in Level:
        badge = rules[f'QLabel[badge="{level.value}"]']
        assert badge["color"] == palette.badges[level].text
        assert badge["background-color"] == palette.badges[level].background
        dot = rules[f'QFrame[dot="{level.value}"]']
        assert dot == {
            "background-color": palette.levels[level],
            "border": "none",
            "border-radius": "4px",
        }
    assert rules['QFrame[dot="none"]']["background-color"] == palette.secondary
    danger = rules['QLabel[badge="danger"]']
    assert danger["color"] == palette.danger_badge.text
    assert danger["background-color"] == palette.danger_badge.background


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_cards_chips_fields_buttons_links_and_badges(palette: Palette) -> None:
    # [0014.47] Fields and buttons: 34 px inside a border of 1 px, 36 px in all; a badge 20 px
    # high, its radius half of it: a pill.
    rules = dict(_rules(style_sheet(palette)))
    assert rules['QFrame[role="card"]'] == {
        "background-color": palette.canvas,
        "border": f"1px solid {palette.border}",
        "border-radius": "12px",
    }
    assert rules['QFrame[role="card"][tone="surface"]'] == {"background-color": palette.surface}
    for selector in ("QPushButton", "QLineEdit, QComboBox"):
        assert rules[selector]["border-radius"] == "8px"
        assert rules[selector]["border"] == f"1px solid {palette.border}"
        assert rules[selector]["min-height"] == "34px"
    assert rules["QPushButton"]["background-color"] == palette.canvas
    link = rules['QPushButton[role="link"], QPushButton[role="link"]:focus']
    assert link["color"] == palette.accent_text
    assert link["border"] == "none"
    assert link["background-color"] == "transparent"
    for kind in [level.value for level in Level] + ["danger"]:
        assert rules[f'QLabel[badge="{kind}"]']["border-radius"] == "10px"
    header = rules["QHeaderView::section"]
    assert (header["color"], header["font-size"]) == (palette.secondary, "12px")
    assert header["border-bottom"] == f"1px solid {palette.border}"
    views = rules["QAbstractItemView"]
    assert views["background-color"] == palette.canvas
    assert rules["QScrollBar::handle:vertical"]["background-color"] == palette.border
    assert rules["QFrame#sidebar"]["border-right"] == f"1px solid {palette.border}"


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_overview_s_chips_figures_captions_and_cards_that_open_a_page(
    palette: Palette,
) -> None:
    # [0014.48] A folder's chip is bordered on the canvas; Add folder has no border; a card
    # that opens a page shows the focus on the accent.
    rules = dict(_rules(style_sheet(palette)))
    assert rules['QFrame[role="chip"]'] == {
        "background-color": palette.canvas,
        "border": f"1px solid {palette.border}",
        "border-radius": "8px",
    }
    plain = rules['QPushButton[role="plain"]']
    assert (plain["background-color"], plain["border"], plain["color"]) == (
        "transparent",
        "none",
        palette.text,
    )
    assert rules['QPushButton[role="icon"]']["border"] == "none"
    assert rules['QLabel[role="figure"]'] == {"font-size": "28px", "font-weight": "600"}
    assert rules['QLabel[role="caption"]'] == {"color": palette.secondary, "font-size": "13px"}
    assert rules['QLabel[role="card-title"]'] == {"font-size": "16px", "font-weight": "600"}
    assert rules['QFrame[role="card"]:focus'] == {"border": f"1px solid {palette.accent}"}


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_a_confirmation_s_title_is_18_px_semibold_and_its_details_on_surface(
    palette: Palette,
) -> None:
    # [0014.50]
    rules = dict(_rules(style_sheet(palette)))
    assert rules['QLabel[role="question"]'] == {"font-size": "18px", "font-weight": "600"}
    assert rules['QPlainTextEdit[role="details"]'] == {
        "background-color": palette.surface,
        "border": "none",
        "border-radius": "8px",
    }


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_bar_the_detail_at_the_side_and_the_advisory_badge(palette: Palette) -> None:
    # [0014.49] [0014.54] A border above the bar, one at the detail's left; the advisory badge
    # is text on surface2, a pill.
    rules = dict(_rules(style_sheet(palette)))
    canvas, border = palette.canvas, f"1px solid {palette.border}"
    assert rules['QFrame[role="bar"]'] == {
        "background-color": canvas,
        "border": "none",
        "border-top": border,
    }
    assert rules['QFrame[role="side"]'] == {
        "background-color": canvas,
        "border": "none",
        "border-left": border,
    }
    advisory = rules['QLabel[badge="advisory"]']
    assert (advisory["color"], advisory["background-color"]) == (palette.text, palette.surface2)
    assert advisory["border-radius"] == "10px"


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_a_title_is_24_px_semibold_and_what_it_does_secondary_text(palette: Palette) -> None:
    # [0014.46]
    rules = dict(_rules(style_sheet(palette)))
    assert rules["QLabel#title"] == {"font-size": "24px", "font-weight": "600"}
    assert rules["QLabel#subtitle"] == {"color": palette.secondary}


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_danger_is_the_purge_s_alone(palette: Palette) -> None:
    # [0014.32] Only the danger button, the pointer over it too (decision 0018, item 8), and
    # the danger badge use the danger colours.
    danger = {palette.danger, palette.danger_badge.text, palette.danger_badge.background}
    users = [
        selector
        for selector, declarations in _rules(style_sheet(palette))
        if any(colour in value for colour in danger for value in declarations.values())
    ]
    assert users == [
        'QPushButton[role="danger"]',
        'QPushButton[role="danger"]:enabled:hover',
        'QLabel[badge="danger"]',
    ]
