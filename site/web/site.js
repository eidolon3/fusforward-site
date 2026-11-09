/* FUS Forward Records: what every page shares. The theme toggle (remembered across pages), the header search
   (it goes to the episode search on index.html), "/" to focus it, and the current section in the nav.
   Load after ../shared/core.js (it uses FF.esc and FF.safeUrl).
   Everything this site keeps in the browser is under the "ffweb." prefix. */
(function () {
  const K = "ffweb.";
  // Every key the site uses. Anything else under the prefix is no longer used and is swept on load.
  const LIVE = new Set(["theme", "rate", "sort", "clean", "pos", "notes"]);
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) { const k = localStorage.key(i); if (k && k.startsWith(K) && !LIVE.has(k.slice(K.length))) localStorage.removeItem(k); }
  } catch (e) {}
  // get(key, default, ok): a value read back must have the default's type (an array for [], a plain object for {},
  // a finite number for 1) and pass ok(value) when given; anything else (a hand edit, a value of the wrong shape)
  // is discarded and the default returned, so a junk setting can never stop a page.
  const kind = v => Array.isArray(v) ? "array" : v === null ? "null" : typeof v;
  const get = (k, d, ok) => {
    let raw; try { raw = localStorage.getItem(K + k); } catch (e) { return d; }
    if (raw == null) return d;
    try {
      const v = JSON.parse(raw);
      if ((d === undefined || kind(v) === kind(d)) && (typeof v !== "number" || isFinite(v)) && (!ok || ok(v))) return v;
    } catch (e) {}
    del(k); return d;
  };
  const set = (k, v) => { try { localStorage.setItem(K + k, JSON.stringify(v)); } catch (e) {} };
  function del(k) { try { localStorage.removeItem(K + k); } catch (e) {} }
  // Episode art at the size it is shown: assets/ep/NN.jpg (640 px) also exists as sm/NN.jpg (160) and md/NN.jpg (320),
  // written by scripts/make_thumbs.py. art() gives an <img>'s src, srcset and sizes; setArt() does the same on an element.
  const thumbs = a => { const m = /^assets\/ep\/(\d+\.jpg)$/.exec(a || ""); return m ? `../assets/ep/sm/${m[1]} 160w, ../assets/ep/md/${m[1]} 320w, ../${a} 640w` : ""; };
  const esc = FF.esc;
  const art = (a, sizes) => { const s = thumbs(a); return `src="../${esc(a)}"` + (s ? ` srcset="${s}" sizes="${esc(sizes)}"` : ""); };
  const setArt = (img, a, sizes) => {                  // no art: no image, rather than a request for "../undefined"
    const s = thumbs(a); if (s) { img.sizes = sizes; img.srcset = s; } else img.removeAttribute("srcset");
    if (a) img.src = "../" + a; else img.removeAttribute("src");
  };
  // A page whose data did not download: say so, with a button that tries again (by default, a reload).
  function fail(el, what, retry) {
    if (!el) return;
    el.hidden = false;
    el.innerHTML = `<div class="ffw-fail" role="alert"><p><b>${esc(what)} couldn’t load.</b> Check your connection and try again.</p><button type="button">Try again</button></div>`;
    el.querySelector("button").addEventListener("click", () => (retry || (() => location.reload()))());
  }
  // Audio that fails to load: a calm note with Try again and the episode on Spotify, and the page's play buttons
  // reset (reset()). A page's "Playing …" announcement waits for sound: pass it to say() instead of writing it.
  let note = null, noteFrom = null, noteT = 0;
  function hideNote() { if (note && note.classList.contains("on")) { note.classList.remove("on"); note.textContent = ""; } }
  function showNote(href, retry) {
    if (!note) {
      note = document.createElement("div"); note.className = "ffw-note"; note.setAttribute("role", "status"); document.body.appendChild(note);
      note.addEventListener("click", e => {
        const b = e.target instanceof Element && e.target.closest("[data-ffw]"); if (!b) return;
        const back = noteFrom && document.contains(noteFrom) ? noteFrom : null; hideNote();
        if (b.dataset.ffw === "retry" && note._retry) note._retry();
        if (back) back.focus({ preventScroll: true });
      });
      note.addEventListener("keydown", e => { if (e.key === "Escape") { hideNote(); if (noteFrom && document.contains(noteFrom)) noteFrom.focus({ preventScroll: true }); } });
    }
    noteFrom = document.activeElement !== document.body ? document.activeElement : null;
    note._retry = retry; note.textContent = ""; note.classList.add("on"); clearTimeout(noteT);
    const url = FF.safeUrl(href);
    noteT = setTimeout(() => {           // filled once the live region is showing, so it is announced
      note.innerHTML = `<p>The audio couldn’t load. ${retry ? `<button type="button" data-ffw="retry">Try again</button>` : "Try again"} or ` +
        (url !== "#" ? `<a href="${esc(url)}" target="_blank" rel="noopener">listen on Spotify<span class="vh"> (opens in a new tab)</span></a>` : "listen on Spotify") +
        `.</p><button type="button" class="x" data-ffw="close" aria-label="Dismiss">×</button>`;
    }, 40);
  }
  function watchAudio(audio, { link, retry, reset } = {}) {
    let say = null;
    audio.addEventListener("playing", () => { clearTimeout(noteT); hideNote(); if (say) { const f = say; say = null; f(); } });
    audio.addEventListener("error", () => {
      if (!audio.getAttribute("src")) return;          // an emptied player, not a failed download
      say = null;
      try { audio.pause(); } catch (e) {}
      if (reset) reset();
      showNote(link ? link() : null, retry);
    });
    return { say(f) { say = f; } };
  }
  // While something slow loads: a thin bar across the top, shown only if it takes more than 150 ms (so a quick
  // load shows nothing at all). busy(true) when it starts, busy(false) when it ends; calls can overlap.
  let busyN = 0, busyT = 0, bar = null;
  function busy(on) {
    if (!bar) { bar = document.createElement("div"); bar.className = "ffw-bar"; bar.setAttribute("aria-hidden", "true"); document.body.appendChild(bar); }
    busyN = Math.max(0, busyN + (on ? 1 : -1)); clearTimeout(busyT);
    if (busyN) busyT = setTimeout(() => bar.classList.add("on"), 150); else bar.classList.remove("on");
  }
  window.FFW = { get, set, art, setArt, fail, watchAudio, busy };

  const root = document.documentElement, btn = document.getElementById("theme"), page = document.body.dataset.page;
  function applyTheme(t) {
    root.dataset.theme = t === "light" ? "light" : "dark";
    if (btn) btn.setAttribute("aria-label", root.dataset.theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
    dispatchEvent(new CustomEvent("ffweb:theme", { detail: root.dataset.theme }));
  }
  applyTheme(get("theme", "dark"));   // dark unless the visitor chose light
  if (btn) btn.addEventListener("click", () => { const t = root.dataset.theme === "dark" ? "light" : "dark"; set("theme", t); applyTheme(t); });
  addEventListener("storage", e => { if (e.key === K + "theme") applyTheme(get("theme", "dark")); });   // another tab switched

  // The header search. On the episodes page that page's own script searches as you type; elsewhere Enter goes there.
  const q = document.getElementById("q");
  if (q && matchMedia("(max-width:560px)").matches) q.placeholder = "Search";   // site.css folds the box to its icon there
  if (q && page !== "episodes") {
    q.addEventListener("keydown", e => {
      if (e.key === "Enter") { const v = q.value.trim(); location.href = "index.html#/search?q=" + encodeURIComponent(v); }
      else if (e.key === "Escape") { q.value = ""; q.blur(); }
    });
    document.addEventListener("keydown", e => {
      const tg = e.target instanceof Element ? e.target : document.body;
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || tg.closest("input, textarea, select, [contenteditable], dialog[open]")) return;
      e.preventDefault(); q.focus(); q.select();
    });
  }

  // "Skip to content": focus the content, without putting "#main" in the address (index.html reads it as a route).
  document.addEventListener("click", e => {
    const a = e.target instanceof Element && e.target.closest("a.skip"), to = a && document.getElementById(a.getAttribute("href").slice(1));
    if (to) { e.preventDefault(); to.focus({ preventScroll: true }); to.scrollIntoView(); }
  });
  // The current section (marked aria-current in each page's HTML): scrolled into view where the nav scrolls sideways.
  const nav = document.querySelector(".nav"), on = nav && nav.querySelector("[aria-current]");
  if (on && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = Math.max(0, on.offsetLeft - nav.offsetLeft - 24);
})();
