"""Buying USPS postage through EasyPost, the same way in both apps."""

from typing import Any, Mapping, Optional, Union

from easypost import EasyPostClient
from easypost.models import Address as EasyPostAddress
from easypost.models import Shipment as EasyPostShipment

from shippy.core.rates import CARRIER

# Volunteers weigh packages in pounds; EasyPost wants ounces.
OUNCES_PER_POUND = 16

# Every package goes as a "Parcel" and asks for Library Mail rates too.
PREDEFINED_PACKAGE = "Parcel"
LIBRARY_MAIL_ELIGIBILITY = "USPS.LIBRARYMAIL"

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


def easypost_address(fields: Mapping[str, Any]) -> dict[str, Any]:
    """EasyPost address fields for an address as the apps hold it.

    The IBP server, Google Maps parsing and shippy-gui's form all say
    ``zipcode``; EasyPost wants ``zip``. Every address is in the US and is
    sent without a phone number.
    """
    data = dict(fields)
    data["zip"] = data.pop("zipcode")
    data["country"] = "US"
    data["phone"] = ""
    return data


def build_address(client: EasyPostClient, **fields) -> EasyPostAddress:
    """Create an EasyPost address from an address as the apps hold it."""
    return client.address.create(**easypost_address(fields))


# An EasyPost address object, or a reference to one by id: {"id": "adr_..."}.
AddressRef = Union[EasyPostAddress, Mapping[str, str]]


def quote_shipment(  # pylint: disable=too-many-arguments
    client: EasyPostClient,
    from_address: AddressRef,
    to_address: AddressRef,
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
        predefined_package=PREDEFINED_PACKAGE,
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
        options={"special_rates_eligibility": LIBRARY_MAIL_ELIGIBILITY},
        **tag,
    )


def cheapest_rate(shipment: EasyPostShipment):
    """The cheapest USPS rate quoted for ``shipment``."""
    return shipment.lowest_rate([CARRIER])


def buy_shipment(
    client: EasyPostClient, shipment: EasyPostShipment, rate
) -> EasyPostShipment:
    """Buy ``rate`` for a quoted shipment."""
    return client.shipment.buy(shipment.id, rate=rate)
