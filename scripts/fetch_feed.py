"""Pull episode metadata from the FUS Forward RSS feed into data/episodes.json, and download the audio still needed.

Run:  python scripts/fetch_feed.py              (metadata, plus audio for episodes not transcribed yet)
      python scripts/fetch_feed.py 23 24        (metadata, plus audio for just these episodes)
      python scripts/fetch_feed.py --all-audio  (metadata, plus audio for every episode)
      python scripts/fetch_feed.py --no-audio   (metadata only)
Episodes are numbered oldest-first. A number, once given, belongs to that episode for good: episodes are
matched to the saved list by their RSS guid (or their link), so a re-upload or a deleted episode never
renumbers the rest. Trailers and bonus items are skipped.
Audio goes to audio/ (not committed); an episode needs it to be transcribed (no out/raw/<NN>.json yet). An episode in
data/hidden.json is downloaded only when asked for by number.
"""
import argparse
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import common
from common import AUDIO, ROOT, download, http_get, rel

FEED = "https://anchor.fm/s/1077a238c/podcast/rss"
NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
SAVED = ROOT / "data" / "episodes.json"
SKIP_TYPES = {"trailer", "bonus"}   # itunes:episodeType; "full" (or none) is an episode


def plain(s):
    """The description as plain text: paragraphs kept, tags dropped, entities decoded."""
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(s)).strip()


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]


def published(it):
    """An item's pubDate as a sortable time; an item without a readable one sorts as the newest."""
    try:
        return parsedate_to_datetime(it.findtext("pubDate")).timestamp()
    except (TypeError, ValueError):
        return float("inf")


def read_feed():
    try:
        return ET.fromstring(http_get(FEED))
    except OSError as e:   # offline, DNS, timeouts, HTTP errors (urllib.error.URLError is an OSError)
        if getattr(e, "code", None):
            sys.exit(f"The RSS feed answered HTTP {e.code} ({e.reason}): {FEED}. Try again later; if it persists, "
                     "the feed has moved: update FEED in scripts/fetch_feed.py.")
        sys.exit(f"Could not read the RSS feed ({getattr(e, 'reason', e)}). Check your internet connection.")
    except ET.ParseError as e:
        sys.exit(f"The RSS feed at {FEED} is not valid XML ({e}). Try again later.")


def has_raw(n):
    return (ROOT / "out" / "raw" / f"{n:02d}.json").exists()


def transcribed_url(n, saved):
    """The audio URL episode n's transcript was made from (its master file keeps it); None if not transcribed."""
    if not has_raw(n):
        return None
    master = common.load_json(ROOT / "out" / "episodes" / f"{n:02d}.json", missing_ok=True)
    return (master or saved).get("audio_url")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", type=int, nargs="*", help="download audio for just these episodes")
    audio = ap.add_mutually_exclusive_group()
    audio.add_argument("--no-audio", action="store_true", help="update the metadata only; download no audio")
    audio.add_argument("--all-audio", action="store_true", help="download every episode's audio")
    a = ap.parse_args()
    if a.n and (a.no_audio or a.all_audio):
        ap.error("give episode numbers, --no-audio or --all-audio, not several")

    root = read_feed()
    show_image = root.find("./channel/itunes:image", NS)   # (an Element with no children is falsy: compare to None)
    cover = show_image.get("href") if show_image is not None else None
    items = []
    for it in root.findall("./channel/item"):
        kind = (it.findtext("itunes:episodeType", namespaces=NS) or "full").strip().lower()
        if kind in SKIP_TYPES:
            print(f"skipped {kind}: {it.findtext('title')}")
        else:
            items.append(it)
    items.sort(key=published)   # oldest first

    saved = common.load_json(SAVED, missing_ok=True) or []
    by_key = {}
    for e in saved:
        for k in (e.get("guid"), e.get("link")):
            if k:
                by_key[k] = e
    next_n = max((e["n"] for e in saved), default=0) + 1
    seen, eps = set(), []
    for it in items:
        guid, link = it.findtext("guid"), it.findtext("link")
        old = by_key.get(guid) or by_key.get(link) or {}
        if old:
            n = old["n"]
        else:
            n, next_n = next_n, next_n + 1
        seen.add(n)
        enc = it.find("enclosure")
        image = it.find("itunes:image", NS)
        e = {
            "n": n,
            "guid": guid,
            "title": it.findtext("title"),
            "date": it.findtext("pubDate") or old.get("date"),
            "duration": it.findtext("itunes:duration", namespaces=NS),
            "audio_url": enc.get("url") if enc is not None else None,
            "audio_file": old.get("audio_file") or f"{n:02d}_{slug(it.findtext('title') or str(n))}.mp3",
            "link": link,
            "notes": plain(it.findtext("description")),
            # The episode's own artwork in the feed; None where it just repeats the show cover (fetch_art.py
            # has better sources and uses this only as a fallback).
            "image": image.get("href") if image is not None and image.get("href") != cover else None,
        }
        if not e["date"]:
            print(f"ep {n}: the feed gives no pubDate ({e['title']})")
        was = transcribed_url(n, old) if old else None
        if was and e["audio_url"] != was:
            print(f"WARNING ep {n}: its audio URL is not the one it was transcribed from. If the episode was "
                  f"re-uploaded with edits, out/raw/{n:02d}.json may no longer line up with the audio: listen to a "
                  f"few timestamps on the site. (This stops once python scripts/build_episode.py {n} records the "
                  "new URL.)")
        eps.append(e)
    gone = [e for e in saved if e["n"] not in seen]
    for e in gone:
        print(f"ep {e['n']}: no longer in the feed; kept as it was ({e['title']})")
    eps = sorted(eps + gone, key=lambda e: e["n"])
    SAVED.write_text(json.dumps(eps, indent=1, ensure_ascii=False), encoding="utf-8")

    unknown = sorted(set(a.n) - {e["n"] for e in eps})
    if unknown:
        sys.exit(f"not in the feed or {rel(SAVED)}: {', '.join(map(str, unknown))}")
    if a.no_audio:
        wanted = []
    elif a.all_audio:
        wanted = eps
    elif a.n:
        wanted = [e for e in eps if e["n"] in a.n]
    else:
        wanted = [e for e in eps if not has_raw(e["n"]) and e["n"] not in common.hidden()]   # hidden: only by number
    missing = []
    for e in wanted:
        dest = AUDIO / e["audio_file"]
        if dest.exists():
            continue
        if not e["audio_url"]:
            print(f"ep {e['n']}: the feed has no audio link")
            missing.append(e["n"])
            continue
        print(f"ep {e['n']}: downloading audio to {rel(dest)} ...", flush=True)
        try:
            download(e["audio_url"], dest)
        except Exception as err:   # one failed download should not stop the rest
            print(f"ep {e['n']}: audio download failed ({err})")
            missing.append(e["n"])
    new = [e["n"] for e in eps if e["n"] not in {s["n"] for s in saved}]
    print(f"{len(eps)} episodes{f'; new: {new}' if new else ''}{f'; missing audio: {missing}' if missing else ''}")


if __name__ == "__main__":
    main()
