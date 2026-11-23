"""Tests for the CLI address generators and main flow (no EasyPost calls)."""

import datetime
import sys
from unittest import mock
from urllib.parse import quote

import easypost  # type: ignore
import pytest

from shippy import cli
from shippy.models import Config

from .conftest import BASE_URL, SHIPPING_SETTINGS, UNIT, request_address

NOW = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)

EXPECTED_INMATE_ADDRESS = {
    "name": "Jane Doe #00012345",
    "street1": "Rt 2 Box 4400",
    "street2": "",
    "city": "Gatesville",
    "state": "TX",
    "zipcode": "76597",
}


@pytest.fixture(name="config")
def fixture_config():
    """A minimal valid config pointing at the fake server."""
    return Config.model_validate(
        {
            "ibp": {"url": BASE_URL},
            "easypost": {"apikey": "EZTK-test"},
            "googlemaps": {"apikey": "gmaps-test"},
        }
    )


@pytest.fixture(name="printed")
def fixture_printed():
    """Capture questionary.print output from the CLI module."""
    with mock.patch("shippy.cli.questionary.print") as printer:
        yield printer


def printed_text(printer) -> str:
    """Join everything passed to a mocked questionary.print."""
    return "\n".join(str(call.args[0]) for call in printer.call_args_list)


def run_individual(config, request_ids, weights=(3,), confirm=False):
    """Drive the individual generator with scripted prompts; return one item."""
    with (
        mock.patch("shippy.cli.console.query_request_id", side_effect=request_ids),
        mock.patch("shippy.cli.console.query_weight", side_effect=list(weights)),
        mock.patch("shippy.cli.console.query_small_box") as box_question,
        mock.patch("shippy.cli.console.confirm_tossed", return_value=confirm) as ask,
    ):
        item = next(cli.generate_addresses_individual(config))
    box_question.assert_not_called()
    return item, ask


@pytest.mark.parametrize("weight", [1, 4, 12])
def test_individual_always_declares_small_box(http, config, weight):
    """Individual mode declares the small box at any weight, without asking."""
    http.add("inmates/by-request/98765/address", request_address())
    (_, got_weight, small_box, _), _ = run_individual(config, [98765], weights=[weight])
    assert got_weight == weight
    assert small_box is True


def test_individual_legacy_barcode(http, config, printed):
    """A legacy integer label is addressed via the by-request endpoint."""
    http.add("inmates/by-request/98765/address", request_address())
    (to_addr, weight, _, _), ask = run_individual(config, [98765])
    assert to_addr == EXPECTED_INMATE_ADDRESS
    assert weight == 3
    assert http.calls == [f"{BASE_URL}/inmates/by-request/98765/address"]
    ask.assert_not_called()
    assert "Jane Doe #00012345 at Hughes" in printed_text(printed)


def test_individual_new_barcode_passes_request_index(http, config, printed):
    """A TEX-ID-INDEX label uses the request-index address endpoint."""
    path = "inmates/Texas/12345/requests/4/address"
    http.add(path, request_address(request_index=4))
    (to_addr, _, _, _), _ = run_individual(config, [("TEX", 12345, 4)])
    assert to_addr == EXPECTED_INMATE_ADDRESS
    assert http.calls == [f"{BASE_URL}/{path}"]
    assert "Warning" not in printed_text(printed)


@pytest.mark.parametrize("status_code", [404, 409])
def test_individual_server_error_skips_to_next_label(
    http, config, printed, status_code
):
    """A 404/409 is shown to the volunteer and the next label is asked for."""
    detail = "Texas inmate #00012345 is not assigned to a unit; cannot address"
    http.add("inmates/by-request/1/address", {"detail": detail}, status_code)
    http.add("inmates/by-request/98765/address", request_address())
    (to_addr, _, _, _), _ = run_individual(config, [1, 98765])
    assert to_addr == EXPECTED_INMATE_ADDRESS
    assert detail in printed_text(printed)


def test_individual_tossed_declined_skips(http, config, printed):
    """Declining a tossed request buys nothing and moves to the next label."""
    http.add("inmates/by-request/1/address", request_address(action="Tossed"))
    http.add("inmates/by-request/98765/address", request_address())
    (to_addr, _, _, _), ask = run_individual(config, [1, 98765], confirm=False)
    assert to_addr == EXPECTED_INMATE_ADDRESS
    ask.assert_called_once()
    text = printed_text(printed)
    assert "TOSSED" in text
    assert text.count("Skipped; no postage bought.") == 1


def test_individual_tossed_confirmed_ships(http, config, printed):
    """Confirming a tossed request lets it ship."""
    http.add("inmates/by-request/1/address", request_address(action="Tossed"))
    (to_addr, _, _, _), ask = run_individual(config, [1], confirm=True)
    assert to_addr == EXPECTED_INMATE_ADDRESS
    ask.assert_called_once()
    assert "TOSSED" in printed_text(printed)


