"""The site's filter predicate, driven as code instead of read as text.

R3-001: the ticket-only toggle used to be verified by asserting on app.js as a
string. The predicate now lives in `site_assets/filter.js` -- the file the page
loads -- and these tests require that same file in a real Node process, so the
browser behaviour is checked by running it.

The fixtures are plain objects with a `dataset` map, the accessor shape a DOM
row exposes (attribute `data-in-weekend` reads as `dataset.inWeekend`).

R4-001: `app.js` used to dereference that module with no fallback, so a deploy
without `filter.js` threw on first paint. These tests also run `app.js` itself
under Node against a bounded DOM stub -- once with the module and once without
-- and assert on the rendered rows, the tab badges and the count label.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FILTER_JS = REPO_ROOT / "site_assets" / "filter.js"
APP_JS = REPO_ROOT / "site_assets" / "app.js"
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


# ---------------------------------------------------------------------------
# app.js itself: the page script, run against a bounded DOM stub
# ---------------------------------------------------------------------------

# Loads `filter.js` the way the browser does (no CommonJS module present, so it
# publishes `globalThis.CarteleraFilter`), wires up the nodes `app.js` reads,
# runs it, then replays the requested clicks and reports what the page shows.
# The stub answers only the selectors registered on each node; anything the page
# asks for beyond that stays empty, which is what the real markup would do for
# the panels this harness does not build.
APP_DRIVER = r"""
const fs = require("fs");
const vm = require("vm");

const filterPath = process.argv[1];
const appPath = process.argv[2];
const mode = process.argv[3];
const clicks = JSON.parse(process.argv[4] || "[]");

function makeClassList() {
  const names = new Set();
  return {
    add: function (name) { names.add(name); },
    remove: function (name) { names.delete(name); },
    contains: function (name) { return names.has(name); },
    toggle: function (name, force) {
      const on = force === undefined ? !names.has(name) : Boolean(force);
      if (on) names.add(name); else names.delete(name);
      return on;
    },
  };
}

function makeElement(tag, dataset, attributes) {
  const element = {
    tagName: tag,
    dataset: dataset || {},
    attributes: Object.assign({}, attributes),
    classList: makeClassList(),
    hidden: false,
    value: "",
    disabled: false,
    parentElement: null,
    children: [],
    queries: {},
    listeners: {},
  };
  element.getAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(element.attributes, name) ? element.attributes[name] : null;
  };
  /* textContent is a string on a real node even when a number is assigned. */
  let text = "";
  Object.defineProperty(element, "textContent", {
    get: function () { return text; },
    set: function (value) { text = String(value); },
  });
  element.setAttribute = function (name, value) { element.attributes[name] = String(value); };
  element.addEventListener = function (type, handler) {
    (element.listeners[type] = element.listeners[type] || []).push(handler);
  };
  element.appendChild = function (child) {
    child.parentElement = element;
    element.children.push(child);
    return child;
  };
  element.insertBefore = function (child, before) {
    const at = element.children.indexOf(before);
    child.parentElement = element;
    if (at === -1) element.children.push(child); else element.children.splice(at, 0, child);
    return child;
  };
  element.remove = function () {
    if (!element.parentElement) return;
    const at = element.parentElement.children.indexOf(element);
    if (at !== -1) element.parentElement.children.splice(at, 1);
    element.parentElement = null;
  };
  element.focus = function () {};
  element.contains = function () { return false; };
  element.closest = function () { return null; };
  element.querySelector = function (selector) {
    const found = element.queries[selector];
    return found && found.length ? found[0] : null;
  };
  element.querySelectorAll = function (selector) { return (element.queries[selector] || []).slice(); };
  return element;
}

/* The inline #events-data payload, cut down to the windows the tabs read. */
const PAYLOAD = {
  site: { name: "Cartelera MDP", url: "https://carteleramdp.com.ar" },
  today: "2026-11-19",
  windows: {
    weekend: { start: "2026-11-19", end: "2026-11-22" },
    next_weekend: { start: "2026-11-26", end: "2026-11-29" },
    "7days": { start: "2026-11-19", end: "2026-11-25" },
  },
  events: [],
};

