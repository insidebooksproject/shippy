"""What the CLI logs, and at which level, for the error digest."""

import logging
import sys
from unittest import mock

import easypost  # type: ignore
import pytest

from shippy.cli import app as cli
from shippy.core.ibp_server import ServerError

from ..conftest import BASE_URL, request_address

LOGGER = "ibp_printing.shippy"


def test_main_starts_logging_before_anything_else(tmp_path):
    """The error log and hooks are set up before the config is even read."""
    calls = []
    argv = ["shippy", "--config", str(tmp_path / "config.ini"), "bulk"]
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch.object(cli, "start_logging", side_effect=calls.append),
        mock.patch.object(cli, "ship", side_effect=lambda _args: calls.append("ship")),
    ):
        cli.main()

    assert calls == ["shippy", "ship"]


def test_unexpected_error_is_logged_critical_and_exits_1(tmp_path, caplog):
    """A missing or broken config.ini reaches the last-resort handler."""
    argv = ["shippy", "--config", str(tmp_path / "missing.ini"), "bulk"]
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch.object(cli, "configure_logging", return_value=tmp_path),
        mock.patch.object(cli.questionary, "print") as printed,
        mock.patch("builtins.input", return_value=""),
        caplog.at_level(logging.ERROR, logger=LOGGER),
        pytest.raises(SystemExit) as exited,
    ):
        cli.main()

    assert exited.value.code == 1
    assert [r.levelname for r in caplog.records] == ["CRITICAL"]
    assert caplog.records[0].exc_info is not None
    assert "didn't expect" in printed.call_args.args[0]


def test_diagnose_printer_does_not_start_the_shipping_logs(tmp_path):
    with (
        mock.patch.object(sys, "argv", ["shippy", "diagnose-printer"]),
        mock.patch.object(cli, "start_logging") as start,
        mock.patch.object(cli, "configure_logging", return_value=tmp_path) as diag,
        mock.patch.object(cli, "discover"),
        mock.patch.object(cli, "get_backend"),
        mock.patch.object(cli, "build_report", return_value="report"),
        mock.patch("builtins.print"),
    ):
        cli.main()

    diag.assert_called_once_with(cli.DIAG_APP)
    start.assert_not_called()


@pytest.mark.parametrize(
    ("request_id", "expected"),
    [(("tex", 12345, 0), "TEX-00012345-0"), (98765, "request 98765")],
)
def test_request_label_is_the_code_not_a_name(request_id, expected):
    assert cli.request_label(request_id) == expected


def test_server_refusal_is_shown_and_logged_as_info(caplog):
    """A 4xx (e.g. an unknown request code) is a normal answer, not an error."""
    with (
        mock.patch.object(cli.questionary, "print") as printed,
        caplog.at_level(logging.DEBUG, logger=LOGGER),
    ):
        cli.report_server_refusal(ServerError(404, "Request not found."), "request 7")

    assert printed.call_args.args[0] == "  Request not found."
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("INFO", "IBP server answered 404 for request 7: Request not found.")
    ]


def test_not_listed_inmate_is_logged_by_code_as_info(caplog):
    """Handled (nothing bought), and the log names the request, not the inmate."""
    address = request_address(inmate_status="not_listed")
    with (
        mock.patch.object(cli.questionary, "print"),
        caplog.at_level(logging.DEBUG, logger=LOGGER),
    ):
        assert cli.check_request_address(address) is False

    assert [r.levelname for r in caplog.records] == ["INFO"]
    message = caplog.records[0].getMessage()
    assert "TEX-00012345-0" in message
    assert "Jane" not in message and "Doe" not in message


def test_unverified_return_address_is_shown_and_logged_as_warning(tmp_path, caplog):
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        f"[ibp]\nurl = {BASE_URL}\n\n"
        "[easypost]\napikey = EZTK-test\n\n[googlemaps]\napikey = gmaps-test\n"
    )
    client = mock.Mock()
    client.address.verify.side_effect = easypost.errors.InvalidRequestError("bad")
    server = mock.Mock()
    server.return_address.return_value = {}
    with (
        mock.patch.object(
            sys, "argv", ["shippy", "--config", str(config_path), "--preview", "bulk"]
        ),
        mock.patch.object(cli, "configure_logging", return_value=tmp_path),
        mock.patch.object(cli.easypost, "EasyPostClient", return_value=client),
        mock.patch.object(cli.Server, "from_config", return_value=server),
        mock.patch.object(cli.postage, "build_address") as build_address,
        mock.patch.object(cli, "generate_addresses_bulk", return_value=iter([])),
        mock.patch.object(cli, "load_logo", return_value=None),
        mock.patch.object(cli, "report_pending_labels"),
        mock.patch.object(cli.questionary, "print") as printed,
        caplog.at_level(logging.WARNING, logger=LOGGER),
    ):
        build_address.return_value.id = "adr_from"
        cli.main()

    shown = "\n".join(str(call.args[0]) for call in printed.call_args_list)
    assert "Failed to verify return address" in shown
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("WARNING", "could not verify the return address adr_from: bad")
    ]
