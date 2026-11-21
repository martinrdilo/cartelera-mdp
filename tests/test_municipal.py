"""Tests for the municipal collector: schedule segmentation, occurrences and venue sites."""

from collectors.municipal import normalize, parse_page, parse_schedule_segments

# Real schedule text (Coros Mardelcanto 2026, data/raw/municipal.json): four
# ranges, each followed by its weekday list after the "Horarios" heading.
MARDELCANTO_SCHEDULE = (
    "desde:\n11/12/2026\n- hasta:\n13/12/2026\nHorarios\nviernes\n"
    "desde:\n13/11/2026\n- hasta:\n15/11/2026\nHorarios\nviernes  sabado  domingo\n"
    "desde:\n23/10/2026\n- hasta:\n23/10/2026\nHorarios\nviernes 18:00\n"
    "desde:\n27/11/2026\n- hasta:\n29/11/2026\nHorarios\nviernes  sabado  domingo\n"
)


def make_record(**overrides):
    record = {
        "source": "municipal",
        "title": "19º Encuentro Internacional de Coros Mardelcanto 2026",
        "venue_name": "Capilla del Divino Maestro - Pías Discípulas",
        "venue_raw": "Capilla del Divino Maestro - Pías Discípulas, Alberti 2179",
        "ranges": parse_schedule_segments(MARDELCANTO_SCHEDULE),
        "schedule_text": MARDELCANTO_SCHEDULE,
        "description": "",
        "entry_text": "",
        "source_event_id": "1",
        "image_url": None,
        "category": "musica",
        "raw_url": "https://example.test",
        "venue_url": None,
    }
    record.update(overrides)
    return record


# The venue block of a real panel (data/raw/municipal.json, live page 1): a
# mailto: anchor for the venue's email, then its own site. The nbsp separators
# are what _split_venue relies on.
VENUE_BODY_WITH_SITE = (
    "Centro de Arte Radio City - Roxy - Melany&nbsp San Luis&nbsp 1752&nbsp <br />\n"
    "Tel&eacute;fono/fax:&nbsp (0223) 494-2950&nbsp 2235-343523 (WhatsApp)&nbsp <br />\n"
    "Zona: Microcentro&nbsp <br />\n"
    ' <a href="mailto:roxyradiocitymelanycentrodeart@gmail.com">'
    "roxyradiocitymelanycentrodeart@gmail.com&nbsp; </a>"
    ' <a href="http://www.centrodeartemdp.com" target="_blank">www.centrodeartemdp.com&nbsp; </a>\n'
)


def panel_html(venue_body):
    """One results-page panel, mirroring the ASP markup of the live agenda."""
    return f'''
<div class="panel panel-default">
  <div class="panel-heading">
    <div class="panel-title"><strong>Benja Torres</strong></div>
    Lugar del evento:
  </div>
  <div class="panel-body">{venue_body}</div>
  <div class="panel-heading"><div class="panel-title">D&iacute;as y Horarios</div></div>
  <div class="panel-body">
    <strong>desde: </strong>05/12/2026<strong>- hasta: </strong>05/12/2026<br />
    <strong>Horarios</strong><br />sabado 21:30<br />
  </div>
  <div class="panel-heading"><div class="panel-title">Entrada</div></div>
  <div class="panel-body">$35000; en venta en www.plateanet.com.ar</div>
</div>
'''


class TestParseScheduleSegments:
    def test_ranges_pair_with_their_weekdays(self):
        segments = parse_schedule_segments(MARDELCANTO_SCHEDULE)
        assert [(s["desde"], s["hasta"]) for s in segments] == [
            ("11/12/2026", "13/12/2026"),
            ("13/11/2026", "15/11/2026"),
            ("23/10/2026", "23/10/2026"),
            ("27/11/2026", "29/11/2026"),
        ]
        assert segments[0]["weekdays"] == [4]
        assert segments[1]["weekdays"] == [4, 5, 6]
        assert segments[2]["weekdays"] == [4]

    def test_no_dates_returns_empty(self):
        assert parse_schedule_segments("Horarios\na confirmar") == []

    def test_empty_text_returns_empty(self):
        assert parse_schedule_segments("") == []

    def test_segments_are_json_ready_for_raw_evidence(self):
        # data/raw/<source>.json stores the segments verbatim.
        import json

        segments = parse_schedule_segments(MARDELCANTO_SCHEDULE)
        assert json.loads(json.dumps(segments))[1]["weekdays"] == [4, 5, 6]


