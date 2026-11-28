"""Read the return address from the IBP server, as shippy does.

The request itself is the shared client's (``shippy.core.ibp_server``); this
sorts its failures into the two the volunteer is told about.
"""

import requests
from pydantic import ValidationError

from shippy.core.ibp_server import Server, ServerError
from shippy.gui.core.models import ReturnAddressConfig

SHIPPING_SETTINGS_PATH = "shipping-settings"
TIMEOUT_SECONDS = 15.0


class IbpServerError(Exception):
    """The return address could not be read from the IBP server."""


class IbpServerUnreachable(IbpServerError):
    """The IBP server could not be reached or answered with an HTTP error."""


def fetch_return_address(
    base_url: str, timeout: float = TIMEOUT_SECONDS
) -> ReturnAddressConfig:
    """Get the organization's return address from the IBP server.

    Raises:
        IbpServerUnreachable: the server could not be reached or answered
            with an HTTP error.
        IbpServerError: the server sent an address that is incomplete or a
            response that isn't one.
    """
    server = Server(base_url, timeout=timeout)
    url = server.url(SHIPPING_SETTINGS_PATH)
    try:
        return ReturnAddressConfig.model_validate(server.return_address())
    except ServerError as error:
        raise IbpServerUnreachable(
            f"could not reach {url}: HTTP {error.status_code}: {error.detail}"
        ) from error
    except requests.RequestException as error:
        raise IbpServerUnreachable(f"could not reach {url}: {error}") from error
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        # ValidationError is a ValueError; so is a body that isn't JSON.
        detail = (
            "the server's return address is incomplete"
            if isinstance(error, ValidationError)
            else "unexpected response"
        )
        raise IbpServerError(f"{detail} from {url}: {error}") from error
