"""Tests for the EasyPost shipment reference that tags what a label was for."""

from unittest import mock

import pytest

from shippy import shipping


def test_request_reference_uses_server_code():
    address = {"code": "TEX-00012345-2", "request_id": 98765}
    assert shipping.request_reference(address) == "ibp1:req:TEX-00012345-2"


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
    assert shipping.request_reference(address) == shipping.MANUAL_REFERENCE


@pytest.mark.parametrize(
    "jurisdiction, name",
    [
        ("Texas", "BETO"),
        ("Texas", "Coyote's Bend St. Jail"),
        ("Federal", "Pine Hollow F.C.I."),
    ],
)
def test_unit_reference_passes_name_through(jurisdiction, name):
    reference = shipping.unit_reference(jurisdiction, name)
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
    assert shipping.unit_reference(jurisdiction, name) == shipping.MANUAL_REFERENCE


def test_long_unit_name_is_cut_to_the_limit():
    name = "Long Unit Name " * 10
    reference = shipping.unit_reference("Texas", name)
    assert len(reference) == shipping.MAX_REFERENCE_LENGTH
    assert reference.startswith("ibp1:unit:Texas:Long Unit Name")


def test_realistic_long_unit_name_fits():
    name = "Bridgeport Pre-Parole Transfer Facility St. Annex"
    reference = shipping.unit_reference("Federal", name)
    assert reference == f"ibp1:unit:Federal:{name}"


def quote_kwargs(**kwargs):
    """Call quote_shipment on a mock client; return shipment.create's kwargs."""
    client = mock.Mock()
    shipping.quote_shipment(client, "from", "to", 48.0, (12.0, 12.0, 12.0), **kwargs)
    return client.shipment.create.call_args.kwargs


def test_quote_shipment_sends_reference():
    kwargs = quote_kwargs(reference="ibp1:manual")
    assert kwargs["reference"] == "ibp1:manual"
    assert kwargs["options"] == {"special_rates_eligibility": "USPS.LIBRARYMAIL"}


@pytest.mark.parametrize("extra", [{}, {"reference": None}, {"reference": ""}])
def test_quote_shipment_without_reference_sends_none(extra):
    assert "reference" not in quote_kwargs(**extra)
