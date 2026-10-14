"""Tests for multi-date occurrence expansion.

Municipal ranges: expand per matching weekday only when the schedule lists
weekdays; never invent dates for ranges without recurrence info.
Articket: the detail page lists every dated session; the JSON-LD block only
exposes start/end.
"""

from datetime import date

from lib.occurrences import (
    expand_segments,
    expand_span,
    extract_articket_detail,
    parse_articket_option,
    parse_weekdays,
)


class TestParseWeekdays:
    def test_single_weekday(self):
        assert parse_weekdays("viernes 18:00") == {4}

    def test_multiple_weekdays(self):
        assert parse_weekdays("viernes  sabado  domingo") == {4, 5, 6}

    def test_accented_weekday(self):
        assert parse_weekdays("miércoles 21:00") == {2}

    def test_no_weekday_returns_empty(self):
        assert parse_weekdays("18:00") == set()

    def test_none_returns_empty(self):
        assert parse_weekdays(None) == set()


class TestExpandSpan:
    def test_weekly_tuesdays(self):
        # Tango y Folclore: 06/10/2026 -> 27/10/2026, "martes 20:30".
        assert expand_span(date(2026, 10, 6), date(2026, 10, 27), {1}) == [
            date(2026, 10, 6),
            date(2026, 10, 13),
            date(2026, 10, 20),
            date(2026, 10, 27),
        ]

    def test_weekend_range(self):
        # Tan Biónica: 21/11/2026 -> 22/11/2026, "sabado domingo".
        assert expand_span(date(2026, 11, 21), date(2026, 11, 22), {5, 6}) == [
            date(2026, 11, 21),
            date(2026, 11, 22),
        ]

    def test_weekdays_outside_range_produce_nothing(self):
        assert expand_span(date(2026, 11, 21), date(2026, 11, 22), {0}) == []


class TestExpandSegments:
    def test_single_day_segment_is_an_exact_date(self):
        segments = [{"start": date(2026, 10, 23), "end": date(2026, 10, 23), "weekdays": set()}]
        assert expand_segments(segments) == (["2026-10-23"], False)

    def test_multi_day_range_without_weekdays_flags_unknown(self):
        segments = [{"start": date(2026, 10, 6), "end": date(2026, 10, 27), "weekdays": set()}]
        assert expand_segments(segments) == ([], True)

    def test_multiple_single_day_segments(self):
        # Luciano Pereyra: 05/12 and 06/12 as separate single-day ranges.
        segments = [
            {"start": date(2026, 12, 5), "end": date(2026, 12, 5), "weekdays": set()},
            {"start": date(2026, 12, 6), "end": date(2026, 12, 6), "weekdays": set()},
        ]
        assert expand_segments(segments) == (["2026-12-05", "2026-12-06"], False)

    def test_weekday_expansion_and_duplicate_collapse(self):
        segments = [
            {"start": date(2026, 12, 5), "end": date(2026, 12, 7), "weekdays": {0, 5, 6}},
            {"start": date(2026, 12, 6), "end": date(2026, 12, 6), "weekdays": set()},
        ]
        assert expand_segments(segments) == (["2026-12-05", "2026-12-06", "2026-12-07"], False)

    def test_unknown_segment_does_not_discard_known_dates(self):
        segments = [
            {"start": date(2026, 12, 5), "end": date(2026, 12, 5), "weekdays": set()},
            {"start": date(2027, 1, 5), "end": date(2027, 1, 30), "weekdays": set()},
        ]
        assert expand_segments(segments) == (["2026-12-05"], True)

    def test_single_day_ignores_mismatched_weekday(self):
        # Live corpus: 11/11/2026 is a Wednesday but the source labels it
        # "domingo"; a single day must always yield its date.
        segments = [{"start": date(2026, 11, 11), "end": date(2026, 11, 11), "weekdays": {6}}]
        assert expand_segments(segments) == (["2026-11-11"], False)

    def test_single_day_mismatched_weekdays_real_dates(self):
        # Same shape in the corpus: 07/12/2026 (Monday, labeled "domingo")
        # and 29/01/2029 (Monday, labeled "miércoles").
        segments = [
            {"start": date(2026, 12, 7), "end": date(2026, 12, 7), "weekdays": {6}},
            {"start": date(2029, 1, 29), "end": date(2029, 1, 29), "weekdays": {2}},
        ]
        assert expand_segments(segments) == (["2026-12-07", "2029-01-29"], False)

    def test_multi_day_weekdays_outside_range_flags_unknown(self):
        # A multi-day range whose listed weekdays never fall inside it: no
        # invented dates, and the empty expansion is flagged, never silent.
        segments = [{"start": date(2026, 11, 21), "end": date(2026, 11, 22), "weekdays": {0}}]
        assert expand_segments(segments) == ([], True)


ARTICKET_SELECT_HTML = """
<html><body>
  <select class="form-control d-none" name="fechas_evento" id="idFechasEventos">
    <option selected disabled>Seleccione una Fecha</option>
    <option value="6051">05 11 2026, 21:00hs</option>
    <option value="6052">03 12 2026, 21:00hs</option>
  </select>
</body></html>
"""

ARTICKET_JSONLD_ONLY_HTML = """
<html><head>
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Event",
    "name": "ZAMBAYONNY - CICLO VERANO MAR DEL PLATA",
    "startDate": "2027-01-09T21:00:00-03:00",
    "endDate": "2027-01-10"
  }
  </script>
</head><body></body></html>
"""


class TestParseArticketOption:
    def test_dd_mm_yyyy_with_time(self):
        assert parse_articket_option("05 11 2026, 21:00hs") == "2026-11-05"

    def test_placeholder_returns_none(self):
        assert parse_articket_option("Seleccione una Fecha") is None

    def test_empty_returns_none(self):
        assert parse_articket_option("") is None


class TestExtractArticketDetail:
    def test_select_lists_all_dates(self):
        assert extract_articket_detail(ARTICKET_SELECT_HTML) == {
            "dates": ["2026-11-05", "2026-12-03"],
            "complete": True,
        }

    def test_jsonld_fallback_keeps_first_date_and_flags_incomplete(self):
        assert extract_articket_detail(ARTICKET_JSONLD_ONLY_HTML) == {
            "dates": ["2027-01-09"],
            "complete": False,
        }

    def test_jsonld_single_day_is_complete(self):
        html = ARTICKET_JSONLD_ONLY_HTML.replace('"endDate": "2027-01-10"', '"endDate": "2027-01-09"')
        assert extract_articket_detail(html) == {"dates": ["2027-01-09"], "complete": True}

    def test_page_without_dates(self):
        assert extract_articket_detail("<html><body>nada</body></html>") == {
            "dates": [],
            "complete": False,
        }
