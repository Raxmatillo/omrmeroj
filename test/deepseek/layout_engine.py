# layout_engine.py
from config import LayoutConfig
from typing import Tuple, Optional

class LayoutEngine:
    """Computes coordinates for all sections. All units in mm, origin at top-left of page (y increases downward)."""

    def __init__(self, config: LayoutConfig):
        self.cfg = config
        self.content_left = config.margin_left_mm
        self.content_top = config.margin_top_mm
        self.content_width = config.page_width_mm - config.margin_left_mm - config.margin_right_mm
        self.content_height = config.page_height_mm - config.margin_top_mm - config.margin_bottom_mm
        self._y = self.content_top  # current vertical position tracker

    def reserve_space(self, height_mm: float) -> Tuple[float, float, float, float]:
        """Return (x, y, w, h) for a full-width block and advance y."""
        x = self.content_left
        w = self.content_width
        y = self._y
        self._y += height_mm
        return x, y, w, height_mm

    def reserve_two_column_space(self, left_height: float, right_height: float) -> Tuple[
        Tuple[float, float, float, float], Tuple[float, float, float, float]]:
        """Return two rectangles side by side, y aligned, advance by max height."""
        used_height = max(left_height, right_height)
        half_width = self.content_width / 2
        left_rect = (self.content_left, self._y, half_width, used_height)
        right_rect = (self.content_left + half_width, self._y, half_width, used_height)
        self._y += used_height
        return left_rect, right_rect

    def current_y(self) -> float:
        return self._y

    def set_y(self, y: float):
        self._y = y