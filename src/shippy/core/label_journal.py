"""Shared label journal glue: label purchase and status tracking.

The journal lives in ibp-printing and is shared by the shippy CLI, shippy-gui
and the label watcher, so a label bought in either app is seen by all of
them. Each app tags its labels with its own ``app`` name
(``shippy.core.log.CLI_APP`` or ``GUI_APP``). Its functions never raise for
journal problems; the wrappers here also make sure an unexpected error can
never break shipping (it is logged and ignored).
"""

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

import ibp_printing

from shippy.core.log import get_logger

logger = get_logger(__name__)

STATUS_PURCHASED = "purchased"
STATUS_PRINTED = "printed"
STATUS_QUEUED = "queued"
STATUS_CHECK_PRINTER = "check_printer"
STATUS_REFUNDED = "refunded"


@dataclass(frozen=True)
class LabelIdentity:
    """Who a label is for, as the journal knows it."""

    recipient_key: str
    recipient_label: str


def identity_for(address: Mapping[str, Any]) -> LabelIdentity:
    """Build the journal identity of an address dict (name, street1, ...).

    Both apps build it here, from the same fields (street1 and street2 joined
    by a space), so they see each other's labels for the same recipient.
    """
    name = str(address.get("name") or "")
    street1 = str(address.get("street1") or "")
    street = " ".join(
        part for part in (street1, str(address.get("street2") or "")) if part
    )
    city = str(address.get("city") or "")
    state = str(address.get("state") or "")
    zip_code = str(address.get("zipcode") or address.get("zip") or "")
    key = ibp_printing.recipient_key(name, street, city, state, zip_code)
    label = ", ".join(part for part in (name, street1, city, state) if part)
    return LabelIdentity(recipient_key=key, recipient_label=label)


def tracking_ref(shipment: Any) -> str:
    """The journal's key for a shipment, and what a volunteer searches for in
    EasyPost: its tracking code, else its shipment id."""
    return shipment.tracking_code or shipment.id


def pending_labels() -> list[Any]:
    """Labels still waiting to print.

    Raises whatever reading the journal raised; callers decide how to carry
    on (shippy-gui calls this off the UI thread).
    """
    return list(ibp_printing.pending_labels())


def record_purchase(
    identity: Optional[LabelIdentity], shipment: Any, *, app: str
) -> Any:
    """Journal a just-bought label; returns its record (None if not journaled)."""
    if identity is None:
        return None
    try:
        return ibp_printing.record_purchase(
            recipient_key=identity.recipient_key,
            recipient_label=identity.recipient_label,
            tracking_code=tracking_ref(shipment),
            shipment_id=shipment.id,
            app=app,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("could not journal the purchase of %s", shipment.id)
        return None


def update_status(shipment: Any, status: str, *, file: Optional[Path] = None) -> None:
    """Journal a label's print outcome; never raises."""
    try:
        ibp_printing.update_status(
            tracking_ref(shipment), status, file=str(file) if file else None
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("could not journal status %s for %s", status, shipment.id)


def retry_meta(
    identity: Optional[LabelIdentity],
    shipment: Any,
    record: Any = None,
    *,
    app: str,
) -> dict[str, Any]:
    """Metadata saved next to a queued label for the label watcher."""
    created = getattr(record, "created", None)
    meta: dict[str, Any] = {
        "tracking_code": tracking_ref(shipment),
        "shipment_id": shipment.id,
        "app": app,
        # When postage was bought (epoch seconds, like the journal).
        "created": created if isinstance(created, (int, float)) else time.time(),
    }
    if identity is not None:
        meta["recipient_label"] = identity.recipient_label
        meta["recipient_key"] = identity.recipient_key
    return meta


def as_datetime(value: Any) -> Optional[datetime]:
    """Read a journal timestamp (epoch seconds) as local time."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).astimezone()
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return moment.astimezone() if moment.tzinfo else moment


def format_time(value: Any) -> str:
    """HH:MM of a journal timestamp (today), else a short date and time."""
    moment = as_datetime(value)
    if moment is None:
        return str(value or "?")
    if moment.date() == datetime.now(moment.tzinfo).date():
        return moment.strftime("%H:%M")
    return moment.strftime("%b %d %H:%M")
