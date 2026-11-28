"""Tests for keeping keys and config text out of the uploaded logs."""

import configparser

import pytest
from pydantic import BaseModel, ValidationError

from shippy.core.redact import describe_config_error, describe_validation_error


def _parse(text: str) -> configparser.Error:
    parser = configparser.ConfigParser()
    with pytest.raises(configparser.Error) as raised:
        parser.read_string(text)
    return raised.value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[easypost]\napikey EZAKSECRET\n", "ParsingError at line 2"),
        ("apikey = EZAKSECRET\n", "MissingSectionHeaderError at line 1"),
        (
            "[easypost]\napikey = a\napikey = EZAKSECRET\n",
            "DuplicateOptionError at line 3",
        ),
    ],
)
def test_describe_config_error_drops_the_lines(text, expected):
    error = _parse(text)

    assert describe_config_error(error) == expected
    assert "SECRET" not in describe_config_error(error)


def test_a_parsing_error_repeats_the_line():
    """Why the line numbers alone are logged."""
    assert "EZAKSECRET" in str(_parse("[easypost]\napikey EZAKSECRET\n"))


class _Keys(BaseModel):
    apikey: int


def test_describe_config_error_drops_the_values():
    with pytest.raises(ValidationError) as raised:
        _Keys.model_validate({"apikey": "EZAKSECRET"})

    described = describe_config_error(raised.value)
    assert described == f"ValidationError: {describe_validation_error(raised.value)}"
    assert described.startswith("ValidationError: apikey: ")
    assert "SECRET" not in described


def test_describe_config_error_of_other_errors():
    assert describe_config_error(PermissionError(13, "Permission denied", "x")) == (
        "PermissionError: Permission denied"
    )
    assert describe_config_error(RuntimeError("EZAKSECRET")) == "RuntimeError"
