/* Mode toggle, mobile nav, and copy buttons. No dependencies. */
(function () {
  var root = document.documentElement;
  var lightQuery = window.matchMedia("(prefers-color-scheme: light)");

  function currentMode() {
    var m = root.getAttribute("data-mode");
    if (m === "dark" || m === "light") return m;
    return lightQuery.matches ? "light" : "dark";
  }

  var toggle = document.querySelector(".mode-toggle");
  if (toggle) {
    var relabel = function () {
      toggle.setAttribute("aria-label", currentMode() === "dark" ? "Switch to light mode" : "Switch to dark mode");
    };
    relabel();
    toggle.addEventListener("click", function () {
      var next = currentMode() === "dark" ? "light" : "dark";
      root.setAttribute("data-mode", next);
      try { localStorage.setItem("ce-mode", next); } catch (e) { /* storage unavailable; mode still applies for this page */ }
      relabel();
    });
  }

  var header = document.querySelector(".site-header");
  var navButton = document.querySelector(".nav-toggle");
  if (header && navButton) {
    navButton.addEventListener("click", function () {
      var open = header.classList.toggle("open");
      navButton.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-copy]"), function (button) {
    var idle = button.textContent;
    button.addEventListener("click", function () {
      var text = button.getAttribute("data-copy");
      if (!navigator.clipboard) { button.textContent = "Select the text to copy"; return; }
      navigator.clipboard.writeText(text).then(function () {
        button.textContent = "Copied";
        button.setAttribute("data-done", "");
        setTimeout(function () { button.textContent = idle; button.removeAttribute("data-done"); }, 1800);
      }, function () {
        button.textContent = "Select the text to copy";
      });
    });
  });
})();

/* Scroll spy for the "On this page" list on docs pages. */
(function () {
  var toc = document.querySelector(".toc");
  if (!toc || !("IntersectionObserver" in window)) return;
  var links = Array.prototype.slice.call(toc.querySelectorAll("a[href^='#']"));
  var headings = links.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); }).filter(Boolean);
  if (!headings.length) return;

  function setActive(id) {
    links.forEach(function (a) {
      var on = a.getAttribute("href") === "#" + id;
      if (on) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
    });
  }

  /* The active section is the last heading that has crossed the top band of the viewport. */
  function update() {
    var line = window.innerHeight * 0.25;
    var current = headings[0];
    for (var i = 0; i < headings.length; i++) {
      if (headings[i].getBoundingClientRect().top <= line) current = headings[i]; else break;
    }
    setActive(current.id);
  }
  var observer = new IntersectionObserver(update, { rootMargin: "-25% 0px -60% 0px", threshold: [0, 1] });
  headings.forEach(function (h) { observer.observe(h); });
  window.addEventListener("scroll", update, { passive: true });
  update();
})();
