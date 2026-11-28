"""Business logic services."""

from typing import Any

import easypost  # type: ignore[import-not-found] # pylint: disable=import-error

from shippy.core.purchase import purchase_may_have_completed
from shippy.core.postage import MANUAL_REFERENCE, cheapest_rate, quote_shipment
from shippy.gui.core.models import AddressBase, ParcelConfig


class PurchaseError(Exception):
    """The buy request failed in a way that may still have bought postage.

    The charge can go through even when the response is lost; the weekly
    refund job refunds any label that was bought but never used.
    """


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
        # shippy-gui only ships to typed addresses, so every label it buys is
        # tagged as manual.
        shipment = quote_shipment(
            self.client,
            {"id": from_addr_id},
            {"id": to_addr_id},
            weight_oz,
            self.parcel_config.dimensions(small_box),
            reference=MANUAL_REFERENCE,
        )

        rate = cheapest_rate(shipment)
        try:
            return self.client.shipment.buy(shipment.id, rate=rate)
        except Exception as error:
            if purchase_may_have_completed(error):
                raise PurchaseError(str(error)) from error
            raise

    def refund_shipment(self, shipment_id: str) -> None:
        """Refund a shipment."""
        self.client.shipment.refund(shipment_id)
