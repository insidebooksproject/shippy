"""Reading the JSONL log files the apps write."""

import json
import pathlib
import typing


def read_jsonl(path: pathlib.Path) -> list[dict[str, typing.Any]]:
    """The records of a JSONL log file (none if it doesn't exist)."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]
