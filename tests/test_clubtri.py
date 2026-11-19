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
