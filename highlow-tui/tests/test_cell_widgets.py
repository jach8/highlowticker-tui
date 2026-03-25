import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static


# We test that the class-level reactive pattern works by building a minimal app
class _PriceCell(Static):
    from textual.reactive import reactive
    value: reactive = reactive("—", layout=False)

    def watch_value(self, new: str) -> None:
        self.update(new)


class _TestApp(App):
    def compose(self) -> ComposeResult:
        yield _PriceCell("—", id="cell")


@pytest.mark.asyncio
async def test_price_cell_updates_on_value_change():
    app = _TestApp()
    async with app.run_test() as pilot:
        cell = app.query_one("#cell", _PriceCell)
        assert cell.value == "—"
        cell.value = "$142.50"
        await pilot.pause()
        assert cell.value == "$142.50"


@pytest.mark.asyncio
async def test_price_cell_no_update_when_value_unchanged():
    """Setting same value should not trigger watch_value (Textual built-in behavior)."""
    app = _TestApp()
    update_count = []

    original_watch = _PriceCell.watch_value

    def counting_watch(self, new):
        update_count.append(new)
        original_watch(self, new)

    _PriceCell.watch_value = counting_watch
    try:
        async with app.run_test() as pilot:
            cell = app.query_one("#cell", _PriceCell)
            cell.value = "$100.00"
            await pilot.pause()
            count_after_first = len(update_count)
            cell.value = "$100.00"  # same value
            await pilot.pause()
            # watch_value should NOT have been called again
            assert len(update_count) == count_after_first
    finally:
        _PriceCell.watch_value = original_watch
