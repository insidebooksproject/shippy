"""Fixtures for the CLI tests."""

import sys
import typing

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.output.plain_text import PlainTextOutput


@pytest.fixture(autouse=True)
def fixture_plain_text_output() -> typing.Iterator[None]:
    """Send questionary's output to stdout as plain text.

    On Windows prompt_toolkit writes through the console API, which fails
    with NoConsoleScreenBufferError when there is no console (CI, or any
    redirected stdout). shippy always runs in a console window there.
    """
    with create_app_session(output=PlainTextOutput(sys.stdout)):
        yield
