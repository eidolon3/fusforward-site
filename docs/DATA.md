# The data: every file, for using the transcripts anywhere

All text is UTF-8. Times are seconds from the start of the episode's audio. Episode numbers (`NN`, two digits
in file names) are the show's own: episode 16 is `16.json`.

## The transcripts (`out/`)

### `out/episodes/NN.json`: the master transcript

Everything else is made from this file. Use it when you need words, times and speakers.

```json
{
  "n": 16,
  "title": "Ep. 16 Jean-Francois Aubry one with waves",
  "date": "Tue, 07 Apr 2026 00:09:32 GMT",
  "audio_url": "https://anchor.fm/...mp3",
  "duration_s": 4556.3,
  "speakers": ["Jean-François Aubry", "Keith Murphy", "Intro narrator", "Charles Caskey"],
  "source": {"model": "scribe_v2", "raw": "16", "transcription_id": "..."},
  "edits": {"fixes": 4, "replaced": 26, "uncertain": 6, "...": "counts of what was corrected"},
  "words": [{"w": "PhD", "s": 34.88, "e": 35.0, "lp": -0.007, "p": 0}, "..."],
  "turns": [{"p": 1, "s": 10.44, "e": 11.14, "w0": 28, "w1": 31}, "..."]
}
```

- `words[i]`: `w` the word as transcribed (with its punctuation), `s`/`e` start and end, `p` the speaker
  (an index into `speakers`), `lp` the model's log-probability (closer to 0 = more confident), `u: 1` if the word
  is marked uncertain, `x: 1` for a sound event such as `[laughs]`.
- `turns[k]`: one stretch of one speaker, from word `w0` up to (not including) `w1`.
- This is the **verbatim** transcript: every "um" and restart is here. The clean read (what the site shows by
  default) is decided on top of it; see `site/data/ep/NN.js` below or `scripts/clean_read.py`.

Read it in Python:

```python
import json
m = json.load(open("out/episodes/16.json", encoding="utf-8"))
for t in m["turns"]:
    words = " ".join(w["w"] for w in m["words"][t["w0"]:t["w1"]])
    print(f'{t["s"]:7.1f}  {m["speakers"][t["p"]]}: {words}')
```

### `out/clean-text/NN.md`

The clean read as Markdown, the easiest version to read or reuse: fillers, stutters, false starts and short
interjections ("Mm-hmm") hidden, no word changed or added, one block per speaker in paragraphs, as the episode page
shows it (and as its "Plain text" download gives it). Uncertain words end in `[?]`. Written by
`scripts/build_site_data.py` with the site data.

### `out/text/NN.md`, `out/vtt/NN.vtt`, `out/srt/NN.srt`

