"""Shop menu geometry and scrolling rules, shared by drawing, hit-testing and keyboard navigation (REVIEW L13, plan 8.6).

The shop used to repeat these numbers in four places that drifted apart: duplicate unreachable ``elif`` branches in
navigation, hit-test rows measured from y=265 while drawing used a y=283 baseline with no shared definition, and a
"row 5" that hit-tested as an item below the visible list. Drawing, hit-tests and navigation now all derive from the
layouts and rules below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

VISIBLE_ROWS = 4          # scrolling lists show 4 items...
BACK_ROW = VISIBLE_ROWS   # ...and "Back" on the row after them


@dataclass(frozen=True)
class ListLayout:
    """A vertical text menu: text is drawn at ``baseline + row * row_h``; a row's click box starts ``ascent`` above."""
    x: int
    baseline: int
    row_h: int
    hit_x0: int
    hit_x1: int
    hit_bottom: int
    ascent: int = 18

    @property
    def top(self) -> int:
        return self.baseline - self.ascent

    def draw_origin(self) -> tuple[int, int, int]:
        """(start_x, start_y, line_h) for the painter."""
        return self.x, self.baseline, self.row_h

    def row_at(self, px: int, py: int) -> Optional[int]:
        if not (self.hit_x0 <= px <= self.hit_x1 and self.top <= py <= self.hit_bottom):
            return None
        return (py - self.top) // self.row_h


LEFT_LIST = ListLayout(x=44, baseline=283, row_h=36, hit_x0=20, hit_x1=400, hit_bottom=485)
RIGHT_LIST = ListLayout(x=444, baseline=283, row_h=36, hit_x0=412, hit_x1=630, hit_bottom=465)
TOGGLES_LIST = ListLayout(x=44, baseline=278, row_h=28, hit_x0=20, hit_x1=400, hit_bottom=485, ascent=16)


@dataclass(frozen=True)
class ScrollSpec:
    """A scrolling list: where its scroll offset lives, how many items it has (Back excluded), and whether moving
    the selection onto Back scrolls the list too."""
    offset_attr: Callable[[Any], str]
    item_count: Callable[[Any], int]
    back_scrolls: bool


def follow_selection(selected: int, offset: int, item_count: int, back_scrolls: bool,
                     visible: int = VISIBLE_ROWS) -> int:
    """New scroll offset that keeps ``selected`` in view (the one rule for up AND down navigation)."""
    if selected < offset:
        return selected
    if (back_scrolls or selected < item_count) and selected >= offset + visible:
        return max(0, selected - (visible - 1))
    return offset


def list_index_at_row(row: int, offset: int, item_count: int) -> Optional[int]:
    """Item index under a clicked row of a scrolling list (``item_count`` = Back), or None."""
    if row == BACK_ROW:
        return item_count
    if 0 <= row < VISIBLE_ROWS:
        idx = offset + row
        return idx if idx < item_count else None
    return None
