"""Which label printers postage may go to, in both apps.

Postage labels are 4x6. ibp-printing's printer registry knows which printer
models are for package labels instead (an SP310, a DYMO LabelWriter 450), and
those are never offered for postage; a printer it doesn't know may print
anything, so it still counts. This is the rule ibp-printing applies itself
when printing with ``label="shipping"``.
"""

from typing import Iterable

from ibp_printing import PrinterCandidate
from ibp_printing.printers import LabelRole

# What the apps print: passed as ``label=`` to ibp-printing's print calls.
SHIPPING_LABEL = LabelRole.SHIPPING.value


def shipping_printers(
    candidates: Iterable[PrinterCandidate],
) -> list[PrinterCandidate]:
    """``candidates`` (in order) without the known package-label printers."""
    return [
        candidate for candidate in candidates if candidate.prints(LabelRole.SHIPPING)
    ]
