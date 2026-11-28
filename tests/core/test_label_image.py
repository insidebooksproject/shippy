"""Unit tests for miscellaneous utility helpers."""

import os
import unittest
from unittest.mock import patch

from PIL import Image

from shippy.core.label_image import LOGO_POSITION, add_logo, build_tempfile, load_logo


class BuildTempfileTests(unittest.TestCase):
    """Tests for the tempfile context manager's acquisition and cleanup."""

    def test_removes_the_file_on_the_success_path(self):
        with build_tempfile(suffix=".png") as tmpfile:
            path = tmpfile.name
            self.assertTrue(os.path.exists(path))

        self.assertFalse(os.path.exists(path))

    def test_removes_the_file_when_the_body_raises(self):
        paths = []
        with self.assertRaises(ValueError):
            with build_tempfile(suffix=".png") as tmpfile:
                paths.append(tmpfile.name)
                raise ValueError("body failed")

        self.assertFalse(os.path.exists(paths[0]))

    def test_creation_failure_surfaces_the_real_error(self):
        """Cleanup must not mask why the tempfile could not be created."""
        with patch(
            "shippy.core.label_image.tempfile.NamedTemporaryFile",
            side_effect=PermissionError("no write access to temp dir"),
        ):
            with self.assertRaises(PermissionError):
                with build_tempfile(suffix=".png"):
                    self.fail("body must not run when creation fails")


class LogoTests(unittest.TestCase):
    """The IBP logo both apps stamp on their labels."""

    def test_the_logo_ships_with_the_package(self):
        with load_logo() as logo:
            logo.load()
            self.assertGreater(logo.width, 0)

    def test_add_logo_pastes_it_at_the_label_position(self):
        label = Image.new("RGB", (800, 1200), "white")
        logo = Image.new("RGB", (10, 10), "black")

        add_logo(label, logo)

        x, y = LOGO_POSITION
        self.assertEqual(label.getpixel((x, y)), (0, 0, 0))
        self.assertEqual(label.getpixel((x - 1, y - 1)), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
