// Display modes: the paper's own colours, or green or amber phosphor like an
// old terminal. The choice lives only in this browser's localStorage. Loaded
// without defer so a saved mode applies before the page is first drawn.
(function () {
  "use strict";

  var KEY = "ledger:display";
  var MODES = ["paper", "green", "amber"];
  var NAMES = { paper: "Paper", green: "Green", amber: "Amber" };
  var root = document.documentElement;

  function current() {
    return root.getAttribute("data-phosphor") || "paper";
  }

  function apply(mode) {
    if (mode === "paper") root.removeAttribute("data-phosphor");
    else root.setAttribute("data-phosphor", mode);
  }

  var saved = null;
  try {
    saved = localStorage.getItem(KEY);
  } catch (e) { /* storage blocked: stay on paper */ }
  if (MODES.indexOf(saved) > 0) apply(saved);

  // The button ships hidden so readers without JavaScript never see a
  // control that does nothing.
  document.addEventListener("DOMContentLoaded", function () {
    var button = document.getElementById("display");
    if (!button) return;

    function label() {
      button.textContent = "Display: " + NAMES[current()];
    }

    label();
    button.hidden = false;
    button.addEventListener("click", function () {
      var next = MODES[(MODES.indexOf(current()) + 1) % MODES.length];
      apply(next);
      try {
        localStorage.setItem(KEY, next);
      } catch (e) { /* nothing to remember, nothing lost */ }
      label();
    });
  });
})();
