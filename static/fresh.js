// Marks stories that weren't on the page at the reader's last visit. The list
// of story links seen lives only in this browser's localStorage and is never
// sent anywhere. Reloads within half an hour count as the same visit, so the
// marks survive a refresh. First visits and blocked storage mark nothing.
(function () {
  "use strict";

  var KEY = "ledger:seen";
  var SAME_VISIT_MS = 30 * 60 * 1000;

  var articles = document.querySelectorAll(".dispatch .article");
  var urls = [];
  articles.forEach(function (article) {
    var link = article.querySelector(".headline a");
    if (link) urls.push(link.href);
  });
  if (!urls.length) return;

  var saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(KEY));
  } catch (e) { /* storage blocked or corrupt: treat as a first visit */ }

  var now = Date.now();
  var baseline = null;
  if (saved && Array.isArray(saved.seen)) {
    var sameVisit = now - saved.at < SAME_VISIT_MS && Array.isArray(saved.base);
    baseline = sameVisit ? saved.base : saved.seen;
  }

  try {
    localStorage.setItem(KEY, JSON.stringify({ seen: urls, base: baseline || urls, at: now }));
  } catch (e) { /* nothing to remember, nothing lost */ }

  if (!baseline) return;
  var known = new Set(baseline);
  articles.forEach(function (article) {
    var link = article.querySelector(".headline a");
    if (!link || known.has(link.href)) return;
    var mark = document.createElement("span");
    mark.className = "fresh";
    mark.textContent = "New";
    mark.title = "New since your last visit";
    link.parentNode.insertBefore(mark, link);
  });
})();
