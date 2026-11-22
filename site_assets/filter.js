/* Cartelera MDP — the predicates behind the filter bar.

   Pure on purpose: each predicate takes a row (anything exposing `dataset`)
   and the filter state, never the DOM, so the page and the Node tests run the
   same code. Loaded before app.js, which only feeds it rows and state. */
(function (global) {
  "use strict";

  /* Whether a filter combination keeps the row. `state` is the filter bar:
     free (gratis), ticket (solo con entrada online), venue (sala) and the
     already-normalized query (búsqueda). */
  function matchesFilters(row, state) {
    if (state.free && row.dataset.free !== "1") return false;
    if (state.ticket && row.dataset.ticket !== "1") return false;
    if (state.venue && row.dataset.venue !== state.venue) return false;
    if (state.query && (row.dataset.search || "").indexOf(state.query) === -1) return false;
    return true;
  }

  function dateInWindow(iso, window) {
    return Boolean(window) && iso >= window.start && iso <= window.end;
  }

  function inMonth(iso, key) {
    return iso.indexOf(key) === 0;
  }

  /* Whether the active day or period tab shows the row. `windows` is the
     payload's `windows` map (weekend, next_weekend, 7days). */
  function inView(row, view, windows) {
    if (view === "all") return true;
    if (view === "weekend") return row.dataset.inWeekend === "1";
    if (view === "next-weekend") return dateInWindow(row.dataset.date, windows && windows.next_weekend);
    if (view.indexOf("month:") === 0) return inMonth(row.dataset.date, view.slice(6));
    return row.dataset.date === view;
  }

  var api = { matchesFilters: matchesFilters, inView: inView };
  if (typeof module === "object" && module.exports) {
    module.exports = api; // Node: require("site_assets/filter.js")
  } else {
    global.CarteleraFilter = api; // Browser: <script src="assets/filter.js">
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
