"""The window's look: the tokens, the contrast, the style sheet (decision 0014, items 32-33)."""

import re
from pathlib import Path

import pytest

from safeclean.analysis.score import Level
from safeclean.ui.theme import (
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
def test_the_accent_marks_the_current_page_the_selection_and_the_focus(palette: Palette) -> None:
    # [0014.32]
    rules = _rules(style_sheet(palette))

    def uses_accent(part: str) -> bool:
        return any(
            part in selector and any(palette.accent in value for value in declarations.values())
            for selector, declarations in rules
        )

    assert uses_accent("#sidebar::item:selected")
    assert uses_accent("::item:selected")
    assert uses_accent(":focus")
    primary = [d for s, d in rules if s == 'QPushButton[role="primary"]']
    assert primary == [
        {
            "background-color": palette.accent_text,
            "color": palette.primary_text,
            "border": f"1px solid {palette.accent_text}",
        }
    ]


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
        assert rules[f'QLabel[dot="{level.value}"]'] == {"color": palette.levels[level]}
    danger = rules['QLabel[badge="danger"]']
    assert danger["color"] == palette.danger_badge.text
    assert danger["background-color"] == palette.danger_badge.background


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_danger_is_the_purge_s_alone(palette: Palette) -> None:
    # [0014.32] Only the danger button and the danger badge use the danger colours.
    danger = {palette.danger, palette.danger_badge.text, palette.danger_badge.background}
    users = [
        selector
        for selector, declarations in _rules(style_sheet(palette))
        if any(colour in value for colour in danger for value in declarations.values())
    ]
    assert users == ['QPushButton[role="danger"]', 'QLabel[badge="danger"]']
