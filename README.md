# FUS Forward Records

Transcripts of every episode of **FUS Forward**, the focused-ultrasound neuromodulation podcast with Charles
Caskey and Keith Murphy, and the website that plays them: read along with the audio, click any word to jump
there, search every episode to the exact second, and learn the field from short clips of the guests explaining it.

The transcripts are machine-made (ElevenLabs speech-to-text), then corrected: names and terms fixed from a
read-through, speakers checked against voiceprints of the hosts. They are unofficial and can still mishear.

- **The website** is plain static files in `site/`: no server, no build step, no tracking. Open it locally or
  put it on any web host.
- **The transcripts** are in `out/` as JSON (every word with its time and speaker), clean readable text
  (`out/clean-text/`, without the ums and false starts), verbatim Markdown, and VTT/SRT captions.
  Use them for anything: show notes, clips, captions, search, another website. See [docs/DATA.md](docs/DATA.md).
- **The pipeline** in `scripts/` turns a new episode into a transcript and updates the site with one command.

Working with Claude Code? It reads [CLAUDE.md](CLAUDE.md), which explains everything below in more depth, so
you can just ask: "add the new episode", "review episode 23", "make the site violet", "put this on our website".

## Look at the site

```bash
python site/serve.py
```

Then open <http://localhost:8770/web/>. (Python 3 only; nothing to install for this.)

## Set up the pipeline (once)

You need Python 3.11+ and [ffmpeg](https://ffmpeg.org/download.html) on your PATH. From the project folder,
make a virtual environment and install into it (on Mac, type `python3` where it says `python`):

```bash
python -m venv .venv
```

Then activate it: `.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on Mac. Then:

```bash
pip install -r requirements.txt
```

Last, copy `.env.example` to `.env` (`copy .env.example .env` on Windows, `cp .env.example .env` on Mac) and
put your ElevenLabs API key in it. Activate the environment again in each new terminal before running a script.

The ElevenLabs key is the only paid part: speech-to-text at about $0.27 per hour of audio (late 2026), so under
a dollar an episode. The scripts show the estimate and ask before spending anything. `.env` is ignored by git:
never commit it. The first run of `name_speakers.py` downloads a small speaker-recognition model (SpeechBrain
ECAPA, about 85 MB) into `models/`.

## Add a new episode

```bash
python scripts/add_episode.py
```

It finds episodes in the RSS feed that don't have a transcript yet, downloads the audio and artwork, shows the
transcription cost and asks before going on, then transcribes, names the speakers, builds the transcript and
updates the site data. It stops and tells you what to do if something needs a person. The one thing it always
needs: add the guest's name to `data/guests.json` (and their affiliation to `data/affiliations.json`). Then run
it again; nothing already done (or paid for) is repeated.

The transcript is usable straight away. To make it better, review the words the transcriber was unsure of;
[CLAUDE.md](CLAUDE.md) has the procedure ("Reviewing a new episode"), and Claude Code can do it for you.

## Publish

The site is these folders, kept side by side: `site/web/`, `site/shared/`, `site/data/`, `site/assets/` and
`site/favicon.ico`. People open `/web/`.

- **GitHub Pages:** the included workflow (`.github/workflows/pages.yml`) publishes `site/` on every push to
  `main`. Turn it on once: Settings → Pages → Source: "GitHub Actions".
- **Netlify / Cloudflare Pages / any static host:** publish the `site/` folder.
- **Inside another website:** copy `site/` into a subfolder (e.g. `/fusforward/`) and link to `/fusforward/web/`.

## What's where

```
site/            the website (web/ pages, shared/ code, data/ built data, assets/ artwork)
scripts/         the pipeline, one script per step; add_episode.py runs them in order
data/            hand-kept inputs: guests, affiliations, transcript corrections, key terms, voiceprints
out/             the transcripts: clean-text/ (clean, readable), text/ (verbatim), vtt/ and srt/ (captions),
                 episodes/ (master JSON), raw/ and speakers/ (inputs to rebuild)
docs/DATA.md     every file format, for using the transcripts elsewhere
CLAUDE.md        the full guide, for Claude Code and for people
```

## License

The code is MIT licensed (see `LICENSE`). The audio, artwork, show notes and transcripts are FUS Forward's.
