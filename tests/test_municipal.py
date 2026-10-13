"""Tests for the municipal collector: schedule segmentation and occurrence expansion."""

from collectors.municipal import normalize, parse_schedule_segments

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
    }
    record.update(overrides)
    return record


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
