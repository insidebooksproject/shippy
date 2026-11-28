"""Tests for the typed address in manual mode (Google Maps parsing)."""

from unittest import mock

import pytest

from shippy.cli import console
from shippy.core.addresses import ParsedAddress


@pytest.fixture(name="answers")
def fixture_answers():
    """Answer the name and company prompts, then the address prompt."""
    with (
        mock.patch.object(console.questionary, "text") as text,
        mock.patch.object(console.questionary, "autocomplete") as autocomplete,
        mock.patch.object(console.questionary, "print") as printer,
    ):
        text.return_value.ask.side_effect = ["Jane Doe", "IBP"]
        autocomplete.return_value.ask.return_value = "1 Main St, Austin, TX"
        yield printer


def test_parsed_address_gets_the_name_and_company(answers):
    parsed = ParsedAddress(
        street1="1 Main St", city="Austin", state="TX", zipcode="78701-1234"
    )
    with mock.patch.object(console, "AddressParser") as parser:
        parser.return_value.return_value = parsed
        address = console.query_address(mock.Mock())

    assert address == {
        "street1": "1 Main St",
        "city": "Austin",
        "state": "TX",
        "zipcode": "78701-1234",
        "name": "Jane Doe",
        "company": "IBP",
    }


def printed_lines(printer):
    """Everything questionary.print showed, one string per call."""
    return [call.args[0] for call in printer.call_args_list]


def test_the_parsed_address_is_shown_as_it_goes_on_the_label(answers):
    """Google Maps may put a place name in street2; the volunteer sees it."""
    parsed = ParsedAddress(
        street1="1 Unit Rd",
        street2="Hughes Unit",
        city="Gatesville",
        state="TX",
        zipcode="76597",
    )
    with mock.patch.object(console, "AddressParser") as parser:
        parser.return_value.return_value = parsed
        console.query_address(mock.Mock())

    assert printed_lines(answers) == [
        "  Address for the label:",
        "    Jane Doe",
        "    IBP",
        "    1 Unit Rd",
        "    Hughes Unit",
        "    Gatesville, TX 76597",
    ]


def test_label_lines_skip_blank_fields():
    address = {"name": "Jane Doe", "company": "", "street1": "1 Main St"}
    assert console.label_address_lines({**address, "city": "Austin"}) == [
        "Jane Doe",
        "1 Main St",
        "Austin",
    ]


def test_address_google_cannot_find_asks_again(answers):
    with mock.patch.object(console, "AddressParser") as parser:
        parser.return_value.return_value = None
        assert console.query_address(mock.Mock()) is None

    assert "couldn't find that address" in answers.call_args.args[0]
