"""
Miroku — Unified stat strip

One card, N columns divided by thin rules. Shared by the Statistics
page's overview band and by HeatmapSection's streak/total/busiest row —
a single "stat strip" visual vocabulary instead of repeated,
independently-bordered tiles (the generic hero-metric-template pattern).

Split into its own module so both `stats_page.py` and `heatmap_widget.py`
can import it without a circular dependency (stats_page embeds
HeatmapSection).
"""
from typing import List, Optional, Tuple

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class StatStrip(QFrame):
    def __init__(self, items: List[Tuple[str, str, Optional[str]]],
                 parent=None) -> None:
        """items: list of (value, label, trend_or_None)."""
        super().__init__(parent)
        self.setObjectName("statStrip")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        for i, (value, label, trend) in enumerate(items):
            col = QWidget()
            col.setStyleSheet("background:transparent;")
            cl = QVBoxLayout(col)
            cl.setContentsMargins(22, 20, 22, 20)
            cl.setSpacing(6)

            val_lbl = QLabel(value)
            val_lbl.setObjectName("statStripValue")
            cl.addWidget(val_lbl)

            lbl = QLabel(label)
            lbl.setObjectName("statStripLabel")
            cl.addWidget(lbl)

            if trend:
                tr = QLabel(trend)
                tr.setObjectName("statStripTrend")
                cl.addWidget(tr)

            lay.addWidget(col, 1)

            if i < len(items) - 1:
                divider = QFrame()
                divider.setObjectName("statStripDivider")
                divider.setSizePolicy(
                    QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
                )
                lay.addWidget(divider)
