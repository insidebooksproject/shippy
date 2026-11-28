"""What the volunteer is told after a label fails to print, or might have."""

import pathlib
from types import SimpleNamespace
from unittest import mock

import pytest

from shippy.cli import app as cli, labels

LOG_DIR = pathlib.Path("logs")
SHIPMENT = SimpleNamespace(id="shp_1", tracking_code="9400111")
IDENTITY = labels.LabelIdentity(
    recipient_key="key", recipient_label="Jane Doe, 1 Unit Rd, Kenedy, TX"
)

# Wording that alarms volunteers or sends them to EasyPost; refunds are automatic.
ALARMING = ("NOT", "EasyPost", "do not create")


@pytest.fixture(name="printed")
def fixture_printed():
    """Capture questionary.print output from the CLI module."""
    with mock.patch("shippy.cli.app.questionary.print") as printer:
        yield printer


def printed_text(printer) -> str:
    """Join everything passed to a mocked questionary.print."""
    return "\n".join(str(call.args[0]) for call in printer.call_args_list)


def printed_styles(printer) -> set:
    """Every style passed to a mocked questionary.print."""
    return {call.kwargs.get("style") for call in printer.call_args_list}


def test_saved_label_notice_is_short_and_calm(printed):
    """A queued label gets a short notice with recipient and tracking."""
    path = pathlib.Path("to-print") / "9400111.png"
    cli.report_saved_label(SHIPMENT, path, mock.Mock(), LOG_DIR, IDENTITY)
    text = printed_text(printed)
    assert "The label didn't print. It was saved and will print automatically" in text
    assert "Recipient: Jane Doe, 1 Unit Rd, Kenedy, TX" in text
    assert "Tracking:  9400111" in text
    assert f"Printer logs: {LOG_DIR}" in text
    for phrase in ALARMING + ("refund", "to-print"):
        assert phrase not in text
    assert printed_styles(printed) == {cli.WARNING_STYLE}


def test_saved_label_notice_without_identity(printed):
    """Without a journal identity the notice still shows the tracking code."""
    cli.report_saved_label(SHIPMENT, pathlib.Path("x.png"), mock.Mock(), LOG_DIR)
    assert "Recipient: this recipient" in printed_text(printed)


def test_pending_count_is_a_plain_line(printed):
    """Labels waiting to print are counted on one line, without a banner."""
    with mock.patch.object(cli.labels, "pending_labels", return_value=[1, 2]):
        cli.report_pending_labels()
    printed.assert_called_once_with(
        "  2 label(s) waiting to print", style=cli.WARNING_STYLE
    )


def test_no_pending_labels_prints_nothing(printed):
    """Nothing is shown when no label is waiting."""
    with mock.patch.object(cli.labels, "pending_labels", return_value=[]):
        cli.report_pending_labels()
    printed.assert_not_called()


def test_uncertain_job_says_create_it_again(printed):
    """A job the queue could not confirm: check, else create it again."""
    result = SimpleNamespace(
        outcome=SimpleNamespace(ok=False, value="uncertain"), printer_name="DYMO"
    )
    cli.warn_if_job_not_ok(SHIPMENT, result, LOG_DIR)
    text = printed_text(printed)
    assert "It may not have printed." in text
    assert cli.CREATE_AGAIN_ADVICE in text
    assert f"Printer logs: {LOG_DIR}" in text
    for phrase in ALARMING:
        assert phrase not in text


def test_ok_job_prints_nothing(printed):
    """A job the queue reported as printed needs no warning."""
    result = SimpleNamespace(outcome=SimpleNamespace(ok=True, value="ok"))
    cli.warn_if_job_not_ok(SHIPMENT, result, LOG_DIR)
    printed.assert_not_called()


def test_unexpected_print_error_says_create_it_again(printed):
    """An unexpected print error: check, else create it again."""
    cli.warn_print_raised(SHIPMENT, RuntimeError("spooler hiccup"), LOG_DIR)
    text = printed_text(printed)
    assert "spooler hiccup" in text
    assert "It may not have printed." in text
    assert cli.CREATE_AGAIN_ADVICE in text
    assert f"Printer logs: {LOG_DIR}" in text
    for phrase in ALARMING:
        assert phrase not in text


def test_advice_wording():
    """The advice names the automatic refund."""
    assert cli.CREATE_AGAIN_ADVICE == (
        "Check the printer. If no label came out, create it again; the unused one "
        "is refunded automatically."
    )