class TestNormalizeOccurrences:
    def test_mardelcanto_expands_every_weekday(self):
        event = normalize([make_record()])[0]
        assert event.occurrences == [
            "2026-10-23",
            "2026-11-13",
            "2026-11-14",
            "2026-11-15",
            "2026-11-27",
            "2026-11-28",
            "2026-11-29",
            "2026-12-11",
        ]
        assert event.recurrence_unknown is False
        assert event.date_start == "2026-10-23"
        assert event.date_end == "2026-12-13"

    def test_range_without_weekdays_stays_a_range(self):
        schedule = "desde:\n06/10/2026\n- hasta:\n27/10/2026\nHorarios\n"
        record = make_record(ranges=parse_schedule_segments(schedule), schedule_text=schedule)
        event = normalize([record])[0]
        assert event.occurrences == []
        assert event.recurrence_unknown is True
        assert event.date_start == "2026-10-06"
        assert event.date_end == "2026-10-27"

    def test_single_day_range_is_one_occurrence(self):
        schedule = "desde:\n24/10/2026\n- hasta:\n24/10/2026\nHorarios\nsabado 18:00"
        record = make_record(ranges=parse_schedule_segments(schedule), schedule_text=schedule)
        event = normalize([record])[0]
        assert event.occurrences == ["2026-10-24"]
        assert event.recurrence_unknown is False


class TestVenueSite:
    """S6: the venue's own site is the only page a municipal event offers."""

    def test_external_anchor_after_the_mailto_is_the_venue_site(self):
        records = parse_page(panel_html(VENUE_BODY_WITH_SITE), "https://example.test", "musica")
        assert len(records) == 1
        assert records[0]["venue_url"] == "http://www.centrodeartemdp.com"
        # The venue block still parses as before; the site is extra evidence.
        assert records[0]["venue_name"] == "Centro de Arte Radio City - Roxy - Melany"

    def test_panel_without_anchors_has_no_venue_site(self):
        body = "Capilla del Divino Maestro - P&iacute;as Disc&iacute;pulas&nbsp Alberti&nbsp 2179&nbsp <br />\n"
        body += "Tel&eacute;fono/fax:&nbsp (0223) 495-2729&nbsp <br />\n"
        records = parse_page(panel_html(body), "https://example.test", "musica")
        assert records[0]["venue_url"] is None

    def test_mailto_only_is_not_a_venue_site(self):
        body = 'Casino Central&nbsp <a href="mailto:casinocentral2012@outlook.com">casinocentral2012@outlook.com</a>'
        records = parse_page(panel_html(body), "https://example.test", "musica")
        assert records[0]["venue_url"] is None

    def test_municipal_hosts_are_not_the_venue_site(self):
        for href in (
            "http://www.mardelplata.gob.ar/cultura",
            "https://turismomardelplata.gob.ar/ASP/SP/agenda.asp",
        ):
            body = f'Teatro Col&oacute;n&nbsp <a href="mailto:teatrocolon@mardelplata.gov.ar">mail</a> <a href="{href}">{href}</a>'
            records = parse_page(panel_html(body), "https://example.test", "musica")
            assert records[0]["venue_url"] is None, href

    def test_relative_and_non_http_hrefs_are_ignored(self):
        body = (
            'Sala X&nbsp <a href="/Fotos/eventos/48573_foto.jpg">foto</a>'
            ' <a href="tel:+542234940000">tel</a>'
            ' <a href="https://www.salax.com.ar/agenda">sitio</a>'
        )
        records = parse_page(panel_html(body), "https://example.test", "musica")
        assert records[0]["venue_url"] == "https://www.salax.com.ar/agenda"

    def test_normalize_passes_the_venue_site_to_the_event(self):
        record = make_record(venue_url="http://www.centrodeartemdp.com")
        event = normalize([record])[0]
        assert event.venue_url == "http://www.centrodeartemdp.com"

    def test_old_raw_records_without_the_key_still_normalize(self):
        # data/raw/municipal.json predates the field; normalization must not fail.
        record = make_record()
        record.pop("venue_url")
        assert normalize([record])[0].venue_url is None


class TestSellerFromEntryText:
    def test_venti_com_ar_is_venti(self):
        event = normalize([make_record(entry_text="$65000 en venta en www.venti.com.ar")])[0]
        assert event.seller == "Venti"

    def test_chauvin_and_app_bombo(self):
        chauvin = normalize([make_record(entry_text="$45000, en venta en www.chauvin.com.ar")])[0]
        bombo = normalize([make_record(entry_text="en venta desde App. Bombo")])[0]
        assert chauvin.seller == "Chauvin"
        assert bombo.seller == "Bombo"

    def test_septimo_fuego_and_entrada_uno(self):
        septimo = normalize([make_record(entry_text="en venta en septimofuego.com")])[0]
        uno = normalize([make_record(entry_text="en venta en www.entradauno.com/x")])[0]
        assert septimo.seller == "Séptimo Fuego"
        assert uno.seller == "Entrada Uno"
