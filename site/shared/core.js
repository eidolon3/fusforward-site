/* FUS Forward transcripts: the data and the player that web/index.html and web/explained.html share.
 *
 * Load with <script src="../shared/core.js"></script>, before site.js. Works from a web server or opened from disk.
 *
 *   FF.episodes()                 -> Promise<[{n, title, display_title, full_title, date, duration_s, guests,
 *                                              affiliation, hosts, audio_url, link, notes, art, words, talk_min}]>
 *                                    (words: the episode's word count)
 *   FF.episode(n)                 -> Promise<{...the episodes() entry, speakers, words, turns, starts, x}>
 *                                    words[i] = {i, w, s, e, p, who, unc, ev, cut, ct}; turns[k] = {k, p, who, s, e, w0, w1};
 *                                    starts[i] = words[i].s
 *                                    (cut: hidden in the clean read; ct: its repaired text, if any;
 *                                    x: "Elsewhere in the series", for an episode with guests)
 *   FF.rows()                     -> Promise<[[n, s, who, text]]>  every search chunk (<= 35 words), in order
 *   FF.glossary()                 -> Promise<[{term, kind: "term"|"person", def, count, episodes, hits: [[n, s, who]]}]>
 *   FF.script(src)                -> Promise: loads a script once (a failed one is tried again on the next call)
 *   FF.renderReadable(el, ep, {paraWords, before, name, clean})  the readable transcript, styled by
 *                                    shared/transcript.css (see the comment on the function)
 *   FF.release(n)                 forget episode n's decoded transcript (FF.episode(n) loads it again)
 *   new FF.Player(audioEl, ep)    .seek(s, play=true) .toggle() .retry() .on/.off("word", i => ...) .on/.off("time", s => ...)
 *                                    .refresh(t) re-announces the word at t · .destroy(); a new Player on the
 *                                    same audio element replaces the old one
 *   FF.bindTranscript(el, player, {spans}) -> {spans, unbind}: click a word to seek; the current word gets .now,
 *                                    its turn gets .live. Binding the same element again replaces the old binding.
 *   FF.fmt(s) "1:02:13" · FF.link(n, s) "#/record/16?t=1834" (index.html's route; s optional) · FF.params() {ep, t, q}
 *   FF.role(name) "charles" | "keith" | "narrator" | "guest" · FF.initials(name)
 *   FF.esc(s) escapes text for HTML and attributes · FF.safeUrl(u) u if it is http(s), else "#" (for data-built links)
 */