/* Three rows, one per day group, with the dataset build_site.render_row emits. */
const FIXTURE_ROWS = [
  { key: "ticket", dataset: { row: "", id: "rock-en-el-tri", date: "2026-11-21", inWeekend: "1", free: "0", venue: "club-tri", ticket: "1", search: "rock en el tri club tri" } },
  { key: "free", dataset: { row: "", id: "coro-mardelcanto", date: "2026-11-22", inWeekend: "1", free: "1", venue: "teatro-colon", ticket: "0", search: "coro mardelcanto teatro colon" } },
  { key: "plain", dataset: { row: "", id: "dillom-bendu", date: "2026-11-25", inWeekend: "0", free: "0", venue: "bendu", ticket: "0", search: "dillom bendu" } },
];

const documentStub = makeElement("#document");
documentStub.documentElement = makeElement("html", {}, { "data-theme": "dark", lang: "es" });
documentStub.head = makeElement("head");
documentStub.body = makeElement("body");
const nodes = {};
documentStub.getElementById = function (id) {
  return Object.prototype.hasOwnProperty.call(nodes, id) ? nodes[id] : null;
};
documentStub.createElement = function (tag) { return makeElement(tag); };

const payloadScript = makeElement("script", {}, { id: "events-data", type: "application/json" });
payloadScript.textContent = JSON.stringify(PAYLOAD);
nodes["events-data"] = payloadScript;

const countLabel = makeElement("p", {}, { id: "filter-count" });
nodes["filter-count"] = countLabel;
const emptyState = makeElement("p", {}, { id: "empty-state" });
nodes["empty-state"] = emptyState;
const ticketButton = makeElement("button", {}, { id: "filter-ticket" });
nodes["filter-ticket"] = ticketButton;
const freeButton = makeElement("button", {}, { id: "filter-free" });
nodes["filter-free"] = freeButton;

/* Day nav: the page marks the weekend tab active when the snapshot has a weekend. */
const badges = {};
const dayButtons = ["weekend", "2026-11-21", "2026-11-22", "next-weekend", "all"].map(function (view) {
  const button = makeElement("button", { view: view }, { "data-view": view });
  if (view === "weekend") button.classList.add("is-on");
  const badge = makeElement("i");
  button.appendChild(badge);
  button.queries["i"] = [badge];
  badges[view] = badge;
  return button;
});

const rowByKey = {};
const groupByDate = {};
const labels = {};
const groups = FIXTURE_ROWS.map(function (entry) {
  const row = makeElement("article", entry.dataset);
  rowByKey[entry.key] = row;
  const group = makeElement("section", { date: entry.dataset.date, inWeekend: entry.dataset.inWeekend });
  const label = makeElement("span");
  labels[entry.dataset.date] = label;
  group.appendChild(label);
  group.queries[".daygroup__head span"] = [label];
  group.appendChild(row);
  group.queries["[data-row]"] = [row];
  groupByDate[entry.dataset.date] = group;
  return group;
});

documentStub.queries["[data-row]"] = FIXTURE_ROWS.map(function (entry) { return rowByKey[entry.key]; });
documentStub.queries[".daygroup"] = groups;
documentStub.queries[".day"] = dayButtons;

const store = {};
const localStorageStub = {
  getItem: function (key) { return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null; },
  setItem: function (key, value) { store[key] = String(value); },
};
const windowStub = { open: function () {} };

if (mode === "with-filter") {
  const context = { console: console };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(filterPath, "utf8"), context, { filename: filterPath });
  windowStub.CarteleraFilter = context.CarteleraFilter;
}

const sandbox = {
  console: console,
  document: documentStub,
  window: windowStub,
  localStorage: localStorageStub,
  location: { href: "https://carteleramdp.com.ar/" },
};
vm.createContext(sandbox);

