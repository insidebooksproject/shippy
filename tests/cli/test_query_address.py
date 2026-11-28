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
    answers.assert_not_called()


def test_address_google_cannot_find_asks_again(answers):
    with mock.patch.object(console, "AddressParser") as parser:
        parser.return_value.return_value = None
        assert console.query_address(mock.Mock()) is None

    assert "couldn't find that address" in answers.call_args.args[0]
