"""Try the Google Maps address parsing from the command line (``addresses``)."""

import json
import os

import googlemaps  # type: ignore

from shippy.core.addresses import AddressParser


def demo():
    """Run a demonstration of address parsing."""
    api_key = os.getenv("Maps_API_KEY")
    if not api_key:
        print("Error: Maps_API_KEY environment variable not set.")
        return

    gmaps = googlemaps.Client(key=api_key)
    parse_address = AddressParser(gmaps)

    chosen_address = "1600 Amphitheatre Parkway, Mountain View, CA 94043"
    address_parts = parse_address(chosen_address)
    if address_parts:
        print("\nParsed Address Components:")
        print(json.dumps(address_parts.model_dump(exclude_none=True), indent=2))
