from avito_hunt.bot_service import (
    back_keyboard,
    discount_keyboard,
    models_keyboard,
    panel_keyboard,
    region_keyboard,
    settings_keyboard,
    storage_keyboard,
)


def callback_values(markup: object) -> set[str]:
    keyboard = markup.inline_keyboard  # type: ignore[attr-defined]
    return {
        button.callback_data
        for row in keyboard
        for button in row
        if button.callback_data is not None
    }


def test_root_panel_uses_inline_navigation() -> None:
    assert callback_values(panel_keyboard(True)) == {
        "settings:root",
        "panel:pause",
        "panel:status",
        "panel:help",
    }
    assert "panel:resume" in callback_values(panel_keyboard(False))


def test_every_nested_screen_has_a_back_button() -> None:
    nested = (
        settings_keyboard(),
        models_keyboard(()),
        storage_keyboard(()),
        region_keyboard(None),
        discount_keyboard(15),
        back_keyboard(),
    )
    for markup in nested:
        assert any(value.endswith(("root", "cancel")) for value in callback_values(markup))
