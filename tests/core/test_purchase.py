"""Tests for the purchase outcomes and volunteer advice both apps share."""

import unittest

import easypost

from shippy.core.ibp_server import ServerError
from shippy.core.purchase import (
    CHECK_PRINTER_ADVICE,
    BuyFailure,
    buy_failure_advice,
    classify_buy_failure,
    is_payment_error,
    is_refusal,
    print_outcome_detail,
    purchase_may_have_completed,
)

errors = easypost.errors


class PurchaseMayHaveCompletedTests(unittest.TestCase):
    """Only a 4xx other than 408 means EasyPost turned the purchase down."""

    def test_classification(self):
        cases = [
            (errors.HttpError("connection reset"), True),
            (errors.TimeoutError("timed out"), True),
            (errors.TimeoutError("timed out", http_status=408), True),
            (errors.InternalServerError("oops", http_status=500), True),
            (errors.ServiceUnavailableError("down", http_status=503), True),
            (RuntimeError("unexpected"), True),
            (errors.PaymentError("no funds", http_status=402), False),
            (errors.InvalidRequestError("bad rate", http_status=422), False),
            (errors.RateLimitError("slow down", http_status=429), False),
        ]
        for error, expected in cases:
            with self.subTest(
                error=type(error).__name__, status=error.__dict__.get("http_status")
            ):
                self.assertIs(purchase_may_have_completed(error), expected)


class RefusalTests(unittest.TestCase):
    """is_refusal() also reads the IBP server client's status code."""

    def test_server_4xx_is_a_refusal_and_5xx_is_not(self):
        self.assertTrue(is_refusal(ServerError(404, "Not Found")))
        self.assertFalse(is_refusal(ServerError(503, "down")))

    def test_payment_error(self):
        self.assertTrue(is_payment_error(errors.PaymentError("no funds")))
        self.assertTrue(is_payment_error(errors.ApiError("odd", http_status=402)))
        self.assertFalse(is_payment_error(errors.InvalidRequestError("bad")))


class ClassifyBuyFailureTests(unittest.TestCase):
    """The three outcomes volunteers are told about."""

    def test_payment_refused_before_or_during_the_buy(self):
        for during_buy in (False, True):
            with self.subTest(during_buy=during_buy):
                error = errors.PaymentError("no funds", http_status=402)
                self.assertIs(
                    classify_buy_failure(error, during_buy=during_buy),
                    BuyFailure.CANT_PAY,
                )

    def test_lost_answer_during_the_buy_may_have_bought(self):
        error = errors.TimeoutError("timed out")
        self.assertIs(
            classify_buy_failure(error, during_buy=True), BuyFailure.MAYBE_BOUGHT
        )
        self.assertIs(
            classify_buy_failure(error, during_buy=False), BuyFailure.NOT_BOUGHT
        )

    def test_refused_buy_bought_nothing(self):
        error = errors.InvalidRequestError("rate expired", http_status=422)
        self.assertIs(
            classify_buy_failure(error, during_buy=True), BuyFailure.NOT_BOUGHT
        )


class AdviceTests(unittest.TestCase):
    """The volunteer-facing wording (both apps' tests check their own too)."""

    def test_each_outcome_names_the_item_to_retry(self):
        self.assertEqual(
            buy_failure_advice(BuyFailure.NOT_BOUGHT, item="package"),
            "No postage was bought. Try this package again.",
        )
        self.assertEqual(
            buy_failure_advice(BuyFailure.MAYBE_BOUGHT, item="shipment"),
            "The purchase may not have completed. Try this shipment again; an "
            "unused label is refunded automatically.",
        )
        self.assertEqual(
            buy_failure_advice(BuyFailure.CANT_PAY, item="package"),
            "The EasyPost account can't pay for postage right now. Tell a "
            "coordinator; no postage was bought.",
        )

    def test_check_printer_advice(self):
        self.assertEqual(
            CHECK_PRINTER_ADVICE,
            "Check the printer. If no label came out, create it again; the unused "
            "one is refunded automatically.",
        )

    def test_print_outcome_detail(self):
        self.assertEqual(
            print_outcome_detail("uncertain"),
            "it could not be confirmed that the job reached the printer",
        )
        self.assertEqual(
            print_outcome_detail("error"), "the print queue reported 'error'"
        )
