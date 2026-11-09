# CLAUDE.md: FUS Forward Records

You are working on the transcripts and website of **FUS Forward**, a podcast about focused-ultrasound
neuromodulation hosted by **Charles Caskey** and **Keith Murphy**. The owner is Keith. This file is your guide:
what everything is, how it fits together, and exactly how to do the jobs he will ask for. Read it before changing
anything. When this file and the code disagree, the code wins; fix this file in the same change.

## Rules that always apply

1. **Never commit or print `.env`.** It holds the ElevenLabs API key. It is in `.gitignore`; keep it there. Read the
   key only through `scripts/common.py: secret()`.
2. **Transcription is the only thing that costs money.** `scripts/transcribe.py` (which `add_episode.py` calls)
   sends the audio to ElevenLabs: about $0.27 per audio hour (scribe_v2 $0.22 plus $0.05 for key terms, as of
   late 2026), so well under a dollar an episode. `add_episode.py` prints the estimate and asks before it
   transcribes; you have no keyboard, so with no `--yes` it answers No and stops. Tell Keith the estimate, and run
   it with `--yes` only after he agrees. Never re-transcribe an episode that already has `out/raw/NN.json` (fix it
   with `data/fixes` and rebuild instead).
3. **Transcripts are what was said.** Never reword, summarise or "improve" a transcript. Corrections go in
   `data/fixes/NN.json` (a misheard word, a wrong speaker) and only when the context makes the right word clear.
   If you can't be sure without hearing the audio, mark the word *uncertain* instead of changing it. Never invent
   names, numbers or titles.
4. **Never edit generated files by hand.** `out/episodes`, `out/text`, `out/vtt`, `out/srt`, and everything in
   `site/data/` are rebuilt by scripts. Change the inputs (`data/`, the lists inside the build scripts,
   `site/web/essentials.js`) and rebuild.
5. **The site stays static.** Plain HTML, CSS and JavaScript, no build step, no framework, no tracking, works
   opened from disk or from any static host. Keep it fast: the home page loads about 0.6 MB.
6. **Check your work in a browser** after any site change (see "Testing"). Light and dark theme, desktop and phone width.
7. **Escape anything from data.** Text from the feed, transcripts or URLs goes into the page through `FF.esc()`;
   links built from data go through `FF.safeUrl()` (http/https only).

## The map

