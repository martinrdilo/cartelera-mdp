/* Cartelera MDP — temas, agenda por día, filtros, búsqueda y detalle.
   Sin dependencias: lee el DOM generado y el payload inline (#events-data). */
(function () {
  "use strict";

  var payloadElement = document.getElementById("events-data");
  var data = payloadElement ? JSON.parse(payloadElement.textContent) : { site: { name: "Cartelera MDP" } };

  /* ---------------------------------------------------------------- theme */

  var root = document.documentElement;
  var THEME_KEY = "cartelera-theme";
  var themeButton = document.getElementById("theme-toggle");
  var systemLight = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

  function storedTheme() {
    try {
      var value = localStorage.getItem(THEME_KEY);
      return value === "light" || value === "dark" ? value : null;
    } catch (error) {
      return null;
    }
  }

  function applyTheme(theme, remember) {
    root.setAttribute("data-theme", theme);
    if (remember) {
      try {
        localStorage.setItem(THEME_KEY, theme);
      } catch (error) {
        /* private mode: the choice lasts for this visit only */
      }
    }
    if (themeButton) {
      themeButton.setAttribute("aria-label", theme === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro");
      themeButton.setAttribute("title", theme === "dark" ? "Modo claro" : "Modo oscuro");
    }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "theme-color");
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", theme === "dark" ? "#080d12" : "#f4f1e9");
  }

  applyTheme(root.getAttribute("data-theme") === "light" ? "light" : "dark", false);

  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next, true);
      track("theme_change", { theme: next });
    });
  }

  if (systemLight && systemLight.addEventListener) {
    systemLight.addEventListener("change", function (event) {
      if (!storedTheme()) applyTheme(event.matches ? "light" : "dark", false);
    });
  }

  /* ---------------------------------------------------------------- state */

  var rows = Array.prototype.slice.call(document.querySelectorAll("[data-row]"));
  var groups = Array.prototype.slice.call(document.querySelectorAll(".daygroup"));
  var dayButtons = Array.prototype.slice.call(document.querySelectorAll(".day"));
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chip"));
  var searchInput = document.getElementById("search");
  var countLabel = document.getElementById("filter-count");
  var emptyState = document.getElementById("empty-state");
  var clearButton = document.getElementById("clear-filters");
  var featured = document.querySelector(".featured");
  var filtersToggle = document.getElementById("filters-toggle");
  var filtersPanel = document.getElementById("filters-panel");
  var filtersOverlay = document.getElementById("filters-overlay");
  var filtersClose = document.getElementById("filters-close");
  var filtersClear = document.getElementById("filters-clear");
  var filtersApply = document.getElementById("filters-apply");
  var activePills = document.getElementById("active-filter-pills");
  var activeDayPill = document.getElementById("active-day-filter");
  var activeDayLabel = document.getElementById("active-day-label");
  var activeVenuePill = document.getElementById("active-venue-filter");
  var activeVenueLabel = document.getElementById("active-venue-label");
  var chipVenueIds = chips
    .filter(function (chip) {
      return chip.dataset.filter === "venue";
    })
    .map(function (chip) {
      return chip.dataset.value;
    });
  var panelViewButtons = Array.prototype.slice.call(document.querySelectorAll("[data-panel-view]"));
  var panelVenueButtons = Array.prototype.slice.call(document.querySelectorAll("[data-panel-venue]"));
  var venueSearch = document.getElementById("venue-search");
  var venueEmpty = document.getElementById("venue-empty");
  var lastFocused = null;

  var defaultView = "all";
  dayButtons.forEach(function (button) {
    if (button.classList.contains("is-on")) defaultView = button.dataset.view;
  });

  var state = { view: defaultView, free: false, venue: null, query: "" };
  var autoSwitched = false;

  function normalize(value) {
    return (value || "")
      .toString()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  function matchesFilters(row, overrides) {
    var free = overrides && "free" in overrides ? overrides.free : state.free;
    var venue = overrides && "venue" in overrides ? overrides.venue : state.venue;
    if (free && row.dataset.free !== "1") return false;
    if (venue && row.dataset.venue !== venue) return false;
    if (state.query && (row.dataset.search || "").indexOf(state.query) === -1) return false;
    return true;
  }

  function matches(row) {
    return matchesFilters(row, null);
  }

  function dateInWindow(iso, window) {
    return Boolean(window) && iso >= window.start && iso <= window.end;
  }

  function inMonth(iso, key) {
    return iso.indexOf(key) === 0;
  }

  function inView(row, view) {
    if (view === "all") return true;
    if (view === "weekend") return row.dataset.inWeekend === "1";
    if (view === "next-weekend") return dateInWindow(row.dataset.date, data.windows && data.windows.next_weekend);
    if (view.indexOf("month:") === 0) return inMonth(row.dataset.date, view.slice(6));
    return row.dataset.date === view;
  }

  function activeFilters() {
    return state.free || Boolean(state.venue) || Boolean(state.query);
  }

  function updateTabCounts() {
    dayButtons.forEach(function (button) {
      var view = button.dataset.view;
      var count = rows.filter(function (row) {
        return matches(row) && inView(row, view);
      }).length;
      var badge = button.querySelector("i");
      if (badge) badge.textContent = count;
      button.classList.toggle("is-empty", count === 0);
      button.classList.toggle("is-on", state.view === view);
      button.setAttribute("aria-pressed", String(state.view === view));
    });
  }

  function syncControls() {
    chips.forEach(function (chip) {
      if (chip.dataset.filter === "free") {
        chip.classList.toggle("is-on", state.free);
        chip.setAttribute("aria-pressed", String(state.free));
        return;
      }
      var on = chip.dataset.value === state.venue;
      chip.classList.toggle("is-on", on);
      chip.setAttribute("aria-pressed", String(on));
    });
    panelViewButtons.forEach(function (button) {
      var on = button.dataset.panelView === state.view;
      button.classList.toggle("is-on", on);
      button.setAttribute("aria-pressed", String(on));
    });
    panelVenueButtons.forEach(function (button) {
      var on = (button.dataset.panelVenue || "") === (state.venue || "");
      button.classList.toggle("is-on", on);
      button.setAttribute("aria-pressed", String(on));
    });
    var dayKey = /^\d{4}-\d{2}-\d{2}$/.test(state.view) ? state.view : "";
    var dayButton = panelViewButtons.filter(function (button) {
      return button.dataset.panelView === dayKey;
    })[0];
    if (activeDayPill) {
      activeDayPill.hidden = !dayButton;
      if (dayButton && activeDayLabel) {
        activeDayLabel.textContent = dayButton.querySelector("span").textContent;
      }
    }
    var venueButton = null;
    if (state.venue && chipVenueIds.indexOf(state.venue) === -1) {
      venueButton = panelVenueButtons.filter(function (button) {
        return button.dataset.panelVenue === state.venue;
      })[0];
    }
    if (activeVenuePill) {
      activeVenuePill.hidden = !venueButton;
      if (venueButton && activeVenueLabel) {
        activeVenueLabel.textContent = venueButton.dataset.label;
      }
    }
    if (activePills) activePills.hidden = !dayButton && !venueButton;
  }

  function updateFilterCounts(visible) {
    chips.forEach(function (chip) {
      var count;
      if (chip.dataset.filter === "free") {
        count = rows.filter(function (row) {
          return (
            row.dataset.free === "1" &&
            matchesFilters(row, { free: false }) &&
            inView(row, state.view)
          );
        }).length;
      } else {
        count = rows.filter(function (row) {
          return (
            row.dataset.venue === chip.dataset.value &&
            matchesFilters(row, { venue: null }) &&
            inView(row, state.view)
          );
        }).length;
      }
      var badge = chip.querySelector("em");
      if (badge) badge.textContent = count;
    });

    panelViewButtons.forEach(function (button) {
      var view = button.dataset.panelView;
      var count = rows.filter(function (row) {
        return matches(row) && inView(row, view);
      }).length;
      var badge = button.querySelector("em");
      if (badge) badge.textContent = count;
      button.classList.toggle("is-empty", count === 0);
    });

    panelVenueButtons.forEach(function (button) {
      var venue = button.dataset.panelVenue;
      var count = rows.filter(function (row) {
        return (
          (!venue || row.dataset.venue === venue) &&
          matchesFilters(row, { venue: null }) &&
          inView(row, state.view)
        );
      }).length;
      var badge = button.querySelector("em");
      if (badge) badge.textContent = count;
      button.classList.toggle("is-empty", count === 0);
    });

    if (filtersApply) {
      filtersApply.textContent = "Ver " + visible + (visible === 1 ? " evento" : " eventos");
    }
  }

  function render(reason) {
    var visible = 0;

    groups.forEach(function (group) {
      var groupRows = Array.prototype.slice.call(group.querySelectorAll("[data-row]"));
      var shown = 0;
      groupRows.forEach(function (row) {
        var show = matches(row);
        row.hidden = !show;
        if (show) shown += 1;
      });
      var groupInView =
        state.view === "all" ||
        (state.view === "weekend" && group.dataset.inWeekend === "1") ||
        (state.view === "next-weekend" &&
          dateInWindow(group.dataset.date, data.windows && data.windows.next_weekend)) ||
        (state.view.indexOf("month:") === 0 && inMonth(group.dataset.date, state.view.slice(6))) ||
        group.dataset.date === state.view;
      group.hidden = !groupInView || shown === 0;
      var label = group.querySelector(".daygroup__head span");
      if (label) label.textContent = shown + (shown === 1 ? " evento" : " eventos");
      if (groupInView) visible += shown;
    });

    updateTabCounts();
    updateFilterCounts(visible);

    if (countLabel) {
      countLabel.textContent = visible + (visible === 1 ? " evento" : " eventos");
    }

    /* Filters can empty the current day while matches exist elsewhere: land on
       "Todo" instead of a dead end. Runs once per user action. */
    if (activeFilters() && visible === 0 && !autoSwitched) {
      var elsewhere = rows.filter(matches).length;
      if (elsewhere > 0) {
        autoSwitched = true;
        state.view = "all";
        render("auto-todo");
        autoSwitched = false;
        return;
      }
    }

    if (emptyState) emptyState.hidden = visible !== 0;
    var keepFeatured =
      state.view === "weekend" || state.view === "next-weekend" || state.view === "all";
    if (featured) featured.hidden = activeFilters() || !keepFeatured;
    syncControls();

    track("filter_change", {
      reason: reason,
      view: state.view,
      free: state.free,
      venue: state.venue,
      query: state.query,
      visible: visible
    });
  }

  function resetFilters() {
    state.free = false;
    state.venue = null;
    state.query = "";
    state.view = "all";
    if (searchInput) searchInput.value = "";
    render("clear");
  }

  function scrollToAgenda() {
    var agenda = document.getElementById("agenda");
    if (agenda) agenda.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function openFilters() {
    if (!filtersPanel || !filtersPanel.hidden) return;
    lastFocused = document.activeElement;
    filtersOverlay.hidden = false;
    filtersPanel.hidden = false;
    if (filtersToggle) filtersToggle.setAttribute("aria-expanded", "true");
    document.body.classList.add("has-dialog");
    if (venueSearch) {
      venueSearch.value = "";
      panelVenueButtons.forEach(function (button) {
        button.hidden = false;
      });
      if (venueEmpty) venueEmpty.hidden = true;
    }
    filtersPanel.focus();
  }

  function closeFilters() {
    if (!filtersPanel || filtersPanel.hidden) return;
    filtersPanel.hidden = true;
    filtersOverlay.hidden = true;
    if (filtersToggle) filtersToggle.setAttribute("aria-expanded", "false");
    document.body.classList.remove("has-dialog");
    if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
    else if (filtersToggle) filtersToggle.focus();
  }

  dayButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      state.view = button.dataset.view;
      render("view");
      scrollToAgenda();
    });
  });

  panelViewButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      state.view = button.dataset.panelView;
      render("panel-view");
    });
  });

  panelVenueButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      state.venue = button.dataset.panelVenue || null;
      render("panel-venue");
    });
  });

  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      if (chip.dataset.filter === "free") {
        state.free = !state.free;
      } else {
        state.venue = state.venue === chip.dataset.value ? null : chip.dataset.value;
      }
      render("chip");
    });
  });

  if (activeDayPill) {
    activeDayPill.addEventListener("click", function () {
      state.view = "all";
      render("clear-day");
    });
  }

  if (activeVenuePill) {
    activeVenuePill.addEventListener("click", function () {
      state.venue = null;
      render("clear-venue");
    });
  }

  if (filtersToggle) {
    filtersToggle.addEventListener("click", function () {
      if (filtersPanel && filtersPanel.hidden) openFilters();
      else closeFilters();
    });
  }
  if (filtersOverlay) filtersOverlay.addEventListener("click", closeFilters);
  if (filtersClose) filtersClose.addEventListener("click", closeFilters);
  if (filtersClear) filtersClear.addEventListener("click", resetFilters);
  if (filtersApply) {
    filtersApply.addEventListener("click", function () {
      closeFilters();
      scrollToAgenda();
    });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && filtersPanel && !filtersPanel.hidden) closeFilters();
  });

  if (filtersPanel) {
    filtersPanel.addEventListener("keydown", function (event) {
      if (event.key !== "Tab") return;
      var focusable = Array.prototype.filter.call(
        filtersPanel.querySelectorAll(
          'button:not([hidden]), input:not([hidden]), [href], [tabindex]:not([tabindex="-1"])'
        ),
        function (element) {
          return !element.disabled;
        }
      );
      if (!focusable.length) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }

  if (venueSearch) {
    venueSearch.addEventListener("input", function () {
      var query = normalize(venueSearch.value);
      var shown = 0;
      panelVenueButtons.forEach(function (button) {
        var match = normalize(button.dataset.search || "").indexOf(query) !== -1;
        button.hidden = !match;
        if (match) shown += 1;
      });
      if (venueEmpty) venueEmpty.hidden = shown !== 0;
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      state.query = normalize(searchInput.value);
      render("search");
    });
    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        searchInput.value = "";
        state.query = "";
        render("search");
      }
    });
  }

  if (clearButton) clearButton.addEventListener("click", resetFilters);

  /* -------------------------------------------------------------- details */

  function setRowOpen(row, open) {
    row.classList.toggle("is-open", open);
    var button = row.querySelector(".js-disclose");
    var details = row.querySelector(".row__details");
    if (button) button.setAttribute("aria-expanded", String(open));
    if (details) details.hidden = !open;
  }

  rows.forEach(function (row) {
    var button = row.querySelector(".js-disclose");
    if (button) {
      button.addEventListener("click", function (event) {
        event.stopPropagation();
        setRowOpen(row, !row.classList.contains("is-open"));
      });
    }
    row.addEventListener("click", function (event) {
      if (event.target.closest("a, button, input, label")) return;
      setRowOpen(row, !row.classList.contains("is-open"));
    });
  });

  /* ---------------------------------------------------------- share + out */

  document.addEventListener("click", function (event) {
    var shareButton = event.target.closest(".js-share");
    if (shareButton) {
      var row = shareButton.closest("[data-row]");
      var card = shareButton.closest("[data-feature]");
      var title = shareButton.dataset.title;
      var venue = shareButton.dataset.venueName;
      var when = shareButton.dataset.when;
      var id = shareButton.dataset.eventId;
      if (row) {
        title = row.dataset.title;
        venue = row.dataset.venueName;
        when = row.dataset.when;
        id = row.dataset.id;
      } else if (card) {
        title = card.dataset.title;
        venue = card.dataset.venueName;
        when = card.dataset.when;
        id = card.dataset.eventId;
      }
      var url = location.href.split("#")[0] + "#" + (id || "");
      var lines = [title, when, venue].filter(Boolean).join(" · ");
      var text = lines + " — Entradas en " + (data.site && data.site.name ? data.site.name : "Cartelera MDP") + ": " + url;
      track("share_whatsapp", { event_id: id });
      window.open("https://wa.me/?text=" + encodeURIComponent(text), "_blank", "noopener");
      return;
    }
    var outbound = event.target.closest('[data-outbound="ticket"]');
    if (outbound) {
      track("outbound_ticket", { event_id: outbound.dataset.eventId, href: outbound.href });
    }
  });

  /* Fallbacks: a poster that fails to load becomes a typographic tile. */
  Array.prototype.forEach.call(document.querySelectorAll("[data-thumb]"), function (image) {
    function fallback() {
      var row = image.closest("[data-row]");
      var holder = image.parentElement;
      if (!holder) return;
      var initials = (row && row.dataset.initials) || "?";
      if (holder.classList.contains("feature__poster")) {
        if (holder.querySelector(".feature__fallback")) return;
        var block = document.createElement("div");
        block.className = "feature__fallback";
        var label = document.createElement("b");
        label.textContent = initials;
        block.appendChild(label);
        holder.insertBefore(block, holder.firstChild);
      } else {
        holder.classList.add("row__thumb--type");
        holder.textContent = initials;
      }
      image.remove();
    }
    /* The error can fire before this script runs: check the already-failed state. */
    if (image.complete && image.naturalWidth === 0) {
      fallback();
    } else {
      image.addEventListener("error", fallback);
    }
  });

  /* Analytics hook. TODO(analytics): forward to GoatCounter (or the provider we
     pick in Fase 3); for now it only names the events worth measuring. */
  function track(name, details) {
    void name;
    void details;
  }

  render("init");
})();