@pytest.mark.parametrize(
    "fetched, stale",
    [
        (None, True),
        ("2026-06-01T00:00:00+00:00", True),
        ("2026-09-01T00:00:00+00:00", False),
        ("2026-09-01T00:00:00", False),
        ("not a date", True),
    ],
)
def test_unit_is_stale(fetched, stale):
    """Units fetched over 90 days ago (or never) count as stale."""
    assert cli.unit_is_stale(fetched, NOW) is stale


def test_stale_unit_warns_without_blocking(printed):
    """A stale unit (older backend, no inmate_status) warns but still ships."""
    address = request_address(datetime_fetched=None)
    assert cli.check_request_address(address, now=NOW) is True
    assert (
        "Warning: this inmate's unit has not been checked in over 90 days and may "
        "be out of date." in printed_text(printed)
    )


def test_current_inmate_never_warns_about_unit(printed):
    """The backend just re-checked the inmate with TDCJ: no unit-age warning."""
    address = request_address(inmate_status="current", datetime_fetched=None)
    assert cli.check_request_address(address, now=NOW) is True
    text = printed_text(printed)
    assert "Warning" not in text
    assert "out of date" not in text


@pytest.mark.parametrize("action", ["Filled", "Tossed"])
def test_not_listed_inmate_is_not_shipped(printed, action):
    """TDCJ no longer lists the inmate: nothing is asked or bought."""
    address = request_address(inmate_status="not_listed", action=action)
    with mock.patch("shippy.cli.console.confirm_tossed") as ask:
        assert cli.check_request_address(address, now=NOW) is False
    ask.assert_not_called()
    text = printed_text(printed)
    assert (
        "TDCJ no longer lists this inmate (they may have been released). "
        "No postage bought; set this package aside." in text
    )
    assert text.lower().count("no postage bought") == 1


def test_unverified_stale_unit_says_tdcj_was_not_reached(printed):
    """The backend couldn't reach TDCJ and the unit is old: say how old."""
    address = request_address(
        inmate_status="unverified", datetime_fetched="2026-06-01T00:00:00+00:00"
    )
    assert cli.check_request_address(address, now=NOW) is True
    assert (
        "Warning: couldn't re-check this inmate with TDCJ; their unit was last "
        "checked 122 days ago and may be out of date." in printed_text(printed)
    )


def test_unverified_never_fetched_unit(printed):
    """An unverified inmate whose unit was never fetched still warns."""
    address = request_address(inmate_status="unverified", datetime_fetched=None)
    assert cli.check_request_address(address, now=NOW) is True
    assert "their unit has never been checked" in printed_text(printed)


def test_unverified_fresh_unit_does_not_warn(printed):
    """TDCJ unreachable but the unit was checked recently: no warning."""
    address = request_address(
        inmate_status="unverified", datetime_fetched="2026-09-01T00:00:00+00:00"
    )
    assert cli.check_request_address(address, now=NOW) is True
    assert "Warning" not in printed_text(printed)


def test_individual_not_listed_skips_to_next_label(http, config, printed):
    """A released inmate's label is skipped once; the next label ships."""
    http.add(
        "inmates/by-request/1/address", request_address(inmate_status="not_listed")
    )
    http.add("inmates/by-request/98765/address", request_address())
    (to_addr, _, _, _), ask = run_individual(config, [1, 98765])
    assert to_addr == EXPECTED_INMATE_ADDRESS
    ask.assert_not_called()
    text = printed_text(printed)
    assert "TDCJ no longer lists this inmate" in text
    assert text.lower().count("no postage bought") == 1


def test_bulk_uses_server_recipient_name(http, config, printed):
    """Bulk mode addresses units to the server's unit recipient name."""
    http.add("shipping-settings", SHIPPING_SETTINGS)
    federal_hughes = dict(UNIT, jurisdiction="Federal")
    http.add("units", [UNIT, federal_hughes])
    http.add("units/Federal/Hughes", federal_hughes)

    with (
        mock.patch(
            "shippy.cli.console.query_unit", side_effect=["HUGHES (FEDERAL)"]
        ) as query_unit,
        mock.patch("shippy.cli.console.query_weight", side_effect=[20]),
        mock.patch("shippy.cli.console.query_small_box", return_value=False),
    ):
        to_addr, weight, _, _ = next(cli.generate_addresses_bulk(config))

    assert set(query_unit.call_args.args[0]) == {"HUGHES (TEXAS)", "HUGHES (FEDERAL)"}
    assert to_addr == dict(EXPECTED_INMATE_ADDRESS, name="ATTN: MAILROOM STAFF")
    assert weight == 20
    assert "error" not in printed_text(printed)


def test_bulk_unit_not_found_skips(http, config, printed):
    """A unit that vanished on the server is reported, then re-prompted."""
    http.add("shipping-settings", SHIPPING_SETTINGS)
    http.add("units", [UNIT, dict(UNIT, name="Gone")])
    http.add("units/Texas/Gone", {"detail": "Unit not found."}, 404)
    http.add("units/Texas/Hughes", UNIT)

    with (
        mock.patch("shippy.cli.console.query_unit", side_effect=["GONE", "HUGHES"]),
        mock.patch("shippy.cli.console.query_weight", side_effect=[20]),
        mock.patch("shippy.cli.console.query_small_box", return_value=False),
    ):
        to_addr, _, _, _ = next(cli.generate_addresses_bulk(config))

    assert to_addr["name"] == "ATTN: MAILROOM STAFF"
    assert "Unit not found." in printed_text(printed)


