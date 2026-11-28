"""Tests for the logging names and setup both apps share."""

import pathlib
from unittest import mock

from shippy.core import log


def test_app_names_are_the_ones_existing_logs_and_journals_use():
    """printer-<app>.* file names and the journal's app= values never change."""
    assert (log.CLI_APP, log.GUI_APP, log.DIAG_APP) == ("shippy", "shippy-gui", "diag")


def test_shared_loggers_reach_ibp_printings_log_files():
    assert log.get_logger("shippy.core.x").name == "ibp_printing.shippy.core.x"


def test_configure_logging_never_logs_to_the_console():
    with mock.patch(
        "shippy.core.log.ibp_printing.configure_logging",
        return_value=pathlib.Path("logs"),
    ) as configure:
        assert log.configure_logging(log.GUI_APP) == pathlib.Path("logs")

    configure.assert_called_once_with(app="shippy-gui", console=False)
