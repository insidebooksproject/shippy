"""Logging names and setup shared by both apps.

Each app's verbose printer logs come from ibp-printing and are named after
the app: ``printer-shippy.log``/``.jsonl`` for the CLI and
``printer-shippy-gui.log``/``.jsonl`` for shippy-gui, in ibp-printing's
per-machine log directory. The same names tag each app's labels in the shared
label journal (``app=``), so they must never change.

At startup each app calls :func:`start_logging`, which also writes the whole
app's warnings and errors to ``errors-<app>.jsonl`` in that directory (the
stations' log upload copies it to ``ibp-server`` for the weekly error digest),
logs uncaught exceptions, and logs a ``<app> starting`` line with the version.
"""

import functools
import importlib.metadata
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional

import ibp_printing
from ibp_printing import log as printing_log
from ibp_printing.log import get_logger as _printing_logger

from shippy.core.redact import scrub_secrets

CLI_APP = "shippy"
GUI_APP = "shippy-gui"
# ``shippy diagnose-printer`` may run next to a shipping session; it gets its
# own printer log files.
DIAG_APP = "diag"

DISTRIBUTION = "shippy"
UNKNOWN_VERSION = "unknown"

_hooks_lock = threading.Lock()
_hooks_installed = False  # pylint: disable=invalid-name


def get_logger(name: str) -> logging.Logger:
    """A logger for shared code whose records reach the app's printer logs.

    It sits under ibp-printing's logger, so in the CLI (which has no log file
    of its own) its records go to ``printer-shippy.*``; in shippy-gui they go
    to ``printer-shippy-gui.*`` and, at INFO and above, its own log file.
    """
    return _printing_logger(name)


@functools.cache
def app_version() -> str:
    """The installed shippy version, with the git commit it was built from.

    The stations install shippy with uv from the ``deploy`` branch, and uv
    records the commit (PEP 610 ``direct_url.json``), so this reads e.g.
    ``0.1.0+gb8ac3af``: the package version alone never changes between
    releases. A checkout or wheel without that record gives just ``0.1.0``.
    """
    try:
        distribution = importlib.metadata.distribution(DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return UNKNOWN_VERSION
    version = distribution.version or UNKNOWN_VERSION
    commit = _vcs_commit(distribution)
    return f"{version}+g{commit[:7]}" if commit else version


def _vcs_commit(distribution: importlib.metadata.Distribution) -> Optional[str]:
    """The git commit an install from a git URL was built from, if recorded."""
    try:
        text = distribution.read_text("direct_url.json")
        if not text:
            return None
        commit = json.loads(text).get("vcs_info", {}).get("commit_id")
    except (OSError, ValueError, AttributeError):
        return None
    return commit if isinstance(commit, str) and commit else None


def configure_logging(app: str) -> Path:
    """Write ibp-printing's printer logs to files named after ``app``.

    Never to the console: shippy-gui has none (pythonw) and the CLI's belongs
    to the volunteer's prompts. Each JSON record carries :func:`app_version`.
    Safe to call more than once.

    Returns:
        The directory ibp-printing writes its printer logs to.
    """
    return ibp_printing.configure_logging(app=app, version=app_version(), console=False)


def start_logging(app: str) -> Path:
    """Set up an app's logs when it starts, and log its ``starting`` line.

    The printer logs (:func:`configure_logging`), ``errors-<app>.jsonl`` with
    every WARNING and above from the whole process, and the uncaught-exception
    hooks (:func:`install_exception_hooks`). Every file it writes in the log
    directory goes through :func:`shippy.core.redact.scrub_secrets`, since
    the stations upload that directory. The ``<app> starting`` line, at INFO,
    goes to the printer logs with the version, like the label watcher's
    (shippy-gui's own log, set up later from config.ini, gets its own
    ``Shippy GUI started`` line instead). Safe to call more than once.

    Returns:
        The log directory (printer logs and error log).
    """
    version = app_version()
    log_dir = configure_logging(app)
    ibp_printing.configure_error_log(app, version=version, log_dir=log_dir)
    scrub_log_dir(log_dir)
    install_exception_hooks()
    printing_log.log_event(
        get_logger("shippy.startup"),
        logging.INFO,
        f"{app} starting",
        app=app,
        version=version,
        argv=sys.argv,
        python=sys.version.split()[0],
        platform=sys.platform,
        error_log=printing_log.error_log_file_name(app),
    )
    return log_dir


class _ScrubbingFormatter(logging.Formatter):
    """Another formatter's output, with :func:`scrub_secrets` applied."""

    def __init__(self, inner: logging.Formatter):
        super().__init__()
        self.inner = inner

    def format(self, record: logging.LogRecord) -> str:
        return scrub_secrets(self.inner.format(record))


def scrub_log_dir(log_dir: Path) -> None:
    """Redact API keys from every log file ibp-printing writes in ``log_dir``.

    The backstop for a message or traceback that repeats one (a Google Maps
    request URL ends ``&key=...``): wraps the formatter of each file handler
    there, on the root logger (the error log) and ibp-printing's (the
    printer logs). Safe to call more than once.
    """
    directory = Path(os.path.abspath(log_dir))
    for owner in (logging.getLogger(), logging.getLogger(printing_log.LOGGER_NAME)):
        for handler in owner.handlers:
            filename = getattr(handler, "baseFilename", None)
            if (
                filename
                and Path(filename).parent == directory
                and handler.formatter is not None
                and not isinstance(handler.formatter, _ScrubbingFormatter)
            ):
                handler.setFormatter(_ScrubbingFormatter(handler.formatter))


def install_exception_hooks() -> None:
    """Log uncaught exceptions, and still show them the way Python did.

    ibp-printing's hooks log an uncaught exception at CRITICAL, in the main
    thread (``sys.excepthook``) or any other (``threading.excepthook``). They
    replace the hooks that were there, so those are called afterwards: the
    traceback still reaches a console or terminal when there is one (under
    pythonw there is none, and Python then prints nothing). Ctrl+C
    (``KeyboardInterrupt``) is how a volunteer quits, not an error, so it is
    shown as before but not logged.

    PySide6 reports an exception raised in a slot, a virtual override (e.g.
    ``closeEvent``), ``QThread.run`` or ``QRunnable.run`` through
    ``sys.excepthook`` and carries on, so this also logs every exception
    shippy-gui's Qt code leaves uncaught. Installs once per process.
    """
    global _hooks_installed  # pylint: disable=global-statement
    with _hooks_lock:
        if _hooks_installed:
            return
        shown_main, shown_thread = sys.excepthook, threading.excepthook
        printing_log.install_exception_hooks()
        logged_main, logged_thread = sys.excepthook, threading.excepthook

        def main_hook(exc_type, exc, traceback):
            if not issubclass(exc_type, KeyboardInterrupt):
                logged_main(exc_type, exc, traceback)
            shown_main(exc_type, exc, traceback)

        def thread_hook(args: threading.ExceptHookArgs) -> None:
            if not issubclass(args.exc_type, KeyboardInterrupt):
                logged_thread(args)
            shown_thread(args)

        sys.excepthook = main_hook
        threading.excepthook = thread_hook
        _hooks_installed = True
