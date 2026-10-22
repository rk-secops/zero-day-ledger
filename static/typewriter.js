// Types each headline out letter by letter as it scrolls into view, one at a
// time. The page is fully readable without this script: headlines are plain
// HTML, and the link keeps its full text as an aria-label while typing.
(function () {
  "use strict";

  var links = document.querySelectorAll(".headline a");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!links.length || reduceMotion || !("IntersectionObserver" in window)) return;

  var jobs = new Map();
  var queue = [];
  var busy = false;

  links.forEach(function (link) {
    var text = link.textContent;
    var typed = document.createElement("span");
    var cursor = document.createElement("span");
    var rest = document.createElement("span");
    cursor.className = "cursor";
    rest.className = "untyped";
    rest.textContent = text;
    link.setAttribute("aria-label", text);
    link.replaceChildren(typed, cursor, rest);
    jobs.set(link, { text: text, typed: typed, cursor: cursor, rest: rest });
  });

  function typeNext() {
    var job = queue.shift();
    if (!job) { busy = false; return; }
    busy = true;
    var n = 0;
    (function step() {
      n += 1;
      job.typed.textContent = job.text.slice(0, n);
      job.rest.textContent = job.text.slice(n);
      if (n < job.text.length) {
        setTimeout(step, 14 + Math.random() * 22);
      } else {
        job.cursor.remove();
        setTimeout(typeNext, 90);
      }
    })();
  }

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      observer.unobserve(entry.target);
      queue.push(jobs.get(entry.target));
    });
    if (!busy) typeNext();
  });
  links.forEach(function (link) { observer.observe(link); });
})();