(function () {
  const here = document.currentScript.src;
  const DATA = new URL("../data/", here).href;
  const cache = {};

  function script(src) {
    if (!cache[src]) {
      cache[src] = new Promise((ok, fail) => {
        const s = document.createElement("script");
        s.src = src;
        s.onload = ok;
        // A failed attempt is forgotten, so the next call tries the network again.
        s.onerror = () => { delete cache[src]; s.remove(); fail(new Error("could not load " + src)); };
        document.head.appendChild(s);
      });
    }
    return cache[src];
  }
  const load = src => script(DATA + src);   // a file in data/

  const epWait = {};
  const FF = {
    _ep(n, data) { (epWait[n] = epWait[n] || {}).data = data; },

    async episodes() {
      await load("episodes.js");
      return window.FF_EPISODES;
    },

    episode(n) {
      n = Number(n);
      const E = epWait[n] = epWait[n] || {};
      // one decode per episode, shared by every caller; a failed one is forgotten so the next call retries
      return E.p || (E.p = FF._decode(n, E).catch(err => { E.p = null; throw err; }));
    },

    async _decode(n, E) {
      await load(`ep/${String(n).padStart(2, "0")}.js`);
      // The compact columns (scripts/build_site_data.py): start deltas and lengths in hundredths of a second, speaker
      // indexes in base 36, flags as one character each.
      const { ww, ws, wd, wp, wf, c, ...d } = E.data, sp = d.speakers;
      const words = new Array(ww.length);
      for (let i = 0, cs = 0; i < ww.length; i++) {
        cs += ws[i];
        const p = parseInt(wp[i], 36), f = wf.charCodeAt(i) - 48;
        // cut: hidden in the clean read; ct: how the clean read shows the word, where that differs.
        words[i] = { i, w: ww[i], s: cs / 100, e: (cs + wd[i]) / 100, p, who: sp[p], unc: !!(f & 1), ev: !!(f & 2), cut: !!(f & 4), ct: c ? c[i] : undefined };
      }
      const turns = d.turns.map(([p, s, e, w0, w1], k) => ({ k, p, who: sp[p], s, e, w0, w1 }));
      const meta = (await FF.episodes()).find(x => x.n === n);
      E.data = null;  // decoded once; drop the raw columns
      // The metadata wins where both have a field (the file's title is the raw feed title); words is the word list here.
      return (E.ep = { ...d, ...meta, words, turns, starts: words.map(w => w.s) });
    },

    /** Forget episode n's decoded transcript (a page that keeps only a few in memory); FF.episode(n) loads it again. */
    release(n) {
      n = Number(n); const E = epWait[n]; if (!E || !E.ep) return;   // one still loading is left alone
      const src = DATA + `ep/${String(n).padStart(2, "0")}.js`;
      delete epWait[n]; delete cache[src];
      for (const s of document.querySelectorAll("script[src]")) if (s.src === src) s.remove();
    },

    script,

    async glossary() {
      await load("glossary.js");
      return window.FF_GLOSSARY;
    },

    async rows() {
      await load("search.js");
      return window.FF_SEARCH;
    },

    /* The readable transcript (style it with shared/transcript.css).
     * Each turn: the speaker's name and time on their own line, then the text in paragraphs of about
     * `paraWords` words split at sentence ends. Interjections (turns of <= 3 words, e.g. "Yeah.") are
     * folded away, so an answer interrupted by "Mm-hmm" reads as one block.
     * Hooks: before(turn) -> html inserted before a turn (chapter headings);
     *        name(who) -> label text (default: the full name).
     * clean: true shows the clean read: fillers, stutters, false starts and sound tags hidden (their spans
     * stay, empty and hidden, so playback still finds them), punctuation and capitals repaired. */
    renderReadable(el, ep, { paraWords = 80, before, name, clean = false } = {}) {
      const label = name || (w => (w.startsWith("Unknown") ? "Unidentified speaker" : w));
      const gone = w => w.ev || (clean && w.cut);  // not counted as reading words
      const hid = w => clean && w.cut;              // not shown at all
      const short = t => {
        const ws = ep.words.slice(t.w0, t.w1).filter(w => !gone(w));
        return ws.length <= 3 && (ws.length > 0 || clean);
      };
      const wordsHtml = (a, b) => ep.words.slice(a, b).map(w => clean && w.cut
        ? `<span class="w ff-cut" data-i="${w.i}" hidden></span>`
        : `<span class="w${w.unc ? " unc" : ""}${w.ev ? " ev" : ""}" data-i="${w.i}"${w.unc ? ' title="The transcription model was unsure of this word"' : ""}>${esc(clean && w.ct ? w.ct : w.w)}</span>`
      ).join(" ");  // the spaces around a hidden span collapse into one
      const shown = w => (clean && w.ct ? w.ct : w.w);
      const ends = w => /[.?!…]["”’)]*$/.test(shown(w));
      const html = [];
      let open = null;  // the section still accepting paragraphs: {who, k}
      // The paragraph being filled: word ranges (a paragraph can span a folded interjection), its count of
      // shown words, and whether its last shown word ends a sentence. Folded turns met while it is open wait
      // in `held` and follow it, so a paragraph holds only its own speaker's words.
      let cur = null, held = [];
      const flush = () => {
        if (cur) {
          html.push(`<p class="ff-p">${cur.parts.map(([a, b]) => wordsHtml(a, b)).join(" ")}</p>`);
          cur = null;
        }
        if (held.length) { html.push(...held); held = []; }
      };
      const close = () => { flush(); if (open) { html.push("</section>"); open = null; } };
      // Add [w0, w1) of turn t to the open section, breaking paragraphs at sentence ends.
      const fill = (t, w0, w1) => {
        let start = w0;
        for (let i = w0; i < w1; i++) {
          const w = ep.words[i];
          if (hid(w)) continue;
          if (!cur) cur = { parts: [], n: 0, end: false };
          if (gone(w)) continue;  // a sound tag shows but does not count
          cur.n++; cur.end = ends(w);
          if ((cur.end && cur.n >= paraWords * 0.7) || cur.n >= paraWords * 1.6) { cur.parts.push([start, i + 1]); start = i + 1; flush(); }
        }
        if (start < w1) {
          if (cur) cur.parts.push([start, w1]);
          else html.push(wordsHtml(start, w1));  // only hidden words left: keep their spans, outside any paragraph
        }
      };
      const visibleIn = t => ep.words.slice(t.w0, t.w1).some(w => !hid(w));
      ep.turns.forEach((t, idx) => {
        const role = FF.role(t.who);
        // A turn with nothing to show (every word hidden by the clean read), or a folded interjection:
        // keep the words (so playback can still find them) but out of the reading flow.
        if (!visibleIn(t) || (short(t) && idx > 0)) {
          const f = `<span class="ff-folded" data-k="${t.k}" hidden>${wordsHtml(t.w0, t.w1)}</span>`;
          if (cur) held.push(f); else html.push(f);
          return;
        }
        const pre = before ? before(t) : "";
        if (pre) { close(); html.push(pre); }
        if (open && open.who === t.who) {
          // Same speaker continuing after a folded interjection: carry on in the same block, and in the same
          // paragraph unless that paragraph already ended a sentence at a good length.
          if (cur && cur.end && cur.n >= paraWords * 0.7) flush();
        } else {
          close();
          html.push(`<section class="turn r-${role}" data-k="${t.k}"><div class="ff-who">` +
            `<span class="ff-name">${esc(label(t.who))}</span>` +
            `<a class="ff-ts" href="${FF.link(ep.n, t.s)}" data-s="${t.s}">${FF.fmt(t.s)}</a></div>`);
          open = { who: t.who, k: t.k };
        }
        fill(t, t.w0, t.w1);
      });
      close();
      el.innerHTML = `<div class="ff-tx${clean ? " ff-clean" : ""}">${html.join("")}</div>`;
    },

    /** The clean read as plain text, laid out as renderReadable lays it out: a block per speaker, paragraphs of
     *  about paraWords words, folded interjections left out. The site's text download; scripts/build_site_data.py
     *  (clean_text) writes the same text to out/clean-text/. Change the three together. */
    cleanText(ep, { paraWords = 80, name = w => w } = {}) {
      const out = []; let block = null, cur = null;
      const flush = () => { if (cur && cur.ws.length) block.paras.push(cur.ws.join(" ")); cur = null; };
      const close = () => { flush(); if (block) out.push(`[${FF.fmt(block.s)}] ${name(block.who)}: ${block.paras.join("\n\n")}`); block = null; };
      ep.turns.forEach((t, idx) => {
        const ws = ep.words.slice(t.w0, t.w1).filter(w => !w.cut);
        if (!ws.length || (ws.length <= 3 && idx > 0)) return;   // nothing shown, or a folded interjection
        if (block && block.who === t.who) { if (cur && cur.end && cur.n >= paraWords * 0.7) flush(); }
        else { close(); block = { who: t.who, s: t.s, paras: [] }; }
        for (const w of ws) {
          const x = w.ct ? w.ct : w.w;
          if (!cur) cur = { ws: [], n: 0, end: false };
          cur.ws.push(x + (w.unc ? " [?]" : "")); cur.n++; cur.end = /[.?!…]["”’)]*$/.test(x);
          if ((cur.end && cur.n >= paraWords * 0.7) || cur.n >= paraWords * 1.6) flush();
        }
      });
      close();
      return out.join("\n\n") + "\n";
    },

    bindTranscript(el, player, { spans: known } = {}) {
      if (el._ffUnbind) el._ffUnbind();  // binding the same element again replaces the old binding
      const spans = known || [];         // known: el's word spans by index, if the caller already has them
      if (!known) for (const s of el.getElementsByClassName("w")) { const i = s.getAttribute("data-i"); if (i !== null) spans[+i] = s; }
      let cur = null, curTurn = null;
      const onClick = e => {
        if (!getSelection().isCollapsed) return;  // the click that ends a text selection is not a seek
        const w = e.target.closest(".w[data-i]");
        const ts = e.target.closest("[data-s]");
        if (w) player.seek(player.ep.words[+w.dataset.i].s);
        else if (ts) { e.preventDefault(); player.seek(+ts.dataset.s); }
      };
      el.addEventListener("click", onClick);
      el._ffUnbind = () => {
        el.removeEventListener("click", onClick);
        player.off("word", onWord);
        delete el._ffUnbind;
      };
      const onWord = i => {
        if (cur) cur.classList.remove("now");
        cur = spans[i];
        // A word hidden by the clean read: light up the last shown word before it.
        for (let j = i - 1; cur && cur.hidden && j >= 0 && j > i - 40; j--) if (spans[j] && !spans[j].hidden) cur = spans[j];
        if (!cur || cur.hidden) { cur = null; return; }
        cur.classList.add("now");
        // The turn block, not a folded interjection's own hidden span, so the live bar stays put.
        const t = cur.closest(".turn") || cur.closest("[data-k]");
        if (t !== curTurn) {
          if (curTurn) curTurn.classList.remove("live");
          curTurn = t;
          if (t) t.classList.add("live");
        }
      };
      player.on("word", onWord);
      return { spans, unbind: el._ffUnbind };
    },

    fmt(s) {
      s = Math.max(0, Math.floor(s));
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0");
      return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`;
    },
    link: (n, s) => "#/record/" + n + (s != null && isFinite(s) ? "?t=" + Math.max(0, Math.floor(s)) : ""),
    params() {
      const p = new URLSearchParams(location.search);
      const num = k => { const v = p.get(k); return v != null && v.trim() !== "" && isFinite(+v) ? +v : null; };  // junk ("abc") -> null
      const t = num("t");
      return { ep: num("ep"), t: t == null ? null : Math.max(0, t), q: p.get("q") || "" };
    },
    // The hosts' names are in every episode's metadata (hosts); these two are the transcript's colour roles
    // (shared/transcript.css .r-charles, .r-keith), so a change of host means a change here and there.
    role(name) {
      if (name === "Charles Caskey") return "charles";
      if (name === "Keith Murphy") return "keith";
      if (name === "Intro narrator") return "narrator";
      return "guest";
    },
    initials(name) { return name.split(/[\s-]+/).filter(Boolean).map(x => x[0]).join("").slice(0, 2).toUpperCase(); },
    esc,
    // Links built from data: only http(s), so a "javascript:" URL in a data file can never run.
    safeUrl: u => /^https?:\/\//i.test(u || "") ? u : "#",
  };

  class Player {
    constructor(audio, ep) {
      if (audio._ffPlayer) audio._ffPlayer.destroy();  // one Player per audio element
      audio._ffPlayer = this;
      this.a = audio; this.ep = ep; this.cbs = { word: [], time: [] }; this.i = -1;
      if (audio.src !== ep.audio_url) {
        // Until the new source's metadata arrives, the element can still report the old one as ready,
        // and a seek would land on the old media and be lost.
        audio.src = ep.audio_url; audio.preload = "metadata"; this.fresh = true;
        this._ready = () => { this.fresh = false; this._ready = null; };
        audio.addEventListener("loadedmetadata", this._ready, { once: true });
      }
      this._go = null;  // a seek waiting for this source's metadata
      const tick = () => {
        this._update();
        if (!this.a.paused) this.raf = requestAnimationFrame(tick);
      };
      this._h = {
        play: () => { cancelAnimationFrame(this.raf); tick(); },
        seeked: () => this._update(),
        timeupdate: () => this._update(),
      };
      for (const [ev, fn] of Object.entries(this._h)) audio.addEventListener(ev, fn);
    }
    on(ev, cb) { this.cbs[ev].push(cb); return this; }
    off(ev, cb) { this.cbs[ev] = this.cbs[ev].filter(x => x !== cb); return this; }
    /** Re-announce the word at time t (default: now), e.g. to paint a fresh view or a deep link before audio loads. */
    refresh(t = this.a.currentTime) { this.i = -1; this._update(t); }
    /** Detach from the audio element; call before reusing it for another episode (new Player does this for you). */
    destroy() {
      cancelAnimationFrame(this.raf);
      for (const [ev, fn] of Object.entries(this._h)) this.a.removeEventListener(ev, fn);
      this._cancelSeek();  // a seek still waiting must never land on the next episode's source
      if (this._ready) { this.a.removeEventListener("loadedmetadata", this._ready); this._ready = null; }
      this.cbs = { word: [], time: [] };
      this.dead = true;
      if (this.a._ffPlayer === this) delete this.a._ffPlayer;
    }
    _cancelSeek() { if (this._go) { this.a.removeEventListener("loadedmetadata", this._go); this._go = null; } }
    seek(s, play = true) {
      this._cancelSeek();  // a newer seek replaces one still waiting
      const src = this.ep.audio_url;
      const go = () => {
        if (this._go === go) this._go = null;
        if (this.dead || this.a._ffPlayer !== this || this.a.src !== src) return;
        this.a.currentTime = s; if (play) this.a.play().catch(() => {}); this._update(s);
      };
      if (this.a.readyState >= 1 && !this.fresh) go();
      else {
        this._update(s);
        this._go = go;
        this.a.addEventListener("loadedmetadata", go, { once: true });
        if (this.a.readyState === 0 && !this.fresh) this.a.load();
      }
    }
    toggle() {                                      // after a failed download, play means: fetch it again
      if (this.a.paused && this.a.error) return this.retry();
      this.a.paused ? this.a.play().catch(() => {}) : this.a.pause();
    }
    /** After the source failed to download: fetch it again, land a seek that was still waiting (or the time it
     *  had reached), and play. */
    retry() {
      if (this.dead) return;
      const waiting = !!this._go, t = this.a.currentTime;
      this.a.load();
      if (waiting) this.a.play().catch(() => {}); else this.seek(t, true);
    }
    _update(t = this.a.currentTime) {
      this.cbs.time.forEach(cb => cb(t));
      const st = this.ep.starts;
      let lo = 0, hi = st.length - 1, i = -1;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (st[mid] <= t + 0.05) { i = mid; lo = mid + 1; } else hi = mid - 1; }
      if (i !== this.i) { this.i = i; if (i >= 0) this.cbs.word.forEach(cb => cb(i)); }
    }
  }
  FF.Player = Player;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  window.FF = FF;
})();
