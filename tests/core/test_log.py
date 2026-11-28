"""Tests for the logging names and setup both apps share."""

import json
import logging
import pathlib
import sys
import threading
from unittest import mock

import pytest

from shippy.core import log

from ..log_files import read_jsonl

# The real function, before the fixture below replaces it, without its cache.
read_app_version = log.app_version.__wrapped__


@pytest.fixture(name="version", autouse=True)
def fixture_version() -> str:
    """A fixed app version, whatever is installed."""
    log.app_version.cache_clear()
    with mock.patch.object(log, "app_version", return_value="0.1.0+gabc1234"):
        yield "0.1.0+gabc1234"
    log.app_version.cache_clear()


def test_app_names_are_the_ones_existing_logs_and_journals_use():
    """printer-<app>.* file names and the journal's app= values never change."""
    assert (log.CLI_APP, log.GUI_APP, log.DIAG_APP) == ("shippy", "shippy-gui", "diag")


def test_shared_loggers_reach_ibp_printings_log_files():
    assert log.get_logger("shippy.core.x").name == "ibp_printing.shippy.core.x"


def test_configure_logging_never_logs_to_the_console(version):
    with mock.patch(
        "shippy.core.log.ibp_printing.configure_logging",
        return_value=pathlib.Path("logs"),
    ) as configure:
        assert log.configure_logging(log.GUI_APP) == pathlib.Path("logs")

    configure.assert_called_once_with(app="shippy-gui", version=version, console=False)


class FakeDistribution:  # pylint: disable=too-few-public-methods
    """Just enough of importlib.metadata.Distribution."""

    def __init__(self, direct_url):
        self.version = "0.1.0"
        self._direct_url = direct_url

    def read_text(self, name):
        assert name == "direct_url.json"
        return None if self._direct_url is None else json.dumps(self._direct_url)


@pytest.mark.parametrize(
    ("direct_url", "expected"),
    [
        (
            {
                "url": "https://github.com/insidebooksproject/shippy.git",
                "vcs_info": {
                    "vcs": "git",
                    "commit_id": "b8ac3af61da1ca430bbbb6d14212071235ff172c",
                    "requested_revision": "deploy",
                },
            },
            "0.1.0+gb8ac3af",
        ),
        ({"url": "file:///src/shippy", "dir_info": {"editable": True}}, "0.1.0"),
        (None, "0.1.0"),
    ],
)
def test_app_version_names_the_deployed_commit(direct_url, expected):
    """uv records the commit a git install came from; the version carries it."""
    with mock.patch.object(
        log.importlib.metadata,
        "distribution",
        return_value=FakeDistribution(direct_url),
    ):
        assert read_app_version() == expected


def test_app_version_without_an_installed_package():
    with mock.patch.object(
        log.importlib.metadata,
        "distribution",
        side_effect=log.importlib.metadata.PackageNotFoundError("shippy"),
    ):
        assert read_app_version() == "unknown"


def test_start_logging_writes_only_warnings_and_up_to_the_error_log(app_log_dir):
    assert log.start_logging(log.CLI_APP) == app_log_dir

    logging.getLogger("some.library").info("routine")
    logging.getLogger("some.library").warning("odd but handled")
    log.get_logger("shippy.x").error("failed for %s", "TEX-00012345-0")

    errors = read_jsonl(app_log_dir / "errors-shippy.jsonl")
    assert [(e["level"], e["logger"], e["msg"]) for e in errors] == [
        ("WARNING", "some.library", "odd but handled"),
        ("ERROR", "ibp_printing.shippy.x", "failed for TEX-00012345-0"),
    ]
    assert {(e["app"], e["version"]) for e in errors} == {("shippy", "0.1.0+gabc1234")}


def test_start_logging_logs_a_starting_line_with_the_version(app_log_dir):
    log.start_logging(log.GUI_APP)

    records = read_jsonl(app_log_dir / "printer-shippy-gui.jsonl")
    starting = [r for r in records if r["msg"] == "shippy-gui starting"]
    assert len(starting) == 1
    assert starting[0]["level"] == "INFO"
    assert starting[0]["version"] == "0.1.0+gabc1234"
    assert starting[0]["data"]["version"] == "0.1.0+gabc1234"
    # INFO: the error log holds warnings and errors only.
    assert read_jsonl(app_log_dir / "errors-shippy-gui.jsonl") == []


def test_start_logging_twice_adds_nothing(app_log_dir):
    log.start_logging(log.CLI_APP)
    handlers = len(logging.getLogger().handlers)
    hook = sys.excepthook

    log.start_logging(log.CLI_APP)

    assert len(logging.getLogger().handlers) == handlers
    assert sys.excepthook is hook
    logging.getLogger("x").error("once")
    assert len(read_jsonl(app_log_dir / "errors-shippy.jsonl")) == 1


def _raise(exc: BaseException):
    try:
        raise exc
    except BaseException:  # pylint: disable=broad-exception-caught
        return sys.exc_info()


def test_uncaught_exception_is_logged_and_still_shown(app_log_dir):
    shown = mock.Mock()
    sys.excepthook = shown
    log.start_logging(log.CLI_APP)

    sys.excepthook(*_raise(RuntimeError("boom")))

    shown.assert_called_once()
    errors = read_jsonl(app_log_dir / "errors-shippy.jsonl")
    assert [(e["level"], e["msg"]) for e in errors] == [
        ("CRITICAL", "uncaught exception")
    ]
    assert "RuntimeError: boom" in errors[0]["exc"]


def test_ctrl_c_is_shown_but_not_logged(app_log_dir):
    shown = mock.Mock()
    sys.excepthook = shown
    log.start_logging(log.CLI_APP)

    sys.excepthook(*_raise(KeyboardInterrupt()))

    shown.assert_called_once()
    assert read_jsonl(app_log_dir / "errors-shippy.jsonl") == []


def test_uncaught_exception_in_a_thread_is_logged_and_still_shown(app_log_dir):
    shown = mock.Mock()
    threading.excepthook = shown
    log.start_logging(log.CLI_APP)

    def fail():
        raise ValueError("in a thread")

    thread = threading.Thread(target=fail, name="worker-1")
    thread.start()
    thread.join()

    shown.assert_called_once()
    errors = read_jsonl(app_log_dir / "errors-shippy.jsonl")
    assert [(e["level"], e["msg"]) for e in errors] == [
        ("CRITICAL", "uncaught exception in thread worker-1")
    ]
    assert "ValueError: in a thread" in errors[0]["exc"]
