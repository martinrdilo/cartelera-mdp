/* Cartelera MDP — client-side filters, sharing and outbound hooks.
   Reads the inlined JSON payload (#events-data); no network, no dependencies. */
(function () {
  "use strict";

  var payloadElement = document.getElementById("events-data");
  if (!payloadElement) return;
  var data = JSON.parse(payloadElement.textContent);

  var cards = Array.prototype.slice.call(document.querySelectorAll("#all-list .card"));
  var chips = Array.prototype.slice.call(document.querySelectorAll(".filters .chip"));
  var venueSelect = document.getElementById("venue-filter");
  var freeCheckbox = document.getElementById("free-filter");
  var countLabel = document.getElementById("filter-count");
  var emptyMessage = document.getElementById("empty-filter");

  var state = { window: "all", venue: "", freeOnly: false };

  /* Analytics hook. TODO(analytics): forward to GoatCounter (or the provider we
     pick in Fase 3); for now it only names the events worth measuring. */
  function track(name, details) {
    void name;
    void details;
  }

  function inWindow(dates) {
    if (state.window === "all") return true;
    var bounds = data.windows[state.window];
    if (!bounds) return true;
    return dates.some(function (iso) {
      return iso >= bounds.start && iso <= bounds.end;
    });
  }

  function matches(card) {
    if (state.venue && card.dataset.venue !== state.venue) return false;
    if (state.freeOnly && card.dataset.free !== "1") return false;
    return inWindow((card.dataset.dates || "").split(" ").filter(Boolean));
  }

  function apply(reason) {
    var visible = 0;
    cards.forEach(function (card) {
      var show = matches(card);
      card.hidden = !show;
      if (show) visible += 1;
    });
    countLabel.textContent = visible + (visible === 1 ? " evento" : " eventos");
    emptyMessage.hidden = visible !== 0;
    track("filter_change", {
      reason: reason,
      window: state.window,
      venue: state.venue,
      free: state.freeOnly,
      visible: visible
    });
  }

  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      state.window = chip.dataset.window;
      chips.forEach(function (other) {
        var active = other === chip;
        other.classList.toggle("is-active", active);
        other.setAttribute("aria-pressed", String(active));
      });
      apply("window");
    });
  });

  if (venueSelect) {
    venueSelect.addEventListener("change", function () {
      state.venue = venueSelect.value;
      apply("venue");
    });
  }

  if (freeCheckbox) {
    freeCheckbox.addEventListener("change", function () {
      state.freeOnly = freeCheckbox.checked;
      apply("free");
    });
  }

  /* Share and outbound tracking live on the document so both card scopes work. */
  document.addEventListener("click", function (event) {
    var shareButton = event.target.closest(".js-share");
    if (shareButton) {
      var card = shareButton.closest(".card");
      var when = card.querySelector(".card__when").textContent;
      var url = location.href.split("#")[0] + "#" + card.dataset.eventId;
      var text =
        card.dataset.title + " — " + card.dataset.venueName + ", " + when +
        " · Entradas en " + data.site.name + ": " + url;
      track("share_whatsapp", { event_id: card.dataset.eventId });
      window.open("https://wa.me/?text=" + encodeURIComponent(text), "_blank", "noopener");
      return;
    }
    var outbound = event.target.closest('[data-outbound="ticket"]');
    if (outbound) {
      track("outbound_ticket", { event_id: outbound.dataset.eventId, href: outbound.href });
    }
  });

  /* Posters come from the sources: a broken URL falls back to the placeholder. */
  Array.prototype.forEach.call(document.querySelectorAll(".card__media img"), function (img) {
    img.addEventListener("error", function () {
      var media = img.parentElement;
      var card = media.closest(".card");
      media.classList.add("card__media--empty");
      media.textContent = (card.dataset.title || "?").trim().charAt(0).toUpperCase();
    });
  });

  apply("init");
})();
