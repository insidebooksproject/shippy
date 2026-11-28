"""Keeping API keys and what was typed out of the logs the stations upload.

The stations copy ibp-printing's whole log directory (the printer logs and
``errors-<app>.jsonl``) to ``ibp-server``, so nothing written there may carry
an API key, a config.ini line or an address a volunteer typed. Code that logs
an exception whose text can hold one describes it with a helper here instead.
"""

import configparser

from pydantic import ValidationError


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
