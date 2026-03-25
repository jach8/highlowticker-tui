import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from textual.app import App, ComposeResult


class _KillApp(App):
    def on_mount(self) -> None:
        from app import KillModal
        self.confirmed = False
        self.push_screen(KillModal(positions=[], on_confirm=self._confirmed, id="kill"))

    def _confirmed(self):
        self.confirmed = True


async def _type(pilot, text: str) -> None:
    """Type each character using pilot.press()."""
    for ch in text:
        await pilot.press(ch)


@pytest.mark.asyncio
async def test_kill_modal_confirm_button_disabled_initially():
    app = _KillApp()
    async with app.run_test() as pilot:
        confirm_btn = app.screen.query_one("#kill-confirm-btn")
        assert confirm_btn.disabled


@pytest.mark.asyncio
async def test_kill_modal_confirm_enabled_after_typing_confirm():
    app = _KillApp()
    async with app.run_test() as pilot:
        inp = app.screen.query_one("#kill-input")
        await pilot.click(inp)
        await _type(pilot, "CONFIRM")
        await pilot.pause()
        confirm_btn = app.screen.query_one("#kill-confirm-btn")
        assert not confirm_btn.disabled


@pytest.mark.asyncio
async def test_kill_modal_wrong_text_keeps_button_disabled():
    app = _KillApp()
    async with app.run_test() as pilot:
        inp = app.screen.query_one("#kill-input")
        await pilot.click(inp)
        await _type(pilot, "confirm")  # lowercase — wrong
        await pilot.pause()
        confirm_btn = app.screen.query_one("#kill-confirm-btn")
        assert confirm_btn.disabled


@pytest.mark.asyncio
async def test_kill_modal_escape_does_not_confirm():
    app = _KillApp()
    async with app.run_test() as pilot:
        await pilot.press("escape")
        await pilot.pause()
        assert not app.confirmed
