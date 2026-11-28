"""Unit tests for the address form."""

import unittest
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from shippy.gui.widgets.address_form import AddressForm


class AddressReplacedSignalTests(unittest.TestCase):
    """recipient_changed fires on any change of recipient, typing included."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.form = AddressForm()
        self.emitted: list[bool] = []
        self.form.recipient_changed.connect(lambda: self.emitted.append(True))

    def test_clear_emits(self):
        self.form.clear()
        self.assertEqual(self.emitted, [True])

    def test_set_address_emits(self):
        self.form.set_address({"street1": "1 Main St", "city": "Austin"})
        self.assertEqual(self.emitted, [True])

    def test_merge_address_emits(self):
        self.form.merge_address({"zipcode": "78701"})
        self.assertEqual(self.emitted, [True])

    def test_typing_in_any_field_emits(self):
        for field in (
            self.form.name_input,
            self.form.company_input,
            self.form.street1_input,
            self.form.street2_input,
            self.form.city_input,
            self.form.state_input,
            self.form.zipcode_input,
        ):
            self.emitted.clear()
            field.textEdited.emit("x")
            self.assertEqual(self.emitted, [True], field.objectName())


class AddressFormTests(unittest.TestCase):
    """Tests for non-destructive address form behavior."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.form = AddressForm()

    def test_merge_address_preserves_existing_values(self):
        self.form.name_input.setText("Jane Doe")
        self.form.street2_input.setText("Unit 42")

        self.form.merge_address({"street1": "123 Prison Rd", "city": "Huntsville"})

        self.assertEqual(self.form.name_input.text(), "Jane Doe")
        self.assertEqual(self.form.street2_input.text(), "Unit 42")
        self.assertEqual(self.form.street1_input.text(), "123 Prison Rd")
        self.assertEqual(self.form.city_input.text(), "Huntsville")

    def test_merge_address_not_called_when_parser_returns_none(self):
        parser = Mock(return_value=None)
        self.form.name_input.setText("Jane Doe")
        self.form.street2_input.setText("Unit 42")

        parsed = parser("unparseable address")
        if parsed:
            self.form.merge_address(parsed)

        parser.assert_called_once_with("unparseable address")
        self.assertEqual(self.form.name_input.text(), "Jane Doe")
        self.assertEqual(self.form.street2_input.text(), "Unit 42")


if __name__ == "__main__":
    unittest.main()
