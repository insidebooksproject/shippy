"""Google Maps errors whose text repeats the request, key included."""

import googlemaps  # type: ignore[import-not-found]
import requests

MAPS_KEY = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKE12345"
TYPED = "123 Main St Huntsville"


def transport_error(
    path: str = "/maps/api/geocode/json", typed: str = TYPED
) -> googlemaps.exceptions.TransportError:
    """A TransportError as googlemaps raises it when the network is down.

    Its text is the requests error, which names the request URL with the
    typed address and ``key=``.
    """
    query = f"address={typed.replace(' ', '+')}&key={MAPS_KEY}"
    return googlemaps.exceptions.TransportError(
        requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='maps.googleapis.com', port=443): "
            f"Max retries exceeded with url: {path}?{query} "
            "(Caused by NewConnectionError('Failed to establish a new connection'))"
        )
    )


def leaks(text: str) -> bool:
    """Whether ``text`` holds the key or any of the typed address."""
    return any(part in text for part in (MAPS_KEY, "Huntsville", "Main St", "Main+St"))