The verbatim transcript as Markdown (one paragraph per turn, `**[hh:mm:ss] Speaker:**`; uncertain words end in `[?]`),
WebVTT captions (speaker in a `<v Name>` tag) and SRT subtitles (speaker name before a turn's first cue). The cues
follow the same rules as the site's caption download. Drop the VTT or SRT into a video editor or YouTube.

### `out/raw/NN.json` and `out/speakers/NN.json`

The untouched ElevenLabs response, and the speaker naming result. Kept so any transcript can be rebuilt (after a
correction or a code change) without transcribing again: `python scripts/build_episode.py NN`.

## The inputs you edit (`data/`)

| File | What it is |
|---|---|
| `episodes.json` | The feed, one entry per episode: `n`, `guid`, `title`, `date`, `duration`, `audio_url`, `audio_file`, `link`, `notes` (the episode description, plain text), `image`. Written by `fetch_feed.py`. |
| `guests.json` | `{"16": ["Jean-François Aubry"]}`; `[]` = hosts only. Every episode needs an entry. |
| `affiliations.json` | `{"16": "CNRS · Physics for Medicine Paris"}`; `""` = deliberately none. |
| `fixes/NN.json` | Corrections for one episode: `fix`, `replace`, `uncertain`, `speaker`, `open_questions` (see CLAUDE.md, "Reviewing a new episode", and the docstring of `scripts/build_episode.py`). |
| `terms/*.txt` | Words the transcriber is told to expect: `core.txt` (field jargon), `people.txt`, `companies.txt`, `NN.txt` (one episode). One per line; `#` starts a comment. |
| `nicknames.json` | Other forms of a speaker's first name, for `report.py`. |
| `cold_open.json` | The stock intro: `words` and speakers, put in place of whatever the transcriber made of it (everything before `end_s` seconds), in episodes whose first 8 seconds contain the `detect` phrase and whose narration before `end_s` contains the `detect_narration` word. |
| `hidden.json` | `{"23": "why"}`: episodes left out of the website (their numbers stay taken). Not downloaded or transcribed unless asked for by number. |
| `art_overrides.json` | Optional: `{"23": "https://...jpg"}` or a file path, to force an episode's art. |
| `voiceprints/*.npy` | The voices of Charles Caskey, Keith Murphy and the intro narrator (192-number speaker embeddings). |
| `pubmed/` | PubMed records: `NN.txt` per guest (for writing terms), `mentioned.txt` (papers in Show Notes). |

## What the website loads (`site/data/`)

These are JavaScript files (so the site also works opened from disk) that each set one global. Built by the
scripts; never edit them.

| File | Global | Contents |
|---|---|---|
| `episodes.js` | `FF_EPISODES` | One entry per episode: `n`, `title` (without "Ep. N"), `display_title`, `full_title`, `date`, `duration_s`, `guests`, `affiliation`, `hosts`, `audio_url`, `link`, `art`, `notes`, `words` (count), `talk_min` (minutes per speaker). |
| `ep/NN.js` | `FF._ep(n, {...})` | One transcript: `n`, `title`, `duration_s`, `audio_url`, `speakers` (names; a word's speaker is an index into this), then the words packed as columns: `ww` words; `ws` start minus the previous word's start and `wd` duration, both in hundredths of a second; `wp` speaker per word (one base-36 digit); `wf` flags per word (one digit: 1 uncertain, 2 sound event, 4 hidden in the clean read); `c` {word index: how the clean read shows it}; `turns` [[speaker, start, end, w0, w1]]; `x` "Elsewhere in the series". `shared/core.js` (`FF.episode(n)`) and `scripts/build_quotes.py` (`load_ep`) both decode it. |
| `search.js` | `FF_SEARCH` | `[[episode, start, speaker, text], ...]`: every transcript in chunks of up to 35 words. |
| `glossary.js` | `FF_GLOSSARY` | Terms and people that come up: `term`, `kind` ("term"/"person"), `def`, `count`, `episodes`, `hits` [[episode, start, speaker]] (every one). |
| `explainers.js` | `FF_EXPLAIN` | `explainers`: the clip library (`id`, `n`, `s`, `e`, `title`, `who`, `level`, `terms`, `caveat`); `defs`: glossary definitions for the margin notes. |
| `mentions.js` | `FF_MENTIONS` | `papers` (`id` (the PubMed id, or the DOI where there is none), `title`, `authors`, `n_authors`, `year`, `journal`, `preprint`, `doi`, `url`, `pubmed`, `moments` [{`ep`, `t`, `who`, `quote`}]), `tools` and `companies` (`name`, `desc`, `url`, `moments` [{`ep`, `t`}]). |
| `quotes.js` | `FF_QUOTES` | `{clip id: [[speaker, text, times], ...]}`: each Explained clip's words in the clean read; `times` is when each word of `text` (split on spaces) starts, in hundredths of a second from the clip's start. |

Read one in Python:

```python
import json, re
text = open("site/data/search.js", encoding="utf-8").read()
rows = json.loads(re.search(r"=\s*(.*);\s*$", text, re.S).group(1))
```

## Linking to a moment

`site/web/index.html#/record/16?t=600` opens episode 16 at 10:00. `#/search?q=skull` searches every episode.
