"""What shippy-gui logs, and at which level, for the error digest."""

import logging
import sys
from unittest import mock

import googlemaps  # type: ignore[import-not-found]
import pytest
from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget

from shippy.core import log
from shippy.gui import __main__ as gui_main
from shippy.gui.shipping_coordinators import (
    AddressLookupCoordinator,
    ShippingStatusPresenter,
)
from shippy.gui.widgets.address_form import AddressForm
from shippy.gui.widgets.autocomplete import GoogleMapsLookupWorker

from ..log_files import read_jsonl
from ..maps_errors import MAPS_KEY, TYPED, leaks, transport_error


@pytest.fixture(name="qapp", scope="module")
def fixture_qapp():
    """The test run's QApplication."""
    return QApplication.instance() or QApplication([])


@pytest.fixture(name="error_log")
def fixture_error_log(app_log_dir):
    """shippy-gui's real logging, in a temporary folder; its error log's path."""
    sys.excepthook = mock.Mock()  # Python's own hook would print to stderr.
    log.start_logging(log.GUI_APP)
    return app_log_dir / "errors-shippy-gui.jsonl"


def uncaught(error_log) -> list[str]:
    """The exception lines of the uncaught exceptions logged so far."""
    return [
        record["exc"].splitlines()[-1]
        for record in read_jsonl(error_log)
        if record["msg"] == "uncaught exception"
    ]


class Emitter(QObject):  # pylint: disable=too-few-public-methods
    """A signal to connect a failing slot to."""

    fired = Signal()


def test_exception_in_a_slot_is_logged(
    qapp, error_log
):  # pylint: disable=unused-argument
    emitter = Emitter()

    def slot():
        raise RuntimeError("slot failed")

    emitter.fired.connect(slot)
    emitter.fired.emit()

    assert uncaught(error_log) == ["RuntimeError: slot failed"]


def test_exception_in_a_qthread_is_logged(
    qapp, error_log
):  # pylint: disable=unused-argument
    class Worker(QThread):  # pylint: disable=too-few-public-methods
        """Fails on its own thread."""

        def run(self):
            raise RuntimeError("worker failed")

    worker = Worker()
    worker.start()
    assert worker.wait(5000)

    assert uncaught(error_log) == ["RuntimeError: worker failed"]


def test_exception_in_a_qrunnable_is_logged(
    qapp, error_log
):  # pylint: disable=unused-argument
    class Task(QRunnable):  # pylint: disable=too-few-public-methods
        """Fails in the thread pool."""

        def run(self):
            raise RuntimeError("task failed")

    pool = QThreadPool()
    pool.start(Task())
    assert pool.waitForDone(5000)

    assert uncaught(error_log) == ["RuntimeError: task failed"]


def test_main_starts_logging_before_qt_and_the_config(monkeypatch):
    calls = []
    monkeypatch.setattr(gui_main, "start_logging", calls.append)
    monkeypatch.setattr(
        gui_main, "QApplication", lambda _argv: calls.append("qt") or mock.Mock()
    )

    def stop(_path):
        calls.append("config")
        raise SystemExit(1)

    monkeypatch.setattr(gui_main, "_load_required_config", stop)

    with pytest.raises(SystemExit):
        gui_main.main()

    assert calls == ["shippy-gui", "qt", "config"]


def test_invalid_config_is_logged_as_error_without_its_values(
    tmp_path, monkeypatch, caplog
):
    """The dialog repeats the bad value; the log names the setting only."""
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        "[ibp]\nurl = not-a-url-SECRET\n\n"
        "[easypost]\napikey = EZTK-test\n\n[googlemaps]\napikey = gmaps-test\n"
    )
    shown = []
    monkeypatch.setattr(gui_main, "_show_config_error", shown.append)
    monkeypatch.setattr(gui_main, "_run_settings_dialog", lambda _path: False)

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit):
        gui_main._load_required_config(  # pylint: disable=protected-access
            str(config_path)
        )

    assert "not-a-url-SECRET" in shown[0]
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert errors[0].getMessage().startswith("config.ini is invalid or incomplete: ")
    assert "ibp.url" in errors[0].getMessage()
    assert "SECRET" not in errors[0].getMessage()


