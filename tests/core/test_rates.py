"""Tests for the rate names and quoted prices both apps show."""

from types import SimpleNamespace

from shippy.core.rates import quoted_prices, rate_price, service_name


def rate(service, price, carrier="USPS"):
    """A quoted rate like EasyPost's (it sends prices as strings)."""
    return SimpleNamespace(carrier=carrier, service=service, rate=price)


def test_service_names_are_spelled_out_and_unknown_ones_kept():
    assert service_name("LibraryMail") == "Library Mail"
    assert service_name("Express") == "Priority Mail Express"
    assert service_name("NewService") == "NewService"


def test_quoted_prices_keep_the_cheapest_usps_rate_per_service():
    rates = [
        rate("LibraryMail", "9.12"),
        rate("LibraryMail", "8.99"),
        rate("GroundAdvantage", "8.40"),
        rate("Ground", "1.00", carrier="UPS"),
    ]
    assert quoted_prices(rates) == {"LibraryMail": 8.99, "GroundAdvantage": 8.40}


def test_rates_without_a_readable_price_are_skipped():
    rates = [rate("LibraryMail", None), rate("GroundAdvantage", "n/a"), object()]
    assert not quoted_prices(rates)
    assert rate_price(rate("LibraryMail", "5.57")) == 5.57
