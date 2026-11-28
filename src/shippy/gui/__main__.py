"""Entry point for shippy-gui application."""

import configparser
import logging
import os
import sys

from PySide6.QtWidgets import QApplication  # type: ignore[import-untyped] # pylint: disable=no-name-in-module
from pydantic import ValidationError

from shippy.core.log import GUI_APP, start_logging
from shippy.core.redact import describe_config_error, describe_validation_error
from shippy.gui.core.config import (
    initialize_config_file,
    load_config,
    resolve_log_path,
)
from shippy.gui.core.logging import configure_logging
from shippy.gui.core.font import apply_font_size
from shippy.gui.main_window import MainWindow
from shippy.gui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)


def main():
    """Launch the shippy-gui application."""
    # The error log, the exception hooks (which also cover Qt slots and
    # worker threads) and the starting line come first, so a broken
    # config.ini is logged too; shippy.log needs the config.
    start_logging(GUI_APP)
    app = QApplication(sys.argv)
    app.setApplicationName("Shippy GUI")
    app.setOrganizationName("Inside Books Project")

    config_path = os.path.join(os.getcwd(), "config.ini")
    config = _load_required_config(config_path)

    _configure_app_logging(config_path, config)

    # Apply configured font size
    apply_font_size(app, config.get_font_size())

    # Note: We pass the intended config_path to MainWindow so that when the user
    # saves settings, they are written to config.ini, not config.example.ini.
    window = MainWindow(config_path=config_path)
    window.show()

    sys.exit(app.exec())


def _load_required_config(config_path: str):
    """Load config.ini or exit if missing/invalid."""
    if not os.path.exists(config_path):
        logger.info("No config.ini; created one from the template")
        initialize_config_file(config_path)
        _show_config_error(
            "A new config.ini was created in this folder.\n\n"
            "Please fill in the IBP server URL and your API keys."
        )
        if not _run_settings_dialog(config_path):
            sys.exit(1)
        return _reload_config_or_exit(config_path)

    try:
        return load_config(config_path)
    except ValidationError as e:
        # The field errors only: the full error repeats what was typed.
        logger.error(
            "config.ini is invalid or incomplete: %s", describe_validation_error(e)
        )
        _show_config_error(
            f"Config file is invalid or incomplete:\n\n{e}\n\n"
            "Please update the settings."
        )
        if not _run_settings_dialog(config_path):
            sys.exit(1)
        return _reload_config_or_exit(config_path)
    except Exception as e:  # pylint: disable=broad-exception-caught
        _log_read_error("Could not read config.ini", e)
        _show_config_error(
            f"Failed to read config file:\n\n{e}\n\nThe application will exit."
        )
        sys.exit(1)


def _log_read_error(message: str, error: Exception) -> None:
    """Log why config.ini could not be read, without the line it choked on.

    A configparser error repeats that line, which can hold an API key.
    """
    if isinstance(error, configparser.Error):
        logger.error("%s: %s", message, describe_config_error(error))
    else:
        logger.error(message, exc_info=error)


def _show_config_error(message: str) -> None:
    """Display a blocking configuration error."""
    from PySide6.QtWidgets import (  # type: ignore[import-untyped] # pylint: disable=no-name-in-module,import-outside-toplevel
        QMessageBox,
    )

    QMessageBox.critical(None, "Configuration Error", message)


def _run_settings_dialog(config_path: str) -> bool:
    """Open settings dialog to let user fix configuration."""
    dialog = SettingsDialog(config_path)
    return bool(dialog.exec())


def _reload_config_or_exit(config_path: str):
    """Reload config after settings; exit if still invalid."""
    try:
        return load_config(config_path)
    except ValidationError as e:
        logger.error(
            "config.ini is still invalid after Settings: %s",
            describe_validation_error(e),
        )
        _show_config_error(
            f"Config file is still invalid or incomplete:\n\n{e}\n\nThe application will exit.",
        )
        sys.exit(1)
    except Exception as e:  # pylint: disable=broad-exception-caught
        _log_read_error("Could not read config.ini after Settings", e)
        _show_config_error(
            f"Failed to read config file:\n\n{e}\n\nThe application will exit.",
        )
        sys.exit(1)


def _configure_app_logging(config_path: str, config) -> None:
    """Configure logging using config settings."""
    printer_log_dir = configure_logging(resolve_log_path(config_path, config))
    logger.info("Shippy GUI started; printer logs in %s", printer_log_dir)


if __name__ == "__main__":
    main()
