"""The rate comparison the CLI shows before it buys."""

from dataclasses import dataclass
from typing import Optional

from shippy.core.rates import COMPARED_SERVICES, quoted_prices, service_name


@dataclass(frozen=True)
class RateSummary:
    """What to show before buying: the price comparison and any warning."""

    line: str
    warning: Optional[str] = None


def summarize_rates(rates, chosen) -> RateSummary:
    """Compare Library Mail and Ground Advantage and name the rate being bought.

    ``rates`` are the shipment's quoted rates (objects with ``carrier``,
    ``service`` and ``rate``); ``chosen`` is the rate about to be bought.
    """
    quoted = {
        service: price
        for service, price in quoted_prices(rates).items()
        if service in COMPARED_SERVICES
    }

    parts = [
        f"{service_name(service)} ${quoted[service]:.2f}"
        for service in COMPARED_SERVICES
        if service in quoted
    ]
    chosen_name = service_name(chosen.service)
    buying = f"{chosen_name} ${float(chosen.rate):.2f} (cheapest)"
    line = f"{' · '.join(parts)} → buying {buying}" if parts else f"Buying {buying}"

    warning = None
    if "LibraryMail" not in quoted:
        warning = (
            "No Library Mail rate was quoted for this package, so it is not "
            "being sent Library Mail. Check the address and weight if that "
            "is unexpected."
        )
    return RateSummary(line=line, warning=warning)