```
site/                    THE WEBSITE (publish these four folders + favicon.ico)
  web/index.html         home (#/), episode pages (#/record/16?t=600), search (#/search?q=skull); one page, hash routes
  web/explained.html     "Explained": the clips as a course, all listed on the left, one at a time on the right
  web/essentials.js      which clips Explained shows, in which chapters (edit this to change Explained)
  web/site.css           colours (light + dark), fonts, header and footer shared by both pages
  web/site.js            theme toggle, header search, saved settings (localStorage, "ffweb." prefix), art helpers
  shared/core.js         the engine: loads data, decodes transcripts, renders the readable transcript, the synced player
  shared/transcript.css  how a transcript looks
  data/                  BUILT by scripts: episodes.js, ep/NN.js (each transcript), search.js, glossary.js,
                         explainers.js, mentions.js, quotes.js
  assets/ep/NN.jpg       episode art 640x360 (+ sm/ 160px and md/ 320px copies); assets/cover.jpg = show cover
  serve.py               local preview server: python site/serve.py -> http://localhost:8770/web/ (--port to change)

scripts/                 THE PIPELINE (each script's docstring says how to run it; all run from the project folder)
  common.py              shared paths (ROOT, AUDIO), the API key, downloads, episode and fixes loading (with the
                         fixes format check), shared rules (HOSTS, FOLD_MAX, LOW_SIM), UTF-8 console output
  add_episode.py         runs everything below, in order, for new episodes
  fetch_feed.py          RSS feed -> data/episodes.json; the audio of episodes not transcribed yet -> audio/
  fetch_art.py           episode art (Spotify, checked by title; see the docstring) -> site/assets/ep/
  make_thumbs.py         the small art copies
  fetch_pubmed.py        a guest's papers from PubMed -> data/pubmed/NN.txt (to write the terms list);
                         --pmid adds a Show Notes paper's record to data/pubmed/mentioned.txt
  build_terms.py         key terms for the transcriber: data/terms/core.txt + people.txt + companies.txt + NN.txt
  transcribe.py          ElevenLabs scribe_v2 -> out/raw/NN.json (the one paid step, ~$0.27/hour)
  name_speakers.py       speaker names: the hosts by voiceprint, others = the guest -> out/speakers/NN.json
  build_episode.py       raw + speakers + data/fixes -> out/episodes/NN.json (master) + text/vtt/srt copies
  flag.py, show_flags.py words that are probably wrong -> out/flags/NN.json; show_flags prints them readably
  report.py, summary.py  quality reports -> out/reports/
  clean_read.py          the "clean read" rules: which words to hide (um, uh, stutters) without changing any
  build_site_data.py     out/episodes -> site/data (episodes, transcripts, search, glossary); holds DEFS (glossary definitions)
  site_xref.py           "Elsewhere in the series" (where a guest is mentioned in other episodes)
  build_explainers.py    the clip library (CURATED list inside) -> site/data/explainers.js
  build_mentions.py      papers/tools/companies mentioned (VERIFIED list inside) -> site/data/mentions.js
  build_quotes.py        Explained's quote text, from the clean read -> site/data/quotes.js

data/                    HAND-KEPT INPUTS (edit these)
  episodes.json          written by fetch_feed.py (don't edit; numbers are fixed per episode by RSS guid)
  guests.json            "23": ["First Last"]  ([] = hosts only). REQUIRED for every episode.
  affiliations.json      "23": "University of X"  ("" = deliberately none)
  fixes/NN.json          corrections for episode NN (format below)
  terms/                 core.txt (field jargon), people.txt (researchers), companies.txt, NN.txt (this episode's names)
  nicknames.json         other forms of a speaker's first name (report.py)
  cold_open.json         the stock intro, identical in most episodes; build_episode.py swaps it in (where its
                         "detect" words are found)
  hidden.json            episodes kept off the site (and never downloaded or transcribed unless asked for by number)
  art_overrides.json     (optional) {"23": "https://...jpg"} to force an episode's art
  voiceprints/*.npy      the hosts' (and intro narrator's) voices, for name_speakers.py
  pubmed/                PubMed records used to write terms and to verify Show Notes papers

out/                     THE TRANSCRIPTS
  episodes/NN.json       the master transcript (every word: text, start, end, speaker, confidence, flags)
  text/NN.md  vtt/NN.vtt  srt/NN.srt   readable, caption and subtitle copies of the master
  raw/NN.json            ElevenLabs' untouched response (kept so nothing ever needs re-transcribing)
  speakers/NN.json       name_speakers' result; NN_emb2.npz are its voice caches (about 1 MB each, committed)
  flags/, clean/, reports/  working files (not committed; rebuilt by the scripts)

audio/                   episode MP3s (downloaded by fetch_feed.py; not committed)
models/                  the downloaded speaker model (not committed)
docs/DATA.md             every file format in detail
```

## How it works, end to end

1. **Feed.** `fetch_feed.py` reads the RSS feed (`https://anchor.fm/s/1077a238c/podcast/rss`). Each episode keeps
   its number forever, matched by its RSS guid, so a trailer or a removed episode never renumbers the rest.
   An episode that leaves the feed is kept as it was, with a note in the output. Episode number 18 is not used in this repository; that is deliberate. Episodes listed in
   `data/hidden.json` are kept off the site (and not downloaded or transcribed unless asked for by number).
2. **Key terms.** The transcriber is given about 200 names and terms so it spells them right: the field's jargon,
   researchers, companies, and the episode's own list (`data/terms/NN.txt`, written from the guest's papers).
   ElevenLabs takes at most 1000, each at most 5 words and 49 characters; `build_terms.py` checks.