def test_new_config_is_not_an_error(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(gui_main, "_show_config_error", lambda _message: None)
    monkeypatch.setattr(gui_main, "_run_settings_dialog", lambda _path: False)

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit):
        gui_main._load_required_config(  # pylint: disable=protected-access
            str(tmp_path / "config.ini")
        )

    assert [r.levelname for r in caplog.records] == ["INFO"]


def _lookup(parser):
    status_label = QLabel()
    search_input = QLineEdit()
    search_input.setText("123 Main")
    coordinator = AddressLookupCoordinator(
        parent_widget=QWidget(),
        search_input=search_input,
        address_form=AddressForm(),
        status_presenter=ShippingStatusPresenter(status_label),
        get_address_parser=lambda: parser,
        get_address_completer=lambda: None,
    )
    return coordinator, status_label


@pytest.mark.parametrize(
    ("error", "described", "traceback"),
    [
        (googlemaps.exceptions.ApiError("REQUEST_DENIED"), "REQUEST_DENIED", False),
        (googlemaps.exceptions.Timeout(), "Timeout", False),
        (transport_error(), "TransportError (ConnectionError)", False),
        (KeyError("street_number"), "unexpectedly", True),
    ],
)
def test_failed_address_search_is_logged_as_error(
    qapp, caplog, error, described, traceback
):  # pylint: disable=unused-argument
    coordinator, status_label = _lookup(mock.Mock(side_effect=error))

    with (
        mock.patch("shippy.gui.shipping_coordinators.QMessageBox.critical") as box,
        caplog.at_level(logging.INFO, logger="shippy.gui"),
    ):
        coordinator.load_address()

    box.assert_called_once()
    assert status_label.text() == "Address search failed"
    assert [r.levelname for r in caplog.records] == ["ERROR"]
    record = caplog.records[0]
    # A Google Maps error's text holds the request URL: never in the log.
    assert (record.exc_info is not None) == traceback
    assert described in record.getMessage()
    assert not leaks(record.getMessage())
    assert "123 Main" not in record.getMessage()


def test_address_search_that_finds_nothing_is_not_an_error(
    qapp, caplog
):  # pylint: disable=unused-argument
    coordinator, _ = _lookup(mock.Mock(return_value=None))

    with (
        mock.patch("shippy.gui.shipping_coordinators.QMessageBox.warning") as box,
        caplog.at_level(logging.INFO, logger="shippy.gui"),
    ):
        coordinator.load_address()

    box.assert_called_once()
    assert [r.levelname for r in caplog.records] == ["INFO"]
    assert "123 Main" not in caplog.records[0].getMessage()


def test_address_search_without_google_maps_is_logged_as_error(
    qapp, caplog
):  # pylint: disable=unused-argument
    coordinator, _ = _lookup(None)

    with (
        mock.patch("shippy.gui.shipping_coordinators.QMessageBox.critical") as box,
        caplog.at_level(logging.INFO, logger="shippy.gui"),
    ):
        coordinator.load_address()

    box.assert_called_once()
    assert [r.levelname for r in caplog.records] == ["ERROR"]


@pytest.mark.parametrize(
    ("error", "level"),
    [
        (transport_error("/maps/api/place/autocomplete/json"), "WARNING"),
        (
            googlemaps.exceptions.ApiError("REQUEST_DENIED", f"bad key {MAPS_KEY}"),
            "ERROR",
        ),
    ],
)
def test_failed_address_suggestions_reach_the_error_log_without_key_or_input(
    qapp, error_log, error, level
):  # pylint: disable=unused-argument
    """A Wi-Fi blip or a revoked key while a volunteer types in the search."""
    gmaps = mock.Mock()
    gmaps.places_autocomplete.side_effect = error
    worker = GoogleMapsLookupWorker(gmaps, TYPED, request_id=1)
    emitted = []
    worker.error_occurred.connect(lambda *args: emitted.append(args))

    worker.run()  # On this thread: the lookup itself, not the QThread.

    assert len(emitted) == 1 and not leaks(emitted[0][1])
    text = error_log.read_text("utf-8")
    assert not leaks(text)
    records = read_jsonl(error_log)
    assert [r["level"] for r in records] == [level]
    assert records[0]["msg"].startswith("Google Maps address suggestions failed: ")
