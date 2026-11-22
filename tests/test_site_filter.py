"""The site's filter predicate, driven as code instead of read as text.

R3-001: the ticket-only toggle used to be verified by asserting on app.js as a
string. The predicate now lives in `site_assets/filter.js` -- the file the page
loads -- and these tests require that same file in a real Node process, so the
browser behaviour is checked by running it.

The fixtures are plain objects with a `dataset` map, the accessor shape a DOM
row exposes (attribute `data-in-weekend` reads as `dataset.inWeekend`).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FILTER_JS = REPO_ROOT / "site_assets" / "filter.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

# Requires the module under test and answers one verdict per case, in order.
DRIVER = """
const Filter = require(process.argv[1]);
let raw = "";
process.stdin.on("data", (chunk) => (raw += chunk));
process.stdin.on("end", () => {
  const answers = JSON.parse(raw).map((item) =>
    item.kind === "view"
      ? Filter.inView({ dataset: item.row }, item.view, item.windows)
      : Filter.matchesFilters({ dataset: item.row }, item.state)
  );
  process.stdout.write(JSON.stringify(answers));
});
"""

BASE_STATE = {"view": "all", "free": False, "ticket": False, "venue": None, "query": ""}
WINDOWS = {
    "next_weekend": {"start": "2026-11-26", "end": "2026-11-29"},
    "weekend": {"start": "2026-11-19", "end": "2026-11-22"},
}

TICKET = {
    "ticket": "1",
    "free": "0",
    "venue": "club-tri",
    "search": "rock en el tri club tri",
    "date": "2026-11-21",
    "inWeekend": "1",
}
FREE = {
    "ticket": "0",
    "free": "1",
    "venue": "teatro-colon",
    "search": "coro mardelcanto teatro colon",
    "date": "2026-11-22",
    "inWeekend": "1",
}
PLAIN = {
    "ticket": "0",
    "free": "0",
    "venue": "bendu",
    "search": "dillom bendu",
    "date": "2026-11-25",
    "inWeekend": "0",
}
ROWS = [TICKET, FREE, PLAIN]


def ask(cases):
    """Run the real predicate under Node; one answer per case, in order."""
    result = subprocess.run(
        [NODE, "-e", DRIVER, str(FILTER_JS)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def filtered(rows, **state):
    """`matchesFilters` verdict for every row under one filter state."""
    items = [
        {"kind": "filter", "row": row, "state": {**BASE_STATE, **state}} for row in rows
    ]
    return ask(items)


def view(rows, name):
    """`inView` verdict for every row under one day/period tab."""
    items = [{"kind": "view", "row": row, "view": name, "windows": WINDOWS} for row in rows]
    return ask(items)


class TestTicketOnly:
    def test_toggle_off_keeps_every_row(self):
        assert filtered(ROWS) == [True, True, True]

    def test_toggle_on_keeps_only_rows_with_a_purchase_link(self):
        assert filtered(ROWS, ticket=True) == [True, False, False]


class TestExistingFilters:
    def test_gratis_keeps_only_free_rows(self):
        assert filtered(ROWS, free=True) == [False, True, False]

    def test_venue_chip_keeps_only_the_chosen_venue(self):
        assert filtered(ROWS, venue="bendu") == [False, False, True]

    def test_search_text_matches_the_row_search_blob(self):
        assert filtered(ROWS, query="coro") == [False, True, False]
        assert filtered(ROWS, query="zzz") == [False, False, False]


class TestDayTabs:
    def test_a_day_tab_shows_only_that_day(self):
        assert view(ROWS, "2026-11-21") == [True, False, False]

    def test_the_weekend_tab_reads_the_row_marker(self):
        assert view(ROWS, "weekend") == [True, True, False]

    def test_the_todo_tab_shows_every_row(self):
        assert view(ROWS, "all") == [True, True, True]

    def test_a_month_tab_matches_the_date_prefix(self):
        assert view(ROWS, "month:2026-11") == [True, True, True]


class TestCombinedFilters:
    def test_ticket_only_with_gratis_leaves_nothing(self):
        # The two chips cannot both hold: a ticketed row is not a free row.
        assert filtered(ROWS, ticket=True, free=True) == [False, False, False]

    def test_ticket_only_with_a_venue_keeps_the_ticketed_row_of_that_venue(self):
        assert filtered(ROWS, ticket=True, venue="club-tri") == [True, False, False]
        assert filtered(ROWS, ticket=True, venue="teatro-colon") == [False, False, False]

    def test_ticket_only_with_search_text(self):
        assert filtered(ROWS, ticket=True, query="rock") == [True, False, False]
        assert filtered(ROWS, ticket=True, query="coro") == [False, False, False]
