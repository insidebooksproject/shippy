"""Tests for keeping keys and config text out of the uploaded logs."""

import configparser

import pytest
from pydantic import BaseModel, ValidationError

from shippy.core.redact import (
    REDACTED,
    describe_config_error,
    describe_validation_error,
    scrub_secrets,
)

from ..maps_errors import MAPS_KEY, leaks, transport_error


def test_scrub_secrets_removes_a_maps_request_query_and_its_key():
    scrubbed = scrub_secrets(str(transport_error()))

    assert not leaks(scrubbed)
    assert f"/maps/api/geocode/json?{REDACTED}" in scrubbed
    assert "maps.googleapis.com" in scrubbed  # What failed is still there.


@pytest.mark.parametrize(
    "text",
    [
        "GET https://example.test/x?a=1&key=hunter2&b=2",
        "apikey=hunter2",
        "api_key=hunter2 then more",
        "?token=hunter2",
        f"a key on its own: {MAPS_KEY}",
        "an EasyPost key: EZAKhunter2hunter2hunter2hunter2",
    ],
)
def test_scrub_secrets_removes_keys(text):
    scrubbed = scrub_secrets(text)

    assert "hunter2" not in scrubbed and MAPS_KEY not in scrubbed
    assert REDACTED in scrubbed


def test_scrub_secrets_keeps_json_valid_and_ordinary_text():
    line = '{"msg": "IBP server request failed", "exc": "url: /api/x?key=s3cret\\n"}'

    assert scrub_secrets(line) == (
        '{"msg": "IBP server request failed", "exc": "url: /api/x?key=[redacted]\\n"}'
    )
    plain = "monkey=1 printer_key=2 http://ibp.test/api/requests/TEX-00012345-0"
    assert scrub_secrets(plain) == plain


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
