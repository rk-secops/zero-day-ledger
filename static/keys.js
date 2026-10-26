// Keyboard shortcuts: j / k step through the stories, o opens the current one,
// p switches the display (display.js), ? opens or closes the reader's guide,
// Esc closes it. This script stores nothing, and the page works the same
// without it.
(function () {
  "use strict";

  var articles = Array.prototype.slice.call(document.querySelectorAll(".dispatch .article"));
  var guide = document.getElementById("guide");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var current = -1;

  function link(article) {
    return article.querySelector(".headline a");
  }

  function select(i) {
    if (articles[current]) articles[current].classList.remove("current");
    current = i;
    var article = articles[i];
    article.classList.add("current");
    article.scrollIntoView({ block: "center", behavior: reduceMotion ? "auto" : "smooth" });
    link(article).focus({ preventScroll: true });
  }

  // With nothing selected yet, start from the first story below the top of
  // the screen rather than jumping back to the top of the page.
  function firstOnScreen() {
    for (var i = 0; i < articles.length; i++) {
      if (articles[i].getBoundingClientRect().top >= 0) return i;
    }
    return articles.length - 1;
  }

  function step(by) {
    if (!articles.length) return;
    var next = current < 0 ? firstOnScreen() : current + by;
    select(Math.max(0, Math.min(articles.length - 1, next)));
  }

  function toggleGuide(open) {
    if (!guide) return;
    guide.open = open;
    if (open) {
      guide.scrollIntoView({ block: "start", behavior: reduceMotion ? "auto" : "smooth" });
      guide.querySelector("summary").focus({ preventScroll: true });
    }
  }

  // Tabbing or clicking onto a headline makes that story the current one.
  articles.forEach(function (article, i) {
    link(article).addEventListener("focus", function () {
      if (i === current) return;
      if (articles[current]) articles[current].classList.remove("current");
      current = i;
      article.classList.add("current");
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var target = e.target;
    if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;

    switch (e.key) {
      case "j": step(1); break;
      case "k": step(-1); break;
      case "o": if (articles[current]) link(articles[current]).click(); break;
      case "p":
        var display = document.getElementById("display");
        if (!display || display.hidden) return;
        display.click();
        break;
      case "?": toggleGuide(!(guide && guide.open)); break;
      case "Escape":
        if (!guide || !guide.open) return;
        toggleGuide(false);
        break;
      default: return;
    }
    e.preventDefault();
  });
})();
