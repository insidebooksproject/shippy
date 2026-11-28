"""What a failed purchase or print means, and what volunteers are told.

Both apps sort a failed postage purchase into the same three outcomes and
tell the volunteer the same thing for each; only the word for what is retried
differs (the CLI says "package", shippy-gui "shipment"). Unused labels are
refunded automatically by a weekly job on the IBP server, so a buy that may
have gone through is never checked or refunded here, and a second label is
always a safe answer (decided 2026-11-17).
"""

import enum

import easypost  # type: ignore[import-untyped]


def is_refusal(error: Exception) -> bool:
    """Whether EasyPost or the IBP server definitely turned the request down.

    A 4xx answer (other than 408, a timeout) is a refusal, e.g. EasyPost's for
    an empty wallet: trying again won't help, and a refused buy bought
    nothing. No answer, a timeout, a 5xx or any other exception may be
    temporary, and a buy that failed that way may have gone through.
    """
    status = getattr(error, "http_status", None) or getattr(error, "status_code", None)
    return isinstance(status, int) and 400 <= status < 500 and status != 408


def purchase_may_have_completed(error: Exception) -> bool:
    """Whether a buy request that raised ``error`` may still have bought postage."""
    return not is_refusal(error)


def is_payment_error(error: Exception) -> bool:
    """Whether EasyPost refused the buy because the account can't pay (402)."""
    return (
        isinstance(error, easypost.errors.PaymentError)
        or getattr(error, "http_status", None) == 402
    )


class BuyFailure(enum.Enum):
    """What a failed attempt to buy postage left behind."""

    NOT_BOUGHT = "not_bought"
    MAYBE_BOUGHT = "maybe_bought"
    CANT_PAY = "cant_pay"


def classify_buy_failure(error: Exception, *, during_buy: bool) -> BuyFailure:
    """Sort a failure into one of the three outcomes volunteers are told about.

    ``during_buy`` says the buy request itself raised ``error``; anything
    before it (addresses, the quote, no usable rate) bought nothing.
    """
    if is_payment_error(error):
        return BuyFailure.CANT_PAY
    if during_buy and purchase_may_have_completed(error):
        return BuyFailure.MAYBE_BOUGHT
    return BuyFailure.NOT_BOUGHT


def buy_failure_advice(failure: BuyFailure, *, item: str) -> str:
    """What to tell the volunteer about ``failure``; ``item`` is what is retried."""
    if failure is BuyFailure.CANT_PAY:
        return (
            "The EasyPost account can't pay for postage right now. Tell a "
            "coordinator; no postage was bought."
        )
    if failure is BuyFailure.MAYBE_BOUGHT:
        return (
            f"The purchase may not have completed. Try this {item} again; an "
            "unused label is refunded automatically."
        )
    return f"No postage was bought. Try this {item} again."


# What to do when a label may not have printed. Unused labels are refunded
# automatically, so a second label is the cheap, safe answer.
CHECK_PRINTER_ADVICE = (
    "Check the printer. If no label came out, create it again; the unused one "
    "is refunded automatically."
)

# Outcomes whose raw value reads badly in a sentence about the print queue.
OUTCOME_DETAILS = {
    "uncertain": "it could not be confirmed that the job reached the printer",
    "tracking_failed": "following the print job failed",
}


def print_outcome_detail(outcome: str) -> str:
    """Why a spooled label job may not have printed, for a volunteer."""
    return OUTCOME_DETAILS.get(outcome, f"the print queue reported '{outcome}'")
