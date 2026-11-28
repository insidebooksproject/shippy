"""Logging names and setup shared by both apps.

Each app's verbose printer logs come from ibp-printing and are named after
the app: ``printer-shippy.log``/``.jsonl`` for the CLI and
``printer-shippy-gui.log``/``.jsonl`` for shippy-gui, in ibp-printing's
per-machine log directory. The same names tag each app's labels in the shared
label journal (``app=``), so they must never change.
"""

import logging
from pathlib import Path

import ibp_printing
from ibp_printing.log import get_logger as _printing_logger

CLI_APP = "shippy"
GUI_APP = "shippy-gui"
# ``shippy diagnose-printer`` may run next to a shipping session; it gets its
# own printer log files.
DIAG_APP = "diag"


def get_logger(name: str) -> logging.Logger:
    """A logger for shared code whose records reach the app's printer logs.

    It sits under ibp-printing's logger, so in the CLI (which has no log file
    of its own) its records go to ``printer-shippy.*``; in shippy-gui they go
    to ``printer-shippy-gui.*`` and, at INFO and above, its own log file.
    """
    return _printing_logger(name)


def configure_logging(app: str) -> Path:
    """Write ibp-printing's printer logs to files named after ``app``.

    Never to the console: shippy-gui has none (pythonw) and the CLI's belongs
    to the volunteer's prompts. Safe to call more than once.

    Returns:
        The directory ibp-printing writes its printer logs to.
    """
    return ibp_printing.configure_logging(app=app, console=False)
