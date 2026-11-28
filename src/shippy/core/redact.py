"""Keeping API keys and what was typed out of the logs the stations upload.

The stations copy ibp-printing's whole log directory (the printer logs and
``errors-<app>.jsonl``) to ``ibp-server``, so nothing written there may carry
an API key, a config.ini line or an address a volunteer typed. Code that logs
an exception whose text can hold one describes it with a helper here instead;
:func:`scrub_secrets` is the backstop that every record written to that
directory goes through.
"""

import configparser
import re

from pydantic import ValidationError

REDACTED = "[redacted]"

# Query parameters that carry a credential, e.g. the ``key=`` of every
# Google Maps request URL (which a requests error repeats).
_SECRET_PARAM = re.compile(
    r"(?i)\b((?:api_?)?key|signature|client_secret|(?:access_)?token)="
    r"[^&\s\"'\\<>]+"
)
# The query string of a Google Maps request also holds what was typed.
_MAPS_QUERY = re.compile(r"(/maps/api/[^\s?\"'\\]*)\?[^\s\"'\\<>]+")
# The shapes of the keys shippy holds, wherever they turn up.
_KNOWN_KEYS = re.compile(r"\b(?:AIza[0-9A-Za-z_-]{30,}|EZ[AT]K[0-9A-Za-z]{16,})")


def scrub_secrets(text: str) -> str:
    """``text`` with API keys and Google Maps request queries redacted."""
    text = _MAPS_QUERY.sub(rf"\1?{REDACTED}", text)
    text = _SECRET_PARAM.sub(rf"\1={REDACTED}", text)
    return _KNOWN_KEYS.sub(REDACTED, text)


def describe_validation_error(error: ValidationError) -> str:
    """The failing settings and why, for the log, without the values.

    ``str(error)`` repeats each bad value, which can be an API key.
    """
    problems = [
        f"{'.'.join(str(part) for part in item['loc']) or 'config'}: {item['msg']}"
        for item in error.errors(include_url=False, include_input=False)
    ]
    return "; ".join(problems) or "invalid"


def describe_config_error(error: BaseException) -> str:
    """Why config.ini could not be read, for the log, without its text.

    A ``configparser`` error repeats the line it could not parse (e.g.
    ``apikey EZAK...`` with no ``=``) and a ``ValidationError`` the values,
    so only the type, the line numbers and the failing settings are kept.
    """
    name = type(error).__name__
    if isinstance(error, ValidationError):
        return f"{name}: {describe_validation_error(error)}"
    if isinstance(error, configparser.Error):
        lines = [lineno for lineno, _line in getattr(error, "errors", None) or []]
        lineno = getattr(error, "lineno", None)
        if isinstance(lineno, int):
            lines.append(lineno)
        if lines:
            return f"{name} at line {', '.join(str(n) for n in sorted(set(lines)))}"
        return name
    if isinstance(error, OSError) and error.strerror:
        return f"{name}: {error.strerror}"
    return name
