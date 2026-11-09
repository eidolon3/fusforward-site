"""What every pipeline script shares: paths, the API key, downloads, data files, and a few rules and formats.

  ROOT    the project folder (the parent of scripts/)
  AUDIO   ROOT/audio: the episode MP3s that fetch_feed.py downloads. Never committed (see .gitignore).
Importing this module also switches console output to UTF-8 (a Windows pipe can't print "→" or "François").
"""
import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"

HOSTS = ("Charles Caskey", "Keith Murphy")
NARRATOR = "Intro narrator"     # the voice of the stock cold open; a speaker like any other in the transcripts
# A turn of this many shown words or fewer is a folded interjection ("Mm-hmm", "Yeah, totally").
# The website applies the same rule: FF.renderReadable in site/shared/core.js. Change both together.
FOLD_MAX = 3
# A turn whose voice similarity is below this is flagged for review (name_speakers.py; listed by report.py).
LOW_SIM = 0.25
FIX_KEYS = ("fix", "uncertain", "replace", "speaker", "open_questions")
# Each data/fixes entry's keys: those it must have (one of the alternatives), those it may have, and how to say it.
FIX_SHAPES = {
    "fix": ([("i", "k", "from", "to")], {"why"}, 'A fix needs "i", "k", "from" and "to".'),
    "uncertain": ([("i",), ("near_s", "text")], {"why"}, 'An uncertain entry needs "i", or "near_s" and "text".'),
    "replace": ([("near_s", "from", "to"), ("all", "from", "to")], {"why"},
                'A replace needs "near_s", "from" and "to" ("all": true instead of "near_s" corrects every match).'),
    "speaker": ([("from_s", "to_s", "who"), ("near_s", "text", "who")], {"why"},
                'A speaker entry needs "who", and "from_s" and "to_s" or "near_s" and "text".'),
}
SENTENCE_END = re.compile(r"[.?!][\"”’)]*$")

# Some hosts (the Spotify for Creators pages) refuse requests that don't look like a browser.
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def utf8_output():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


utf8_output()


def rel(path):
    """A path as people type it: relative to ROOT where possible, with forward slashes."""
    path = Path(path)
    return (path.relative_to(ROOT) if path.is_relative_to(ROOT) else path).as_posix()


def http_get(url, timeout=30, retries=2):
    """The body of url as bytes. Retries briefly on network errors and 5xx; raises on anything else."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(2 * (attempt + 1))


def download(url, dest, timeout=120):
    """Stream url into dest, through a .part file, so a broken download never leaves a half file behind."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as fh:
        while chunk := r.read(1 << 20):
            fh.write(chunk)
    part.replace(dest)


def secret(name):
    """A key from the environment, or from ROOT/.env (lines of NAME=value). Exits with a clear message if missing or empty."""
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == name:
                    v = v.strip().strip('"').strip("'")
                    if v:
                        return v
                    sys.exit(f"{name} in .env is empty: put your key after the = sign.")
    sys.exit(f"{name} is not set. Copy .env.example to .env and put your key there (or set it in the environment).")


def load_json(path, missing_ok=False):
    """JSON from path. A missing file exits naming it (or gives None with missing_ok); invalid JSON exits with the
    line and column, since a stray or missing comma in a hand-edited file is the usual cause."""
    path = Path(path)
    if not path.exists():
        if missing_ok:
            return None
        sys.exit(f"{rel(path)} is missing")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))   # -sig: Windows editors sometimes add a BOM
    except json.JSONDecodeError as e:
        sys.exit(f"{rel(path)} is not valid JSON (line {e.lineno}, column {e.colno}: {e.msg}). "
                 "A missing or extra comma is the usual cause.")


def episodes():
    """data/episodes.json: one entry per episode, in number order (fetch_feed.py writes it)."""
    return load_json(ROOT / "data" / "episodes.json")


