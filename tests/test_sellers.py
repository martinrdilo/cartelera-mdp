"""Ticket host -> seller mapping shared by every collector."""

from lib.sellers import SELLERS, seller_from_url


def test_maps_known_hosts():
    assert seller_from_url("https://articket.com.ar/EVENTO/") == "Articket"
    assert seller_from_url("https://www.plateanet.com/obra/1") == "Plateanet"
    assert seller_from_url("https://wearebombo.com/e/1") == "Bombo"


def test_existing_mappings_still_resolve():
    expected = {
        "venti.live": "Venti",
        "venti.com.ar": "Venti",
        "articket.com.ar": "Articket",
        "cultutickets.com": "CultuTickets",
        "ticketek.com.ar": "Ticketek",
        "plateanet.com": "Plateanet",
        "wearebombo.com": "Bombo",
        "tuentrada.com": "TuEntrada",
        "unica-cartelera.com.ar": "Única Cartelera",
        "passline.com": "Passline",
        "getdogma.app": "Dogma",
        "alpogo.com": "Alpogo",
        "ticketmas.ar": "Ticketmas",
        "chauvin.com.ar": "Chauvin",
        "entradauno.com": "Entrada Uno",
    }
    for domain, seller in expected.items():
        assert seller_from_url(f"https://{domain}/evento/x") == seller


def test_maps_subdomains_to_their_parent():
    assert seller_from_url("https://entradas.ticketek.com.ar/x") == "Ticketek"
    assert seller_from_url("https://www.passline.com/eventos/x") == "Passline"


def test_maps_the_wave4_sellers():
    assert seller_from_url("https://getdogma.app/web/event/QgFh7Ao4G7F5") == "Dogma"
    assert seller_from_url("https://alpogo.com/evento/john-5-en-mar-del-plata-26982") == "Alpogo"


def test_maps_the_venue_owned_stores():
    assert seller_from_url("https://ticketmas.ar/es/ticketmas/evento/x") == "Ticketmas"
    assert seller_from_url("https://entradas.chauvin.com.ar/event/164319-suona") == "Chauvin"


def test_maps_the_missing_ticket_hosts():
    assert seller_from_url("https://feverup.com/m/384932") == "Fever"
    assert seller_from_url("https://www.edenentradas.ar/event/don-osvaldo-mdq-wh") == "Eden Entradas"
    assert seller_from_url("https://centralticket.net/event/11105") == "Central Ticket"
    assert seller_from_url(
        "https://events.flashpass.com.ar/eventos/el-calamar-loco-7-aniversario-9683"
    ) == "Flashpass"
    assert seller_from_url("https://wearebombo.app.link/I87eVR2le7b") == "Bombo"
    assert seller_from_url("https://ccave.fanz.com.ar/event/178241-manu-nena-solda-taxiburon") == "Chauvin"


def test_maps_subdomains_of_the_new_hosts():
    assert seller_from_url("https://www.feverup.com/x") == "Fever"


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


def test_maps_venti_com_ar_and_entrada_uno():
    assert seller_from_url("https://www.venti.com.ar/evento/x") == "Venti"
    assert seller_from_url("https://www.entradauno.com/x") == "Entrada Uno"
