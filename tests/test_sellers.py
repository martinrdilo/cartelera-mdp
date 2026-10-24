"""Ticket host -> seller mapping shared by every collector."""

from lib.sellers import SELLERS, seller_from_url


def test_maps_known_hosts():
    assert seller_from_url("https://articket.com.ar/EVENTO/") == "Articket"
    assert seller_from_url("https://www.plateanet.com/obra/1") == "Plateanet"
    assert seller_from_url("https://wearebombo.com/e/1") == "Bombo"


def test_maps_subdomains_to_their_parent():
    assert seller_from_url("https://entradas.ticketek.com.ar/x") == "Ticketek"
    assert seller_from_url("https://www.passline.com/eventos/x") == "Passline"


def test_maps_the_wave4_sellers():
    assert seller_from_url("https://getdogma.app/web/event/QgFh7Ao4G7F5") == "Dogma"
    assert seller_from_url("https://alpogo.com/evento/john-5-en-mar-del-plata-26982") == "Alpogo"


def test_bandsintown_is_an_info_page_not_a_seller():
    # Que Hacemos links Bandsintown event pages, but they sell no tickets.
    assert seller_from_url("https://www.bandsintown.com/e/109045198-joystick") is None


def test_unknown_or_missing_host_returns_none():
    assert seller_from_url("https://example.com/x") is None
    assert seller_from_url("") is None
    assert seller_from_url(None) is None


def test_does_not_match_a_lookalike_suffix():
    assert seller_from_url("https://notarticket.com.ar/x") is None
    assert seller_from_url("https://plateanet.com.evil.test/x") is None


def test_every_entry_has_a_domain_and_seller():
    assert all(domain and seller for domain, seller in SELLERS)
