"""Postage convenience functions."""

from dataclasses import dataclass
from typing import Any, Optional

from easypost import EasyPostClient
from easypost.models import Address as EasyPostAddress
from easypost.models import Shipment as EasyPostShipment

# Each shipment's EasyPost ``reference`` says what the label was bought for, so
# the IBP server can match labels to requests later. Only one of these forms:
#   ibp1:req:<request code>              an individual package
#   ibp1:unit:<jurisdiction>:<unit name> a bulk box to a unit's mailroom
#   ibp1:manual                          anything else (or anything unexpected)
MANUAL_REFERENCE = "ibp1:manual"

# EasyPost documents no limit on ``reference``; keep it well within any
# plausible one. A longer unit tag is cut to this length (its start still
# names the unit); a longer request code is not trusted and tags as manual.
MAX_REFERENCE_LENGTH = 100


def _plain_text(value: Any, *, forbidden: str = "") -> bool:
    """Whether ``value`` is non-blank printable ASCII without ``forbidden``."""
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.isascii()
        and value.isprintable()
        and not any(char in value for char in forbidden)
    )


def request_reference(address: Any) -> str:
    """The shipment reference for a request address from the IBP server.

    Uses the request's canonical ``code`` (e.g. ``TEX-00012345-2``) however
    the volunteer entered the label; an older server sends no code, so the
    label is tagged as manual. Never raises.
    """
    try:
        code = address.get("code")
    except Exception:  # pylint: disable=broad-exception-caught
        return MANUAL_REFERENCE

    if not _plain_text(code, forbidden=" :"):
        return MANUAL_REFERENCE

    reference = f"ibp1:req:{code}"
    return reference if len(reference) <= MAX_REFERENCE_LENGTH else MANUAL_REFERENCE


def unit_reference(jurisdiction: Any, name: Any) -> str:
    """The shipment reference for a bulk box, from the server's unit key.

    The unit name is passed through unchanged (spaces, periods, apostrophes);
    anything unexpected tags the label as manual. Never raises.
    """
    if not _plain_text(jurisdiction, forbidden=":") or not _plain_text(name):
        return MANUAL_REFERENCE

    return f"ibp1:unit:{jurisdiction}:{name}"[:MAX_REFERENCE_LENGTH]


# Services shown side by side before buying (EasyPost service names).
COMPARED_SERVICES = ("LibraryMail", "GroundAdvantage")

SERVICE_NAMES = {
    "LibraryMail": "Library Mail",
    "GroundAdvantage": "Ground Advantage",
    "MediaMail": "Media Mail",
    "Priority": "Priority Mail",
}


def build_address(client: EasyPostClient, **kwargs) -> EasyPostAddress:
    """Build easypost Address."""
    kwargs["zip"] = kwargs.pop("zipcode")
    kwargs["country"] = "US"
    kwargs["phone"] = ""
    return client.address.create(**kwargs)


def quote_shipment(  # pylint: disable=too-many-arguments
    client: EasyPostClient,
    from_address: EasyPostAddress,
    to_address: EasyPostAddress,
    weight: float,
    dimensions: tuple[float, float, float],
    *,
    reference: Optional[str] = None,
) -> EasyPostShipment:
    """Create a shipment (rates quoted, nothing bought); weight in ounces.

    ``reference`` tags the shipment (see ``MANUAL_REFERENCE``); none is sent
    when it is empty.
    """
    length, width, height = dimensions
    parcel = client.parcel.create(
        predefined_package="Parcel",
        weight=weight,
        length=length,
        width=width,
        height=height,
    )
    tag = {"reference": reference} if reference else {}
    return client.shipment.create(
        from_address=from_address,
        to_address=to_address,
        parcel=parcel,
        options={"special_rates_eligibility": "USPS.LIBRARYMAIL"},
        **tag,
    )


def cheapest_rate(shipment: EasyPostShipment):
    """The cheapest USPS rate quoted for ``shipment``."""
    return shipment.lowest_rate(["USPS"])


def buy_shipment(
    client: EasyPostClient, shipment: EasyPostShipment, rate
) -> EasyPostShipment:
    """Buy ``rate`` for a quoted shipment."""
    return client.shipment.buy(shipment.id, rate=rate)


def service_name(service: str) -> str:
    """Volunteer-facing name of an EasyPost service."""
    return SERVICE_NAMES.get(service, service)


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
    quoted: dict[str, float] = {}
    for rate in rates:
        if rate.carrier == "USPS" and rate.service in COMPARED_SERVICES:
            price = float(rate.rate)
            quoted[rate.service] = min(price, quoted.get(rate.service, price))

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
