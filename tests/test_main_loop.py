"""Drive cli.main() through shipments with mocked prompts and EasyPost."""

import os
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import easypost  # type: ignore

from shippy import cli, console

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


class StopShipping(Exception):
    """Ends the otherwise endless prompt loop."""


def write_config(text: str) -> pathlib.Path:
    """Write a config file that is removed after the test run."""
    handle, name = tempfile.mkstemp(suffix=".ini")
    with os.fdopen(handle, "w") as stream:
        stream.write(text)
    return pathlib.Path(name)


class MainLoopTests(unittest.TestCase):
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

        server = mock.Mock()
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
            mock.patch.object(cli.labels, "record_purchase", return_value=None),
            mock.patch.object(cli, "report_pending_labels"),
            mock.patch.object(cli, "ship_label"),
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
        printed = mock.patch.object(cli.questionary, "print")
        self.printed = printed.start()
        self.addCleanup(printed.stop)
        confirm = mock.patch.object(console.questionary, "confirm")
        self.confirm = confirm.start()
        self.addCleanup(confirm.stop)
        self.confirm.return_value.ask.side_effect = [True, False]

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
        text = "\n".join(str(call.args[0]) for call in self.printed.call_args_list)
        self.assertNotIn("Failed to verify address", text)


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