3. **Transcribe.** ElevenLabs scribe_v2 returns every word with its time and a speaker label (speaker_0, speaker_1…).
4. **Name speakers.** `name_speakers.py` compares each speaker's voice with the saved voiceprints of Charles, Keith
   and the intro narrator; anyone else is the guest from `guests.json`. It also repairs turns the transcriber gave
   to the wrong person, judging each turn by its voice.
5. **Build.** `build_episode.py` applies `data/fixes/NN.json`, swaps in the stock cold open, tidies turn boundaries,
   and writes the master `out/episodes/NN.json` plus the Markdown, VTT and SRT copies.
6. **Site data.** `build_site_data.py` decides the "clean read" (via `clean_read.py`), packs each transcript into a
   compact file for the browser, builds the search index and glossary. `build_explainers.py`, `build_mentions.py`
   and `build_quotes.py` build the Explained clips, the Show Notes papers and the quotes.
7. **Site.** The pages load those files. Nothing runs on a server.

**The clean read** hides fillers (um, uh), stutters ("I, I, I"), false starts ("Cal... California"), verbal tics
(", you know,") and short interjections from the other speaker ("Mm-hmm"), with guards for emphasis ("no, no").
It only hides; it never adds or changes a word, and the Verbatim switch shows everything. The rules are in
`clean_read.py`'s docstring. Two rules exist twice and must change together: "≤3 shown words = folded
interjection" (`FOLD_MAX` in `scripts/common.py` and in `shared/core.js` renderReadable), and how paragraphs are
cut (`clean_read.py` `finish()` mirrors `core.js` `fill()`). Likewise the VTT/SRT files in `out/` follow the same
cue rules as the site's caption download (`build_episode.py` `cues()` and `cues()` in `web/index.html`).

## Adding an episode

When Keith says "add the new episode" (or a number):

1. `python scripts/fetch_feed.py` to see what's new (it also downloads the audio of every episode not
   transcribed yet; `--no-audio` skips that).
2. **Guest.** Find the guest's name in the episode title/notes (`data/episodes.json`). Add it to
   `data/guests.json` (`"23": ["First Last"]`, spelled as they spell it, accents included; `[]` for hosts only) and
   their affiliation to `data/affiliations.json`. Confirm the name with Keith if the title is ambiguous.
3. **Terms (worth it).** `python scripts/fetch_pubmed.py 23 "Last AB[Author]"` prints the guest's frequent
   coauthors and paper titles. Write `data/terms/23.txt`: the people, places, devices, methods and acronyms this
   episode will likely say, one per line, rare words only (common English is transcribed fine). Look at an existing
   `NN.txt` for the style. Then `python scripts/build_terms.py 23` shows the final list.