def test_individual_scanned_code_tags_shipment_with_request_code(http, config):
    """A scanned TEX- label tags the shipment with the server's request code."""
    path = "inmates/Texas/12345/requests/2/address"
    http.add(path, request_address(request_index=2, code="TEX-00012345-2"))
    (_, _, _, reference), _ = run_individual(config, [("TEX", 12345, 2)])
    assert reference == "ibp1:req:TEX-00012345-2"


def test_individual_legacy_id_tags_shipment_with_server_code(http, config):
    """A typed legacy request id still tags with the canonical request code."""
    http.add("inmates/by-request/98765/address", request_address(code="TEX-00012345-1"))
    (_, _, _, reference), _ = run_individual(config, [98765])
    assert reference == "ibp1:req:TEX-00012345-1"


def test_individual_without_server_code_tags_shipment_manual(http, config):
    """An older server sends no request code: tag as manual, never invent one."""
    body = request_address()
    del body["code"]
    http.add("inmates/by-request/98765/address", body)
    (to_addr, _, _, reference), _ = run_individual(config, [98765])
    assert reference == "ibp1:manual"
    assert to_addr == EXPECTED_INMATE_ADDRESS


def test_bulk_tags_shipment_with_unit_name_unchanged(http, config):
    """A bulk box is tagged with the unit's jurisdiction and name as given."""
    unit = dict(UNIT, name="Coyote's Bend St. Jail")
    http.add("shipping-settings", SHIPPING_SETTINGS)
    http.add("units", [unit])
    http.add(f"units/Texas/{quote(unit['name'], safe='')}", unit)

    with (
        mock.patch(
            "shippy.cli.console.query_unit", side_effect=["COYOTE'S BEND ST. JAIL"]
        ),
        mock.patch("shippy.cli.console.query_weight", side_effect=[20]),
        mock.patch("shippy.cli.console.query_small_box", return_value=False),
    ):
        _, _, _, reference = next(cli.generate_addresses_bulk(config))

    assert reference == "ibp1:unit:Texas:Coyote's Bend St. Jail"


def test_manual_tags_shipment_manual(config):
    """A typed address is tagged as manual."""
    typed = dict(EXPECTED_INMATE_ADDRESS, name="Pat Example")
    with (
        mock.patch("shippy.cli.googlemaps.Client"),
        mock.patch("shippy.cli.console.query_address", return_value=typed),
        mock.patch("shippy.cli.console.query_weight", return_value=2),
        mock.patch("shippy.cli.console.query_small_box", return_value=False),
    ):
        to_addr, _, _, reference = next(cli.generate_addresses_manual(config))

    assert to_addr == typed
    assert reference == "ibp1:manual"


def test_main_return_address_from_shipping_settings(http, tmp_path, printed):
    """main() builds the return address from /shipping-settings, not config."""
    http.add("shipping-settings", SHIPPING_SETTINGS)
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        f"[ibp]\nurl = {BASE_URL}\napikey = leftover-legacy-key\n\n"
        "[easypost]\napikey = EZTK-test\n\n[googlemaps]\napikey = gmaps-test\n"
    )

    argv = ["shippy", "--config", str(config_path), "manual"]
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch("shippy.cli.easypost.EasyPostClient") as client,
        mock.patch("shippy.cli.shipping.build_address") as build_address,
        mock.patch("shippy.cli.generate_addresses_manual", return_value=iter([])),
        mock.patch("shippy.cli.load_logo"),
        # Real discovery would depend on this machine's printers.
        mock.patch("shippy.cli.printer_gate.wait_for_printer"),
    ):
        cli.main()

    build_address.assert_called_once_with(
        client.return_value, **SHIPPING_SETTINGS["return_address"]
    )
    assert printed.called


@pytest.mark.parametrize("typed", [True, False])
def test_verify_address_failure_shown_only_for_typed(printed, typed):
    """Only a typed (manual) address that fails verification warns the volunteer."""
    client = mock.Mock()
    client.address.verify.side_effect = easypost.errors.InvalidRequestError("bad")
    cli.verify_address(client, mock.Mock(id="adr_1"), typed=typed)
    client.address.verify.assert_called_once_with("adr_1")
    shown = "Failed to verify address" in printed_text(printed)
    assert shown is typed


def test_verify_address_success_is_quiet(printed):
    """A verified address shows no warning."""
    client = mock.Mock()
    cli.verify_address(client, mock.Mock(id="adr_1"), typed=True)
    assert "Failed to verify" not in printed_text(printed)


def test_only_manual_mode_has_typed_addresses():
    """Individual and bulk addresses come from the IBP server."""
    assert cli.TYPED_ADDRESS_MODES == {"manual"}
