"""Club TRI agenda: untitled cards never reach the snapshot."""

from collectors.clubtri import normalize


def make_record(**overrides):
    record = {
        "source": "clubtri",
        "title": "Dante Spinetta",
        "date_text": "Sáb 14 de Noviembre",
        "time_text": "20:00",
        "status_text": "Comprar",
        "link": "https://articket.com.ar/DANTE/",
        "image_url": None,
        "image_id": "634",
        "raw_url": "https://clubtri.com.ar/",
    }
    record.update(overrides)
    return record


def test_untitled_card_is_dropped():
    assert normalize([make_record(title=""), make_record(title="   ", image_id="718")]) == []


def test_titled_cards_still_normalize():
    events = normalize([make_record()])
    assert len(events) == 1
    assert events[0].title == "Dante Spinetta"
    assert events[0].source_event_id == "634"
    assert events[0].ticket_url == "https://articket.com.ar/DANTE/"
    assert events[0].seller == "Articket"


def test_free_card_keeps_its_info_link_as_origin():
    link = "https://www.instagram.com/p/Dfmk6R7G5bm/"
    events = normalize(
        [make_record(title="El Fuego Sagrado", status_text="Gratis", link=link)]
    )
    event = events[0]
    assert event.ticket_url is None
    assert event.seller is None
    assert event.is_free is True
    assert event.raw_url == link


def test_every_card_carries_the_club_site_as_the_venue_link():
    # The club publishes its agenda on its own site, so the row can offer it
    # even when the card has no stable event page: a free card links to an
    # Instagram post, and those disappear.
    events = normalize(
        [
            make_record(),
            make_record(
                title="Noche de Salsa",
                status_text="Gratis",
                link="https://www.instagram.com/club.tri/",
                image_id="731",
            ),
        ]
    )
    assert [event.venue_url for event in events] == ["https://clubtri.com/"] * 2


def test_ticket_card_keeps_the_listing_as_origin():
    event = normalize([make_record()])[0]
    assert event.ticket_url == "https://articket.com.ar/DANTE/"
    assert event.raw_url == "https://clubtri.com.ar/"