4. **Run it.** `python scripts/add_episode.py 23`. It checks the guest and the API key, prints the audio minutes
   and the estimated cost, and stops there (it asks "Transcribe? [y/N]", and you can't answer). Tell Keith the
   estimate; once he says yes, `python scripts/add_episode.py 23 --yes`. It fetches the art, transcribes, names
   speakers, builds, flags and rebuilds the site data, and stops with instructions if anything is missing.
   If it stops partway, fix the problem and run the same command again: a transcribed episode is never
   transcribed (or paid for) twice.
5. **Review** (next section), then preview and tell Keith what you changed and what still needs his ears.

## Reviewing a new episode

The goal: fix what the transcriber clearly got wrong, mark what only the audio can settle, change nothing else.

1. `python scripts/show_flags.py 23` lists flagged words with context, one per line:
   `n 268+4 @84.32 ~Focused Ultrasound Foundation | "Focused Ultrasound, uh, Foundation" | …context…`.
   `l` = low confidence (`lp-0.7` is its log-probability), `n` = sounds like a listed term (`~term`); `268+4` is
   the raw word index and span (4 words from index 268), `@84.32` the time in seconds (for `near_s`).
2. Read the transcript around each flag (`out/text/23.md`, or the master JSON). Then decide, in
   `data/fixes/23.json` (copy the shape of an existing file, e.g. `data/fixes/22.json`; every key is optional):
   - **`fix`** `{"i": 268, "k": 4, "from": "Focused Ultrasound, uh, Foundation", "to": "Focused Ultrasound Foundation", "why": "..."}`:
     replace a flagged span with a listed term. Only for flags, by raw index and span as show_flags prints them;
     `from` is the flagged text (punctuation and case don't matter) and the build checks it.
   - **`replace`** `{"near_s": 1798.4, "from": "UCI", "to": "UCL", "why": "..."}`: any misheard word or phrase,
     found by text near a time (seconds). `"all": true` (instead of `near_s`) fixes every occurrence. A `replace`
     that finds nothing stops the build with an error, so a correction is never silently lost.
   - **`uncertain`** `{"near_s": 2377.8, "text": "call it tree", "why": "..."}` (or `{"i": ..., "why": ...}`): mark
     words as unsure (dotted on the site, `[?]` in text) when the audio is needed.
   - **`speaker`** `{"near_s": 1713.0, "text": "Thanks, Treebs.", "who": "Charles Caskey", "why": "..."}` or
     `{"from_s": 100.0, "to_s": 104.5, "who": ..., "why": ...}`: give words to the right speaker. `who` must be a
     host, the guest, or "Intro narrator" (typos stop the build).
   - **`open_questions`** `["..."]`: notes for Keith, things only listening can settle.
   Always write a short `why`. Good evidence: the guest's own papers (`data/pubmed/`), the terms lists, the show notes,
   what the speaker says a sentence later. Not evidence: what would make the sentence read nicer.
3. Speakers: `python scripts/report.py 23` writes `out/reports/23.md` with voice-match warnings (turns whose
   voice fits another speaker better). Check those turns in context.
4. Rebuild, one command after the other (Windows PowerShell 5 has no `&&`):
   `python scripts/build_episode.py 23`, then `python scripts/add_episode.py --site`. The build checks every
   entry first (keys, required fields, types; `why` is optional) and stops, naming the file and the entry, if one
   is malformed or finds nothing; it also prints any misspelling left within two minutes of a fix.
5. Preview the episode and skim it in both readings (clean and Verbatim).

## Show Notes papers (episode pages)

The papers an episode discusses come from `scripts/build_mentions.py`:
1. `python scripts/build_mentions.py --candidates` prints every place someone refers to a study, scored.
2. For a real paper, find it (PubMed / DOI), check it is the one meant (authors, year, journal, what they describe),
   and add it to `VERIFIED` in the script with the episode and time. A paper with a PubMed id needs its record
   in `data/pubmed/mentioned.txt` (the build stops and says so): `python scripts/fetch_pubmed.py --pmid 41072763`.
3. `python scripts/build_mentions.py` (or `add_episode.py --site`). Every link must resolve and be the right paper.

## Explained clips

Explained shows hand-picked clips: someone clearly explaining one idea in 20–120 seconds (the build enforces it), useful to a beginner or
an expert. Keith decides what goes in; propose, show him the text, then add.
1. `python scripts/build_explainers.py --candidates 23` prints the episode's sentences with times (lines already in
   a clip are starred). Find a clean explanation; note its start and end seconds.
2. Add it to `CURATED` in `build_explainers.py`: `(episode, start_s, end_s, "Question-style title", [terms], "basics"|"intermediate"|"deep cut")`.
   Start on the first word, end on the last (the build snaps to word edges, ±0.3 s).
3. Run `python scripts/build_explainers.py`; it prints each clip's id (`"23-1234"`, episode-second of the first word).
4. Put the id in a chapter's `ids` in `site/web/essentials.js` (the order there is the page order).
5. `python scripts/build_quotes.py`, then check the quote reads well (a clip that starts mid-sentence is capitalised
   on the page automatically). Show Keith the text.

## Changing the design

- **Colours** are the "Lilac & Slate" scheme (#8f56a2 and #b59bc9 on blue-grey slate, mint as the second colour). The site opens in dark; the toggle in
  the header switches to light and is remembered. They are CSS variables at the top of `site/web/site.css`:
  `:root{…}` for light, `:root[data-theme="dark"]{…}` for dark. (The default theme is set in three places:
  `data-theme` on `<html>` and the one-line script in the head of `index.html` and `explained.html`, and
  `applyTheme(get("theme", "dark"))` in `site.js`.) The main ones: `--bg` page, `--paper` cards and bars, `--t1` text, `--t2`/`--mute` secondary text,
  `--rule` lines, `--soft` tinted panels, `--acc` links and highlights, `--mag` and `--org` the brand pink and orange
  (play buttons, the gradient `--grad`), `--now` the current word's highlight. `index.html` adds the player bar
  (`--bar…`) and speaker colours (`--c-…`) at the top of its `<style>`. Change both themes; check contrast (text on
  background at least 4.5:1).
- **Fonts**: Inter (interface) and Source Serif 4 (reading), from Google Fonts, set as `--disp` and `--text`.
- **Layout and pages**: `index.html` has its CSS in its `<style>` (episode page sections: hero, chapters + turntable,
  show notes, transcript tools, transcript, margin notes, "From this episode", "On this episode"). The episode page
  is laid out so the Transcript header shows on the first screen of a ~820 px tall window; keep it that way.
- **The logo** is the inline SVG in each page's header (`.wm`).
- For a new look (a violet scheme, say), define new `--bg/--paper/--t1/--acc/--mag/--org/--grad` values in both
  theme blocks rather than editing rules one by one.

## Publishing

The site is `site/web`, `site/shared`, `site/data`, `site/assets` and `site/favicon.ico`, kept side by side.
`site/index.html` sends visitors to `web/`.
- **GitHub Pages:** `.github/workflows/pages.yml` publishes `site/` on every push to `main`. In the repository's
  Settings → Pages, set the source to "GitHub Actions". The site is then at `https://<user>.github.io/<repo>/`.
- **Any static host** (Netlify, Cloudflare Pages, S3): publish the `site/` folder.
- **Inside another website** (e.g. the Attune site): copy `site/` into a subfolder such as `/fusforward/`; every
  path inside is relative, so it works anywhere. Link to `/fusforward/web/`, or to an episode at a moment:
  `/fusforward/web/index.html#/record/16?t=600`. To show it inside an existing page, an `<iframe>` of that URL works.
  To build your own pages instead, read the transcripts directly (docs/DATA.md).

## Testing

After a site change, run `python site/serve.py` and check, in light and dark, at desktop (1440 px) and phone (375 px):
- home; an episode (`#/record/16`) plays, words light up and can be clicked, Verbatim switches instantly,
  Show Notes and chapters work; search (`#/search?q=skull`) finds results; `explained.html` plays a clip, stops at its end, and Next / ← → move between clips;
- the browser console shows no errors; nothing scrolls sideways on a phone.
After a pipeline change, rebuild an episode and compare `out/episodes/NN.json` before and after: only what you
meant to change should differ.

## Good to know

- Windows: the scripts switch their output to UTF-8 themselves (common.py); paths use pathlib and work on Mac too.
- `name_speakers.py` caches voice embeddings in `out/speakers/NN_emb2.npz`; with the cache it runs without audio.
  The caches are committed, so re-running it for an existing episode needs neither the audio nor the model; only
  a new episode does. (If a cache is missing, `python scripts/fetch_feed.py 16` gets that episode's audio back.)
  The model (about 85 MB) downloads into `models/` on first use, pinned to
  a fixed SpeechBrain revision.
- Clip ids come from the first word's time; re-transcribing an episode can shift them by a second. Rebuilding
  `build_quotes.py` stops with "essentials.js lists unknown clip X" if one moved; update `essentials.js`.
- The art script never replaces existing art with something worse; if it can't find an episode's art it says so.
  Set it by hand in `data/art_overrides.json`.
- A guest who appears in another episode is found by name for "Elsewhere in the series"; long surnames match only
  capitalised, so a surname like "Young" doesn't match the word "young".
- Saved settings in the browser use the `ffweb.` prefix: theme, rate, sort, clean, pos (where you stopped), notes.
