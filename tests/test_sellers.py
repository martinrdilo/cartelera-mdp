"""Ticket host -> seller mapping shared by every collector."""

from lib.sellers import SELLERS, seller_from_url


def test_maps_known_hosts():
    assert seller_from_url("https://articket.com.ar/EVENTO/") == "Articket"
    assert seller_from_url("https://www.plateanet.com/obra/1") == "Plateanet"
    assert seller_from_url("https://wearebombo.com/e/1") == "Bombo"


def test_maps_subdomains_to_their_parent():
    assert seller_from_url("https://entradas.ticketek.com.ar/x") == "Ticketek"
    assert seller_from_url("https://www.passline.com/eventos/x") == "Passline"


def test_unknown_or_missing_host_returns_none():
    assert seller_from_url("https://example.com/x") is None
    assert seller_from_url("") is None
    assert seller_from_url(None) is None


def test_does_not_match_a_lookalike_suffix():
    assert seller_from_url("https://notarticket.com.ar/x") is None
    assert seller_from_url("https://plateanet.com.evil.test/x") is None


def test_every_entry_has_a_domain_and_seller():
    assert all(domain and seller for domain, seller in SELLERS)