let initError = null;
try {
  vm.runInContext(fs.readFileSync(appPath, "utf8"), sandbox, { filename: appPath });
} catch (error) {
  initError = String(error && error.message ? error.message : error);
}

function clickTarget(name) {
  if (name === "ticket") return ticketButton;
  if (name === "free") return freeButton;
  return dayButtons.filter(function (button) { return button.dataset.view === name; })[0] || null;
}

const clickResults = clicks.map(function (name) {
  const element = clickTarget(name);
  let error = null;
  try {
    (element.listeners.click || []).forEach(function (handler) { handler({ target: element }); });
  } catch (caught) {
    error = String(caught && caught.message ? caught.message : caught);
  }
  return { action: name, error: error };
});

function hiddenMap(source) {
  const out = {};
  Object.keys(source).forEach(function (key) { out[key] = source[key].hidden; });
  return out;
}

function textMap(source) {
  const out = {};
  Object.keys(source).forEach(function (key) { out[key] = source[key].textContent; });
  return out;
}

process.stdout.write(JSON.stringify({
  init_error: initError,
  count: countLabel.textContent,
  badges: textMap(badges),
  labels: textMap(labels),
  rows_hidden: hiddenMap(rowByKey),
  groups_hidden: hiddenMap(groupByDate),
  empty_hidden: emptyState.hidden,
  clicks: clickResults,
}));
"""


def run_app(with_filter, clicks=()):
    """Run `app.js` under Node; return the page state it leaves behind."""
    result = subprocess.run(
        [
            NODE,
            "-e",
            APP_DRIVER,
            str(FILTER_JS),
            str(APP_JS),
            "with-filter" if with_filter else "without-filter",
            json.dumps(list(clicks)),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestPageWithTheFilterModule:
    """The normal deploy: filter.js loads first and the page filters as before."""

    def test_init_renders_the_default_weekend_view(self):
        page = run_app(with_filter=True)
        assert page["init_error"] is None
        assert page["count"] == "2 eventos"
        assert page["badges"]["weekend"] == "2"
        assert page["badges"]["all"] == "3"
        assert page["rows_hidden"] == {"ticket": False, "free": False, "plain": False}
        assert page["groups_hidden"]["2026-11-25"] is True

    def test_the_ticket_toggle_keeps_only_the_ticketed_row(self):
        page = run_app(with_filter=True, clicks=["ticket"])
        assert page["init_error"] is None
        assert [click["error"] for click in page["clicks"]] == [None]
        assert page["rows_hidden"] == {"ticket": False, "free": True, "plain": True}
        assert page["count"] == "1 evento"


class TestPageWithoutTheFilterModule:
    """filter.js missing from a deploy (R4-001): the page degrades to no
    client-side filtering instead of throwing on first paint."""

    def test_init_does_not_throw_and_renders_every_row(self):
        page = run_app(with_filter=False)
        assert page["init_error"] is None
        assert page["rows_hidden"] == {"ticket": False, "free": False, "plain": False}
        assert page["groups_hidden"] == {
            "2026-11-21": False,
            "2026-11-22": False,
            "2026-11-25": False,
        }
        assert page["labels"] == {
            "2026-11-21": "1 evento",
            "2026-11-22": "1 evento",
            "2026-11-25": "1 evento",
        }
        assert page["count"] == "3 eventos"
        assert page["empty_hidden"] is True

    def test_every_tab_badge_counts_the_rows_it_shows(self):
        page = run_app(with_filter=False)
        assert page["badges"] == {
            "weekend": "3",
            "2026-11-21": "3",
            "2026-11-22": "3",
            "next-weekend": "3",
            "all": "3",
        }

    def test_the_ticket_and_gratis_toggles_do_not_break_the_page(self):
        page = run_app(with_filter=False, clicks=["ticket", "free"])
        assert [click["error"] for click in page["clicks"]] == [None, None]
        assert page["rows_hidden"] == {"ticket": False, "free": False, "plain": False}
        assert page["count"] == "3 eventos"
