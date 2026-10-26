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

  function slice(list) {
    return Array.prototype.slice.call(list);
  }

  var rows = slice(document.querySelectorAll("[data-row]"));
  var groups = slice(document.querySelectorAll(".daygroup"));
  var dayButtons = slice(document.querySelectorAll(".day"));
  var searchInput = document.getElementById("search");
  var countLabel = document.getElementById("filter-count");
  var emptyState = document.getElementById("empty-state");
  var clearButton = document.getElementById("clear-filters");
  var freeButton = document.getElementById("filter-free");
  var venueChips = slice(document.querySelectorAll(".fchip[data-venue]"));
  var salaToggle = document.getElementById("sala-toggle");
  var salaDrawer = document.getElementById("sala-drawer");
  var salaClose = document.getElementById("sala-close");
  var salaOptions = slice(document.querySelectorAll(".sala-option"));
  var salaShowAll = document.getElementById("sala-show-all");
  var salaClear = document.getElementById("sala-clear");
  var venueSearch = document.getElementById("venue-search");
  var venueEmpty = document.getElementById("venue-empty");
  var activePills = document.getElementById("active-filters");
  var activeVenuePill = document.getElementById("active-venue-filter");
  var activeVenueLabel = document.getElementById("active-venue-label");
  var filterbar = document.querySelector(".filterbar");
  var previewLimit = salaDrawer ? parseInt(salaDrawer.dataset.preview, 10) || 12 : 12;

  var defaultView = "all";
  dayButtons.forEach(function (button) {
    if (button.classList.contains("is-on")) defaultView = button.dataset.view;
  });

  var state = { view: defaultView, free: false, venue: null, query: "" };
  var autoSwitched = false;
  var showAllVenues = false;

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
    if (freeButton) {
      freeButton.classList.toggle("is-on", state.free);
      freeButton.setAttribute("aria-pressed", String(state.free));
    }
    var chipHasVenue = false;
    venueChips.forEach(function (chip) {
      var on = chip.dataset.venue === state.venue;
      chip.classList.toggle("is-on", on);
      chip.setAttribute("aria-pressed", String(on));
      if (on) chipHasVenue = true;
    });
    salaOptions.forEach(function (option) {
      var on = option.dataset.venue === state.venue;
      option.classList.toggle("is-on", on);
      option.setAttribute("aria-pressed", String(on));
    });

    var selected = null;
    if (state.venue) {
      selected = salaOptions.filter(function (option) {
        return option.dataset.venue === state.venue;
      })[0] || null;
    }
    var showPill = Boolean(selected) && !chipHasVenue;
    if (activeVenuePill) {
      activeVenuePill.hidden = !showPill;
      if (showPill && activeVenueLabel) {
        activeVenueLabel.textContent =
          selected.dataset.label || selected.querySelector(".sala-option__name").textContent;
      }
    }
    if (activePills) activePills.hidden = !showPill;
  }

  function updateResultCount(visible) {
    if (countLabel) {
      countLabel.textContent = visible + (visible === 1 ? " evento" : " eventos");
    }
  }

  function render(reason) {
    var visible = 0;

    groups.forEach(function (group) {
      var groupRows = slice(group.querySelectorAll("[data-row]"));
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
    updateResultCount(visible);

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

  function setDrawer(open) {
    if (!salaDrawer || !salaToggle) return;
    salaDrawer.hidden = !open;
    salaToggle.setAttribute("aria-expanded", String(open));
    salaToggle.classList.toggle("is-open", open);
    if (filterbar) filterbar.classList.toggle("filterbar--open", open);
    if (open) {
      if (venueSearch) venueSearch.value = "";
      showAllVenues = false;
      applyVenueVisibility();
    }
  }

  function applyVenueVisibility() {
    var query = normalize(venueSearch ? venueSearch.value : "");
    var shown = 0;
    salaOptions.forEach(function (option, index) {
      var match = !query || normalize(option.dataset.search || "").indexOf(query) !== -1;
      var inPreview = Boolean(query) || showAllVenues || index < previewLimit;
      var visible = match && inPreview;
      option.hidden = !visible;
      if (visible) shown += 1;
    });
    if (venueEmpty) venueEmpty.hidden = !(query && shown === 0);
    if (salaShowAll) {
      salaShowAll.hidden = Boolean(query) || salaOptions.length <= previewLimit;
      salaShowAll.setAttribute("aria-expanded", String(showAllVenues));
      salaShowAll.textContent = showAllVenues
        ? "Ver solo las más activas"
        : "Ver todas las salas (" + salaOptions.length + ")";
    }
  }

  function focusToggle() {
    if (!salaToggle) return;
    try {
      salaToggle.focus({ preventScroll: true });
    } catch (error) {
      salaToggle.focus();
    }
  }

  function resetFilters() {
    state.free = false;
    state.venue = null;
    state.query = "";
    state.view = "all";
    if (searchInput) searchInput.value = "";
    if (venueSearch) venueSearch.value = "";
    showAllVenues = false;
    applyVenueVisibility();
    render("clear");
  }

  dayButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      var view = button.dataset.view;
      state.view = state.view === view && view !== "all" ? "all" : view;
      render("view");
    });
  });

  if (freeButton) {
    freeButton.addEventListener("click", function () {
      state.free = !state.free;
      render("free");
    });
  }

  venueChips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      state.venue = state.venue === chip.dataset.venue ? null : chip.dataset.venue;
      render("venue");
    });
  });

  salaOptions.forEach(function (option) {
    option.addEventListener("click", function () {
      var venue = option.dataset.venue || null;
      state.venue = state.venue === venue ? null : venue;
      render("venue");
      setDrawer(false);
      focusToggle();
    });
  });

  if (salaToggle) {
    salaToggle.addEventListener("click", function () {
      setDrawer(Boolean(salaDrawer && salaDrawer.hidden));
    });
  }
  if (salaClose) {
    salaClose.addEventListener("click", function () {
      setDrawer(false);
      focusToggle();
    });
  }
  if (salaShowAll) {
    salaShowAll.addEventListener("click", function () {
      showAllVenues = !showAllVenues;
      applyVenueVisibility();
    });
  }
  if (venueSearch) venueSearch.addEventListener("input", applyVenueVisibility);
  if (salaClear) {
    salaClear.addEventListener("click", function () {
      resetFilters();
      setDrawer(false);
      focusToggle();
    });
  }
  if (activeVenuePill) {
    activeVenuePill.addEventListener("click", function () {
      state.venue = null;
      render("clear-venue");
    });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && salaDrawer && !salaDrawer.hidden) {
      setDrawer(false);
      focusToggle();
    }
  });

  document.addEventListener("click", function (event) {
    if (!salaDrawer || salaDrawer.hidden) return;
    if (salaDrawer.contains(event.target)) return;
    if (salaToggle && salaToggle.contains(event.target)) return;
    setDrawer(false);
  });

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

  if (clearButton) {
    clearButton.addEventListener("click", function () {
      resetFilters();
      setDrawer(false);
    });
  }

  /* ------------------------------------------------------------- carousel */

  var featuredPages = slice(document.querySelectorAll(".featured__page"));
  var featuredPrev = document.getElementById("featured-prev");
  var featuredNext = document.getElementById("featured-next");
  var featuredPageCount = document.getElementById("featured-page-count");
  var featuredIndex = 0;

  function showFeaturedPage(index) {
    if (!featuredPages.length) return;
    featuredIndex = Math.max(0, Math.min(index, featuredPages.length - 1));
    featuredPages.forEach(function (page, position) {
      page.hidden = position !== featuredIndex;
    });
    if (featuredPageCount) {
      featuredPageCount.textContent = featuredIndex + 1 + " / " + featuredPages.length;
    }
    if (featuredPrev) featuredPrev.disabled = featuredIndex === 0;
    if (featuredNext) featuredNext.disabled = featuredIndex === featuredPages.length - 1;
  }

  if (featuredPrev) {
    featuredPrev.addEventListener("click", function () {
      showFeaturedPage(featuredIndex - 1);
    });
  }
  if (featuredNext) {
    featuredNext.addEventListener("click", function () {
      showFeaturedPage(featuredIndex + 1);
    });
  }
  showFeaturedPage(0);

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
