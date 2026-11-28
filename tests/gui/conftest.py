"""Run the shippy-gui tests without a display."""

import os

# Must be set before the first QApplication is created; an explicit setting
# (e.g. QT_QPA_PLATFORM=xcb to watch the widgets) still wins.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
