"""Drive cli.main() through shipments with mocked prompts and EasyPost."""

import os
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import easypost  # type: ignore
import requests

from shippy.cli import app as cli, console
from shippy.core.ibp_server import ServerError

BASE_CONFIG = """\
[ibp]
url = http://ibp.example/
apikey = ibp-key

[easypost]
apikey = ep-key

[googlemaps]
apikey = gm-key
"""

ADDRESS = {
    "name": "ATTN: MAILROOM STAFF",
    "street1": "1 Unit Rd",
    "city": "Kenedy",
    "state": "TX",
    "zipcode": "78119",
}


class StopShipping(BaseException):
    """Ends the otherwise endless prompt loop.

    A BaseException, like KeyboardInterrupt, so that main()'s last-resort
    handler for unexpected errors lets it through.
    """


def write_config(text: str) -> pathlib.Path:
    """Write a config file that is removed after the test run."""
    handle, name = tempfile.mkstemp(suffix=".ini")
    with os.fdopen(handle, "w") as stream:
        stream.write(text)
    return pathlib.Path(name)


class MainLoopCase(unittest.TestCase):
    """Two bulk shipments: a small box, then a large one."""

    def setUp(self):
        path = write_config(BASE_CONFIG)
        self.addCleanup(path.unlink)

        self.client = mock.Mock()
        quote = mock.Mock(
            id="shp_1",
            rates=[SimpleNamespace(carrier="USPS", service="LibraryMail", rate="9.12")],
        )
        quote.lowest_rate.return_value = quote.rates[0]
        self.client.shipment.create.return_value = quote

        self.server = server = mock.Mock()
        server.return_address.return_value = dict(ADDRESS)
        server.shipping_settings.return_value = {"unit_recipient_name": ADDRESS["name"]}
        server.units.return_value = [{"jurisdiction": "Texas", "name": "Connally"}]
        server.unit.side_effect = lambda _jurisdiction, _name: dict(ADDRESS)

        patches = [
            mock.patch(
                "sys.argv", ["shippy", "--config", str(path), "--preview", "bulk"]
            ),
            mock.patch.object(cli, "configure_logging", return_value=pathlib.Path(".")),
            mock.patch.object(cli.easypost, "EasyPostClient", return_value=self.client),
            mock.patch.object(cli.Server, "from_config", return_value=server),
            mock.patch.object(cli, "load_logo", return_value=None),
            mock.patch.object(cli.label_journal, "record_purchase", return_value=None),
            mock.patch.object(cli, "report_pending_labels"),
            mock.patch.object(console.questionary, "print"),
            mock.patch.object(
                console,
                "query_unit",
                side_effect=["CONNALLY", "CONNALLY", StopShipping],
            ),
            mock.patch.object(console, "query_weight", side_effect=[10, 5]),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        ship_label = mock.patch.object(cli, "ship_label")
        self.ship_label = ship_label.start()
        self.addCleanup(ship_label.stop)
        typed = mock.patch("builtins.input", return_value="")
        self.input = typed.start()
        self.addCleanup(typed.stop)
        printed = mock.patch.object(cli.questionary, "print")
        self.printed = printed.start()
        self.addCleanup(printed.stop)
        confirm = mock.patch.object(console.questionary, "confirm")
        self.confirm = confirm.start()
        self.addCleanup(confirm.stop)
        self.confirm.return_value.ask.side_effect = [True, False]

    def printed_text(self) -> str:
        """Everything shown to the volunteer."""
        return "\n".join(str(call.args[0]) for call in self.printed.call_args_list)


class MainLoopTests(MainLoopCase):
    """Both shipments go through."""

    def test_box_answer_and_weight_reach_easypost_per_shipment(self):
        with self.assertRaises(StopShipping):
            cli.main()

        parcels = [call.kwargs for call in self.client.parcel.create.call_args_list]
        self.assertEqual(len(parcels), 2)
        declared = [
            (p["weight"], p["length"], p["width"], p["height"]) for p in parcels
        ]
        self.assertEqual(
            declared,
            [
                (160.0, 12.0, 12.0, 12.0),  # 10 lb, answered Yes: small box
                (80.0, 20.0, 14.0, 10.0),  # 5 lb, answered No: large box
            ],
        )
        self.assertEqual(self.client.shipment.buy.call_count, 2)

    def test_bulk_shipments_are_tagged_with_the_unit(self):
        with self.assertRaises(StopShipping):
            cli.main()

        references = [
            call.kwargs.get("reference")
            for call in self.client.shipment.create.call_args_list
        ]
        self.assertEqual(references, ["ibp1:unit:Texas:Connally"] * 2)

    def test_unverified_server_address_ships_without_warning(self):
        """Bulk addresses come from the IBP server: a failed check is not shown."""
        self.client.address.verify.side_effect = easypost.errors.InvalidRequestError(
            "address not found"
        )
        with self.assertRaises(StopShipping):
            cli.main()

        # The return address once, then each of the two unit addresses.
        self.assertEqual(self.client.address.verify.call_count, 3)
        self.assertEqual(self.client.shipment.buy.call_count, 2)
        self.assertNotIn("Failed to verify address", self.printed_text())
        # The return address's failed check only warns; it isn't retried.
        self.assertIn(
            "Failed to verify return address, consider double-checking before "
            "shipping.",
            self.printed_text(),
        )


class ApiErrorTests(MainLoopCase):
    """An EasyPost or IBP server failure skips one package, not the session."""

    def run_main(self):
        """Run both shipments, expecting one ERROR log record."""
        with self.assertLogs("ibp_printing.shippy", "ERROR") as logs:
            with self.assertRaises(StopShipping):
                cli.main()
        self.assertEqual(len(logs.records), 1)
        self.assertIsNotNone(logs.records[0].exc_info)
        self.client.shipment.refund.assert_not_called()

    def test_quote_failure_skips_the_package(self):
        self.client.shipment.create.side_effect = [
            easypost.errors.InternalServerError("try later", http_status=500),
            self.client.shipment.create.return_value,
        ]
        self.run_main()

        self.assertIn(cli.NOT_BOUGHT_ADVICE, self.printed_text())
        self.assertNotIn(cli.MAYBE_BOUGHT_ADVICE, self.printed_text())
        # The second package is still quoted and bought.
        self.assertEqual(self.client.shipment.create.call_count, 2)
        self.assertEqual(self.client.shipment.buy.call_count, 1)
        self.assertEqual(self.ship_label.call_count, 1)

    def test_no_usps_rate_skips_the_package(self):
        quote = self.client.shipment.create.return_value
        quote.lowest_rate.side_effect = [
            easypost.errors.FilteringError("No rates found."),
            quote.rates[0],
        ]
        self.run_main()

        self.assertIn("No USPS rate was quoted", self.printed_text())
        self.assertIn(cli.NOT_BOUGHT_ADVICE, self.printed_text())
        self.assertEqual(self.client.shipment.buy.call_count, 1)

    def test_buy_timeout_may_have_bought(self):
        self.client.shipment.buy.side_effect = [
            easypost.errors.TimeoutError("Request timed out."),
            mock.DEFAULT,
        ]
        self.run_main()

        self.assertIn(cli.MAYBE_BOUGHT_ADVICE, self.printed_text())
        self.assertNotIn(cli.NOT_BOUGHT_ADVICE, self.printed_text())
        # Nothing is retried or reconciled: the next package is bought as usual.
        self.assertEqual(self.client.shipment.buy.call_count, 2)
        self.assertEqual(self.ship_label.call_count, 1)

    def test_buy_payment_refused_asks_for_a_coordinator(self):
        self.client.shipment.buy.side_effect = [
            easypost.errors.PaymentError("Insufficient funds.", http_status=402),
            mock.DEFAULT,
        ]
        self.run_main()

        self.assertIn("Insufficient funds.", self.printed_text())
        self.assertIn(cli.CANT_PAY_ADVICE, self.printed_text())
        self.assertNotIn(cli.NOT_BOUGHT_ADVICE, self.printed_text())
        self.assertNotIn(cli.MAYBE_BOUGHT_ADVICE, self.printed_text())
        self.assertEqual(self.ship_label.call_count, 1)

    def test_buy_refused_bought_nothing(self):
        self.client.shipment.buy.side_effect = [
            easypost.errors.InvalidRequestError("Rate expired.", http_status=422),
            mock.DEFAULT,
        ]
        self.run_main()

        self.assertIn(cli.NOT_BOUGHT_ADVICE, self.printed_text())
        self.assertNotIn(cli.MAYBE_BOUGHT_ADVICE, self.printed_text())
        self.assertEqual(self.ship_label.call_count, 1)

    def test_unit_fetch_network_error_skips_the_package(self):
        self.server.unit.side_effect = [
            requests.ConnectionError("no route to host"),
            dict(ADDRESS),
        ]
        self.run_main()

        self.assertIn("Can't reach the IBP server.", self.printed_text())
        self.assertIn(cli.NOT_BOUGHT_ADVICE, self.printed_text())
        self.assertEqual(self.client.shipment.buy.call_count, 1)

    def test_return_address_failure_waits_for_enter(self):
        self.server.return_address.side_effect = [
            requests.ConnectionError("no route to host"),
            dict(ADDRESS),
        ]
        self.run_main()

        self.assertIn(
            "Can't reach the IBP server. Check the internet connection, then "
            "press Enter to try again (Ctrl+C to quit).",
            self.printed_text(),
        )
        self.input.assert_called_once()
        self.assertEqual(self.client.shipment.buy.call_count, 2)

    def test_return_address_rejected_by_easypost_asks_for_a_coordinator(self):
        self.client.address.create.side_effect = [
            easypost.errors.InvalidRequestError("Invalid zip.", http_status=422),
            mock.DEFAULT,
            mock.DEFAULT,
            mock.DEFAULT,
        ]
        self.run_main()

        self.assertIn(
            "EasyPost rejected the return address from the IBP server: Invalid "
            "zip. Tell a coordinator; press Enter to try again (Ctrl+C to quit).",
            self.printed_text(),
        )
        self.assertNotIn("Can't reach", self.printed_text())
        self.input.assert_called_once()
        self.assertEqual(self.client.shipment.buy.call_count, 2)

    def test_return_address_refused_by_server_asks_for_a_coordinator(self):
        self.server.return_address.side_effect = [
            ServerError(404, "Not Found"),
            dict(ADDRESS),
        ]
        self.run_main()

        self.assertIn(
            "The IBP server turned down the request for the return address: Not "
            "Found. Tell a coordinator; press Enter to try again (Ctrl+C to quit).",
            self.printed_text(),
        )
        self.input.assert_called_once()

    def test_return_address_verify_timeout_waits_for_enter(self):
        self.client.address.verify.side_effect = [
            easypost.errors.TimeoutError("Request timed out."),
            mock.DEFAULT,
            mock.DEFAULT,
            mock.DEFAULT,
        ]
        self.run_main()

        self.assertIn("Can't reach EasyPost.", self.printed_text())
        self.input.assert_called_once()
        # The failed check, its retry, then each of the two unit addresses.
        self.assertEqual(self.client.address.verify.call_count, 4)
        self.assertEqual(self.client.shipment.buy.call_count, 2)

    def test_ctrl_c_at_return_address_retry_quits(self):
        self.server.return_address.side_effect = ServerError(404, "Not Found")
        self.input.side_effect = KeyboardInterrupt
        with self.assertLogs("ibp_printing.shippy", "ERROR"):
            with self.assertRaises(SystemExit) as exited:
                cli.main()

        self.assertEqual(exited.exception.code, 130)
        self.client.shipment.create.assert_not_called()


class UnexpectedErrorTests(MainLoopCase):
    """An error nothing else handles is logged, then shippy closes on Enter."""

    def test_unexpected_error_is_logged_and_waits_for_enter(self):
        self.ship_label.side_effect = RuntimeError("bug")
        with self.assertLogs("ibp_printing.shippy", "ERROR") as logs:
            with self.assertRaises(SystemExit) as exited:
                cli.main()

        self.assertEqual(exited.exception.code, 1)
        self.assertIsInstance(logs.records[-1].exc_info[1], RuntimeError)
        self.assertIn("shippy hit a problem it didn't expect", self.printed_text())
        self.input.assert_called_once()


class LoadConfigTests(unittest.TestCase):
    """cli.load_config() and the [parcel] section."""

    def load(self, text):
        path = write_config(text)
        self.addCleanup(path.unlink)
        return cli.load_config(path)

    def test_without_parcel_section_uses_defaults(self):
        parcel = self.load(BASE_CONFIG).parcel
        self.assertEqual(parcel.dimensions(False), (20.0, 14.0, 10.0))
        self.assertEqual(parcel.dimensions(True), (12.0, 12.0, 12.0))

    def test_parcel_section_overrides_box_sizes(self):
        parcel = self.load(
            BASE_CONFIG
            + "\n[parcel]\nlength = 18\nwidth = 14\nheight = 12\n"
            + "small_length = 18\nsmall_width = 12\nsmall_height = 8\n"
        ).parcel
        self.assertEqual(parcel.dimensions(False), (18.0, 14.0, 12.0))
        self.assertEqual(parcel.dimensions(True), (18.0, 12.0, 8.0))


if __name__ == "__main__":
    unittest.main()
