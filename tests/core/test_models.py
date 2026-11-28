"""Tests for the config models both apps share."""

import unittest

from pydantic import ValidationError

from shippy.core.models import Config, IbpConfig, ParcelConfig

CUBE = (12.0, 12.0, 12.0)


class ParcelDimensionsTests(unittest.TestCase):
    """ParcelConfig box sizes."""

    def test_small_box_is_a_cubic_foot(self):
        self.assertEqual(ParcelConfig().dimensions(True), (12.0, 12.0, 12.0))

    def test_large_box_is_the_default(self):
        self.assertEqual(ParcelConfig().dimensions(False), (20.0, 14.0, 10.0))

    def test_large_box_follows_config(self):
        config = ParcelConfig(length=18, width=12, height=12)
        self.assertEqual(config.dimensions(False), (18.0, 12.0, 12.0))

    def test_small_box_over_a_cubic_foot_is_rejected(self):
        with self.assertRaises(ValidationError):
            ParcelConfig(small_length=13, small_width=12, small_height=12)

    def test_exactly_a_cubic_foot_is_accepted(self):
        config = ParcelConfig(small_length=12, small_width=12, small_height=12)
        self.assertEqual(config.dimensions(True), CUBE)

    def test_other_shapes_of_a_cubic_foot_are_accepted(self):
        config = ParcelConfig(small_length=18, small_width=12, small_height=8)
        self.assertEqual(config.dimensions(True), (18.0, 12.0, 8.0))

    def test_small_box_under_a_cubic_foot_is_rejected(self):
        # 12x12x6 is a lower cubic tier and would understate a 12x12x12 box.
        with self.assertRaises(ValidationError):
            ParcelConfig(small_length=12, small_width=12, small_height=6)

    def test_fractional_sides_are_rejected(self):
        # 15.5 x 11 x 10: USPS would measure 16 x 11 x 10 = 1,760.
        with self.assertRaises(ValidationError):
            ParcelConfig(small_length=15.5, small_width=11, small_height=10)

    def test_fraction_that_rounds_up_to_a_cubic_foot_is_rejected(self):
        # 11.1 rounds up to a 12-inch cube, but cubic pricing would see 11.
        with self.assertRaises(ValidationError):
            ParcelConfig(small_length=11.1, small_width=11.1, small_height=11.1)

    def test_whole_number_floats_are_accepted(self):
        config = ParcelConfig(small_length=12.0, small_width=12.0, small_height=12.0)
        self.assertEqual(config.dimensions(True), CUBE)

    def test_side_over_22_inches_is_rejected(self):
        # 24 x 9 x 8 = 1,728 cubic inches, but one side is over 22 inches.
        with self.assertRaises(ValidationError):
            ParcelConfig(small_length=24, small_width=9, small_height=8)


class IbpConfigTests(unittest.TestCase):
    """The [ibp] section."""

    def test_both_base_url_forms_are_accepted(self):
        for url in ("http://192.168.1.156/api", "http://localhost:8000"):
            with self.subTest(url=url):
                self.assertTrue(str(IbpConfig(url=url).url).startswith(url))

    def test_an_old_apikey_line_is_read_but_optional(self):
        self.assertIsNone(IbpConfig(url="http://host/api").apikey)
        self.assertEqual(IbpConfig(url="http://host/api", apikey="k").apikey, "k")

    def test_url_must_be_http(self):
        with self.assertRaises(ValidationError):
            IbpConfig(url="ftp://host/api")


class ConfigTests(unittest.TestCase):
    """The whole config.ini."""

    def test_parcel_section_is_optional(self):
        config = Config.model_validate(
            {
                "ibp": {"url": "http://host/api"},
                "easypost": {"apikey": "ep"},
                "googlemaps": {"apikey": "gm"},
            }
        )
        self.assertEqual(config.parcel, ParcelConfig())

    def test_unknown_sections_are_ignored(self):
        """shippy reads a config.ini that also has shippy-gui's [ui] section."""
        config = Config.model_validate(
            {
                "ui": {"font_size": "11"},
                "ibp": {"url": "http://host/api"},
                "easypost": {"apikey": "ep"},
                "googlemaps": {"apikey": "gm"},
            }
        )
        self.assertEqual(config.easypost.apikey, "ep")
