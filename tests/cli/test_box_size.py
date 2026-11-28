"""Tests for the box-size question, rate comparison and postage purchase."""

import unittest
from types import SimpleNamespace
from unittest import mock

from shippy.cli import app as cli, console
from shippy.cli.rates import summarize_rates
from shippy.core.models import SMALL_BOX_MIN_WEIGHT_LB


def rate(service, price, carrier="USPS"):
    """A quoted rate like EasyPost's."""
    return SimpleNamespace(carrier=carrier, service=service, rate=f"{price:.2f}")


class QuerySmallBoxTests(unittest.TestCase):
    """console.query_small_box()."""

    def test_light_package_is_not_asked(self):
        with mock.patch.object(console.questionary, "confirm") as confirm:
            answer = console.query_small_box(3, SMALL_BOX_MIN_WEIGHT_LB)
        self.assertIs(answer, False)
        confirm.assert_not_called()

    def test_heavy_package_is_asked_with_default_no(self):
        with mock.patch.object(console.questionary, "confirm") as confirm:
            confirm.return_value.ask.return_value = True
            answer = console.query_small_box(4, SMALL_BOX_MIN_WEIGHT_LB)
        self.assertIs(answer, True)
        self.assertIs(confirm.call_args.kwargs["default"], False)

    def test_question_is_about_rounded_volume_and_longest_side(self):
        with mock.patch.object(console.questionary, "confirm") as confirm:
            console.query_small_box(5, SMALL_BOX_MIN_WEIGHT_LB)
        self.assertEqual(
            confirm.call_args.args[0],
            "Is the box 1,728 cubic inches or less (length x width x height, "
            "each side rounded up) with no side over 22 inches?",
        )

    def test_examples_are_shown_before_the_question(self):
        order = mock.Mock()
        with (
            mock.patch.object(console.questionary, "confirm") as confirm,
            mock.patch.object(console.questionary, "print") as say,
        ):
            order.attach_mock(say, "print")
            order.attach_mock(confirm, "confirm")
            console.query_small_box(5, SMALL_BOX_MIN_WEIGHT_LB)
        shown = "\n".join(call.args[0] for call in say.call_args_list)
        for example in ("12x12x12", "18x12x8", "16x12x9", "20x10x8"):
            self.assertIn(example, shown)
        self.assertIn("14x12x11 (1,848", shown)
        self.assertIn("24x10x7 (side over 22", shown)
        self.assertIn("not sure, answer No", shown)
        names = [call[0] for call in order.mock_calls]
        self.assertLess(names.index("print"), names.index("confirm"))

    def test_light_package_shows_no_examples(self):
        with mock.patch.object(console.questionary, "print") as say:
            console.query_small_box(3, SMALL_BOX_MIN_WEIGHT_LB)
        say.assert_not_called()

    def test_cancel_returns_none(self):
        with mock.patch.object(console.questionary, "confirm") as confirm:
            confirm.return_value.ask.return_value = None
            answer = console.query_small_box(10, SMALL_BOX_MIN_WEIGHT_LB)
        self.assertIsNone(answer)


class SummarizeRatesTests(unittest.TestCase):
    """rates.summarize_rates()."""

    def test_both_services_shown_and_cheapest_named(self):
        rates = [rate("LibraryMail", 9.12), rate("GroundAdvantage", 8.4)]
        summary = summarize_rates(rates, rates[1])
        self.assertEqual(
            summary.line,
            "Library Mail $9.12 · Ground Advantage $8.40 "
            "→ buying Ground Advantage $8.40 (cheapest)",
        )
        self.assertIsNone(summary.warning)

    def test_other_services_and_carriers_are_left_out(self):
        rates = [
            rate("LibraryMail", 5.57),
            rate("Priority", 11.0),
            rate("GroundAdvantage", 3.0, carrier="UPS"),
        ]
        summary = summarize_rates(rates, rates[0])
        self.assertEqual(
            summary.line, "Library Mail $5.57 → buying Library Mail $5.57 (cheapest)"
        )

    def test_missing_library_mail_warns(self):
        rates = [rate("GroundAdvantage", 8.4), rate("Priority", 11.0)]
        summary = summarize_rates(rates, rates[0])
        self.assertIn("Ground Advantage $8.40", summary.line)
        self.assertIsNotNone(summary.warning)
        self.assertIn("Library Mail", summary.warning)

    def test_nothing_compared_still_names_purchase(self):
        rates = [rate("Priority", 11.0)]
        summary = summarize_rates(rates, rates[0])
        self.assertEqual(summary.line, "Buying Priority Mail $11.00 (cheapest)")
        self.assertIsNotNone(summary.warning)


class PurchasePostageTests(unittest.TestCase):
    """cli.purchase_postage(): quote with the chosen box, buy the cheapest."""

    def setUp(self):
        self.client = mock.Mock()
        self.rates = [rate("LibraryMail", 9.12), rate("GroundAdvantage", 8.4)]
        quote = mock.Mock(id="shp_1", rates=self.rates)
        quote.lowest_rate.return_value = self.rates[1]
        self.client.shipment.create.return_value = quote
        self.quote = quote
        printed = mock.patch.object(cli.questionary, "print")
        self.printed = printed.start()
        self.addCleanup(printed.stop)

    def purchase(self, dimensions):
        return cli.purchase_postage(
            self.client, "from", "to", weight=160.0, dimensions=dimensions
        )

    def test_buys_the_cheapest_usps_rate(self):
        bought = self.purchase((12.0, 12.0, 12.0))
        self.quote.lowest_rate.assert_called_once_with(["USPS"])
        self.client.shipment.buy.assert_called_once_with("shp_1", rate=self.rates[1])
        self.assertIs(bought, self.client.shipment.buy.return_value)

    def test_declares_the_chosen_box(self):
        self.purchase((12.0, 12.0, 12.0))
        parcel = self.client.parcel.create.call_args.kwargs
        self.assertEqual(
            (parcel["length"], parcel["width"], parcel["height"]), (12.0, 12.0, 12.0)
        )
        self.assertEqual(parcel["weight"], 160.0)
        options = self.client.shipment.create.call_args.kwargs["options"]
        self.assertEqual(options["special_rates_eligibility"], "USPS.LIBRARYMAIL")

    def test_shows_the_comparison_before_buying(self):
        order = mock.Mock()
        order.attach_mock(self.printed, "print")
        order.attach_mock(self.client.shipment.buy, "buy")
        self.purchase((20.0, 14.0, 10.0))
        names = [call[0] for call in order.mock_calls]
        printed_lines = [
            call.args[0] for call in self.printed.call_args_list if call.args
        ]
        self.assertTrue(any("Ground Advantage $8.40" in x for x in printed_lines))
        first_print = names.index("print")
        self.assertLess(first_print, names.index("buy"))


if __name__ == "__main__":
    unittest.main()
