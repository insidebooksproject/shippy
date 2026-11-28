"""Describe the USPS rates EasyPost quoted for a bought shipment."""

from dataclasses import dataclass
from typing import Any, Optional

from shippy.core.rates import (
    COMPARED_SERVICES,
    LIBRARY_MAIL,
    quoted_prices,
    rate_price,
    service_name,
)


@dataclass(frozen=True)
class RateSummary:
    """One-line comparison of the quoted rates and the one that was bought."""

    text: str
    library_mail_missing: bool


def summarize_rates(shipment: Any) -> Optional[RateSummary]:
    """Compare the quoted USPS rates with the one bought.

    Returns None when the shipment carries no usable rate list (nothing to
    show). Example text: "Library Mail $9.12 · Ground Advantage $8.40 →
    bought Ground Advantage (cheapest)".
    """
    rates = getattr(shipment, "rates", None)
    if not isinstance(rates, (list, tuple)):
        return None
    quoted = quoted_prices(rates)

    selected = getattr(shipment, "selected_rate", None)
    bought_service = str(getattr(selected, "service", "") or "")
    bought_price = rate_price(selected) if selected is not None else None
    if not quoted and bought_price is None:
        return None

    shown = [service for service in COMPARED_SERVICES if service in quoted]
    if bought_service and bought_service not in shown and bought_service in quoted:
        shown.append(bought_service)
    parts = [f"{service_name(s)} ${quoted[s]:.2f}" for s in shown]

    text = " · ".join(parts)
    if bought_service:
        cheapest = bought_price is not None and all(
            bought_price <= price for price in quoted.values()
        )
        bought = f"bought {service_name(bought_service)}"
        if cheapest:
            bought += " (cheapest)"
        text = f"{text} → {bought}" if text else bought

    missing = LIBRARY_MAIL not in quoted
    if missing:
        text = f"WARNING: no Library Mail rate was quoted. {text}"
    return RateSummary(text=text, library_mail_missing=missing)
