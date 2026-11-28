"""Tests for the EasyPost shipment and the reference that tags what it was for."""

from unittest import mock

import pytest

from shippy.core import postage


def test_request_reference_uses_server_code():
    address = {"code": "TEX-00012345-2", "request_id": 98765}
    assert postage.request_reference(address) == "ibp1:req:TEX-00012345-2"


@pytest.mark.parametrize(
    "address",
    [
        {},
        {"code": None},
        {"code": ""},
        {"code": 12345},
        {"code": "TEX-00012345-2\n"},
        {"code": "TEX 00012345 2"},
        {"code": "ibp1:req:TEX-1-0"},
        {"code": "TEX-" + "9" * 200 + "-0"},
        None,
        "not a mapping",
    ],
)
def test_request_reference_unexpected_code_is_manual(address):
    """Anything odd about the code tags the label manual instead of raising."""
    assert postage.request_reference(address) == postage.MANUAL_REFERENCE


@pytest.mark.parametrize(
    "jurisdiction, name",
    [
        ("Texas", "BETO"),
        ("Texas", "Coyote's Bend St. Jail"),
        ("Federal", "Pine Hollow F.C.I."),
    ],
)
def test_unit_reference_passes_name_through(jurisdiction, name):
    reference = postage.unit_reference(jurisdiction, name)
    assert reference == f"ibp1:unit:{jurisdiction}:{name}"


@pytest.mark.parametrize(
    "jurisdiction, name",
    [
        ("Texas", ""),
        ("Texas", "   "),
        ("Texas", None),
        (None, "BETO"),
        ("Tex:as", "BETO"),
        ("Texas", "Line\nBreak"),
        ("Texas", "Café"),
    ],
)
def test_unit_reference_unexpected_key_is_manual(jurisdiction, name):
    assert postage.unit_reference(jurisdiction, name) == postage.MANUAL_REFERENCE


def test_long_unit_name_is_cut_to_the_limit():
    name = "Long Unit Name " * 10
    reference = postage.unit_reference("Texas", name)
    assert len(reference) == postage.MAX_REFERENCE_LENGTH
    assert reference.startswith("ibp1:unit:Texas:Long Unit Name")


def test_realistic_long_unit_name_fits():
    name = "Bridgeport Pre-Parole Transfer Facility St. Annex"
    reference = postage.unit_reference("Federal", name)
    assert reference == f"ibp1:unit:Federal:{name}"


def quote_kwargs(**kwargs):
    """Call quote_shipment on a mock client; return shipment.create's kwargs."""
    client = mock.Mock()
    postage.quote_shipment(client, "from", "to", 48.0, (12.0, 12.0, 12.0), **kwargs)
    return client.shipment.create.call_args.kwargs


def test_quote_shipment_sends_reference():
    kwargs = quote_kwargs(reference="ibp1:manual")
    assert kwargs["reference"] == "ibp1:manual"
    assert kwargs["options"] == {"special_rates_eligibility": "USPS.LIBRARYMAIL"}


@pytest.mark.parametrize("extra", [{}, {"reference": None}, {"reference": ""}])
def test_quote_shipment_without_reference_sends_none(extra):
    assert "reference" not in quote_kwargs(**extra)


def test_easypost_address_renames_zipcode_and_sets_country_and_phone():
    fields = {"name": "Jane Doe", "street1": "1 Main St", "zipcode": "78701"}
    assert postage.easypost_address(fields) == {
        "name": "Jane Doe",
        "street1": "1 Main St",
        "zip": "78701",
        "country": "US",
        "phone": "",
    }
    assert "zip" not in fields  # the caller's dict is left alone


def test_build_address_creates_the_easypost_address():
    client = mock.Mock()
    postage.build_address(client, name="Jane Doe", zipcode="78701")
    client.address.create.assert_called_once_with(
        name="Jane Doe", zip="78701", country="US", phone=""
    )


def test_quote_shipment_declares_the_parcel_in_ounces_and_inches():
    client = mock.Mock()
    postage.quote_shipment(client, {"id": "a"}, {"id": "b"}, 48.0, (20.0, 14.0, 10.0))
    client.parcel.create.assert_called_once_with(
        predefined_package="Parcel", weight=48.0, length=20.0, width=14.0, height=10.0
    )
    assert client.shipment.create.call_args.kwargs["from_address"] == {"id": "a"}


def test_cheapest_rate_is_the_lowest_usps_rate():
    shipment = mock.Mock()
    assert postage.cheapest_rate(shipment) is shipment.lowest_rate.return_value
    shipment.lowest_rate.assert_called_once_with(["USPS"])
