import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from textual.app import App, ComposeResult


# Minimal host app for testing CommandBar
class _TestApp(App):
    CSS = """
    CommandBar { height: 3; }
    """
    def compose(self) -> ComposeResult:
        from app import CommandBar
        yield CommandBar(id="cmd")

    def on_key(self, event) -> None:
        from app import CommandBar
        cmd = self.query_one(CommandBar)
        if event.is_printable and not cmd.has_focus:
            cmd.open(event.character)
            event.stop()


@pytest.mark.asyncio
async def test_command_bar_opens_on_printable_key():
    app = _TestApp()
    async with app.run_test() as pilot:
        from app import CommandBar
        cmd = app.query_one(CommandBar)
        assert not cmd.is_open
        # Call open() directly to avoid Input auto-focus consuming the key event
        cmd.open("n")
        await pilot.pause()
        assert cmd.is_open


@pytest.mark.asyncio
async def test_escape_closes_command_bar():
    app = _TestApp()
    async with app.run_test() as pilot:
        from app import CommandBar
        cmd = app.query_one(CommandBar)
        cmd.open("n")
        await pilot.pause()
        assert cmd.is_open
        await pilot.press("escape")
        await pilot.pause()
        assert not cmd.is_open


@pytest.mark.asyncio
async def test_slash_sets_search_mode():
    app = _TestApp()
    async with app.run_test() as pilot:
        from app import CommandBar
        cmd = app.query_one(CommandBar)
        cmd.open("/")
        await pilot.pause()
        assert cmd.mode == "search"


@pytest.mark.asyncio
async def test_colon_sets_command_mode():
    app = _TestApp()
    async with app.run_test() as pilot:
        from app import CommandBar
        cmd = app.query_one(CommandBar)
        cmd.open(":")
        await pilot.pause()
        assert cmd.mode == "command"
