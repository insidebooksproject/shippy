"""Business logic services."""

from typing import Any

import easypost  # type: ignore[import-not-found] # pylint: disable=import-error

from shippy.gui.core.constants import (
    SHIPMENT_CARRIER,
    SHIPMENT_REFERENCE,
    SHIPMENT_SERVICE,
    PARCEL_PREDEFINED_PACKAGE,
)
from shippy.gui.core.models import AddressBase, ParcelConfig


class PurchaseError(Exception):
    """The buy request failed in a way that may still have bought postage.

    The charge can go through even when the response is lost; the weekly
    refund job refunds any label that was bought but never used.
    """


def purchase_may_have_completed(error: Exception) -> bool:
    """Whether a buy request that raised ``error`` may still have bought postage.

    A 4xx answer (other than 408, a timeout) means EasyPost turned the
    purchase down, e.g. for an empty wallet. No answer, a timeout, a 5xx or
    any other exception may have come after the charge went through.
    """
    status = getattr(error, "http_status", None)
    refused = isinstance(status, int) and 400 <= status < 500 and status != 408
    return not refused


class ShipmentService:
    """Service for handling EasyPost shipment logic."""

    def __init__(self, api_key: str, parcel_config: ParcelConfig):
        self.client = easypost.EasyPostClient(api_key)
        self.parcel_config = parcel_config

    def create_address(self, address: AddressBase) -> Any:
        """Create an address in EasyPost."""
        data = address.to_easypost_dict()
        return self.client.address.create(**data)

    def verify_address(self, address_id: str) -> Any:
        """Verify an existing address ID."""
        return self.client.address.verify(address_id)

    def buy_shipment(
        self,
        from_addr_id: str,
        to_addr_id: str,
        weight_oz: float,
        *,
        small_box: bool = False,
    ) -> Any:
        """Create a shipment, find the lowest rate, and buy postage.

        ``small_box`` declares the configured small box (a 12 in cube: one cubic
        foot), so Ground Advantage is priced on actual weight; otherwise the
        configured, larger dimensions are declared.

        Raises:
            PurchaseError: the buy request failed and may still have bought
                postage (see ``purchase_may_have_completed``). Anything else
                raised, before or by the buy request, means nothing was bought.
        """
        # Any qualifying box is declared as the configured small box, exactly
        # the top USPS cubic tier (1,728 cu in; ParcelConfig checks it). That
        # never understates postage, but a much smaller box could fall in a
        # cheaper cubic tier that this misses. Known and deferred until real
        # dimensions or a box picker.
        length, width, height = self.parcel_config.dimensions(small_box)
        parcel = self.client.parcel.create(
            predefined_package=PARCEL_PREDEFINED_PACKAGE,
            weight=weight_oz,
            length=length,
            width=width,
            height=height,
        )

        shipment = self.client.shipment.create(
            from_address={"id": from_addr_id},
            to_address={"id": to_addr_id},
            parcel=parcel,
            options={"special_rates_eligibility": SHIPMENT_SERVICE},
            reference=SHIPMENT_REFERENCE,
        )

        rate = shipment.lowest_rate([SHIPMENT_CARRIER])
        try:
            return self.client.shipment.buy(shipment.id, rate=rate)
        except Exception as error:
            if purchase_may_have_completed(error):
                raise PurchaseError(str(error)) from error
            raise

    def refund_shipment(self, shipment_id: str) -> None:
        """Refund a shipment."""
        self.client.shipment.refund(shipment_id)
