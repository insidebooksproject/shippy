"""A plain ``shippy`` install has no PySide6: the CLI and core never load Qt."""

import pkgutil
import subprocess
import sys

import shippy.core

CORE_MODULES = sorted(
    f"shippy.core.{module.name}"
    for module in pkgutil.iter_modules(shippy.core.__path__)
)

CHECK = """
import importlib, sys
for name in sys.argv[1:]:
    importlib.import_module(name)
loaded = sorted({{m.split(".")[0] for m in sys.modules}} & {forbidden!r})
print(",".join(loaded))
"""


def loaded_after_import(modules, forbidden):
    """Which of ``forbidden`` a fresh interpreter has loaded after ``modules``."""
    result = subprocess.run(
        [sys.executable, "-c", CHECK.format(forbidden=set(forbidden)), *modules],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_core_loads_neither_qt_nor_prompt_toolkit():
    assert CORE_MODULES
    forbidden = {"PySide6", "shiboken6", "prompt_toolkit", "questionary"}
    assert loaded_after_import(CORE_MODULES, forbidden) == ""


def test_cli_does_not_load_qt():
    modules = ["shippy.cli", "shippy.cli.app", "shippy.__main__"]
    assert loaded_after_import(modules, {"PySide6", "shiboken6"}) == ""
