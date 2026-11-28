"""The USPS rates EasyPost quoted, as both apps show them to volunteers.

The CLI shows the comparison before it buys and shippy-gui after; each words
its own line (``shippy.cli.rates``, ``shippy.gui.core.rates``) from these.
"""

from typing import Any, Iterable, Optional

CARRIER = "USPS"

LIBRARY_MAIL = "LibraryMail"
GROUND_ADVANTAGE = "GroundAdvantage"

# Services always shown side by side, in this order, when they were quoted.
COMPARED_SERVICES = (LIBRARY_MAIL, GROUND_ADVANTAGE)

SERVICE_NAMES = {
    LIBRARY_MAIL: "Library Mail",
    GROUND_ADVANTAGE: "Ground Advantage",
    "MediaMail": "Media Mail",
    "Priority": "Priority Mail",
    "Express": "Priority Mail Express",
}


def service_name(service: str) -> str:
    """Volunteer-facing name of an EasyPost USPS service code."""
    return SERVICE_NAMES.get(service, service)


def rate_price(rate: Any) -> Optional[float]:
    """A quoted rate's price in dollars; None if it has none that reads."""
    try:
        return float(rate.rate)
    except (AttributeError, TypeError, ValueError):
        return None


def quoted_prices(rates: Iterable[Any]) -> dict[str, float]:
    """The cheapest quoted USPS price per service.

    ``rates`` are EasyPost rates (objects with ``carrier``, ``service`` and
    ``rate``); other carriers and rates without a readable price are skipped.
    """
    quoted: dict[str, float] = {}
    for rate in rates:
        price = rate_price(rate)
        if getattr(rate, "carrier", None) != CARRIER or price is None:
            continue
        service = str(getattr(rate, "service", ""))
        quoted[service] = min(price, quoted.get(service, price))
    return quoted