def episode(n):
    """The data/episodes.json entry whose "n" is n. Exits if there is none."""
    for e in episodes():
        if e["n"] == n:
            return e
    sys.exit(f"episode {n} is not in data/episodes.json: run python scripts/fetch_feed.py")


def hidden():
    """The episode numbers in data/hidden.json: kept out of the site, and not downloaded or transcribed unless asked for
    by number. ({"23": "why"}; a missing file hides nothing.)"""
    return {int(k) for k in (load_json(ROOT / "data" / "hidden.json", missing_ok=True) or {}) if k.isdigit()}


def fixes_path(n):
    return ROOT / "data" / "fixes" / f"{n:02d}.json"


def load_fixes(n):
    """data/fixes/<NN>.json with every list key present (empty when absent); no file means no fixes.
    An unknown key (a typo such as "replaces") or an entry missing a key exits, naming the file and the entry,
    so a correction is never silently ignored."""
    p = fixes_path(n)
    fixes = load_json(p, missing_ok=True) or {}
    unknown = [k for k in fixes if k not in FIX_KEYS and k != "_note"]
    if unknown:
        sys.exit(f"{rel(p)}: unknown key {', '.join(map(repr, unknown))}. The keys are: {', '.join(FIX_KEYS)} (and _note).")
    fixes = {**{k: [] for k in FIX_KEYS}, **fixes}
    for kind in FIX_KEYS:
        if not isinstance(fixes[kind], list):
            sys.exit(f"{rel(p)}: \"{kind}\" must be a list [...]")
    for q in fixes["open_questions"]:
        if not isinstance(q, str):
            sys.exit(f"{rel(p)}: open_questions holds text only, not {q!r}")
    for kind, (needs, extra, hint) in FIX_SHAPES.items():
        for k, e in enumerate(fixes[kind], 1):
            where = f"{rel(p)}: {kind} entry {k} {json.dumps(e, ensure_ascii=False)[:160]}"
            if not isinstance(e, dict):
                sys.exit(f"{where} is not an object {{...}}")
            have = {key for key, v in e.items() if v is not None and (key != "all" or v is True)}   # "near_s": null = absent
            shape = next((s for s in needs if set(s) <= have), None)
            if shape is None:
                missing = min((sorted(set(s) - have) for s in needs), key=len)
                sys.exit(f"{where}: missing {', '.join(map(json.dumps, missing))}. {hint}")
            stray = set(e) - {key for s in needs for key in s} - extra
            if stray:
                sys.exit(f"{where}: unknown key {', '.join(map(repr, sorted(stray)))}")
            for key in ("i", "k"):
                if key in have and type(e[key]) is not int:
                    sys.exit(f"{where}: {key} must be a whole number")
            for key in ("near_s", "from_s", "to_s"):
                if key in have and type(e[key]) not in (int, float):
                    sys.exit(f"{where}: {key} must be a number of seconds")
            for key in ("from", "to", "text", "who"):
                if key in have and not (isinstance(e[key], str) and e[key].strip()):
                    sys.exit(f"{where}: {key} must be non-empty text")
    return fixes


def guests():
    """data/guests.json: {"23": ["First Last"], ...}; [] is the hosts alone."""
    return load_json(ROOT / "data" / "guests.json")


def parser(doc):
    """An argparse parser taking an episode number, with the script's docstring as its --help."""
    p = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("n", type=int, help="episode number")
    return p


def hms(s, sep="."):
    """Seconds as hh:mm:ss.mmm (VTT) or hh:mm:ss,mmm (SRT), rounded to the millisecond (halves up, as JavaScript's
    Math.round in the website's caption download)."""
    ms = math.floor(max(s, 0) * 1000 + 0.5)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def mmss(s):
    """Seconds as m:ss, or h:mm:ss from an hour on (as the website shows times)."""
    s = int(max(s, 0))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def norm_key(s):
    """Lower case, accents dropped, letters and digits only: "Jean-François" -> "jeanfrancois".
    The same as build_site_data.match_key."""
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)))
