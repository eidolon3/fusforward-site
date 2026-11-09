"""Download each episode's artwork, as Spotify shows it, for the site.

Run:  python scripts/fetch_art.py              (episodes that have no artwork yet)
      python scripts/fetch_art.py 23 24        (just these, replacing what is there)
      python scripts/fetch_art.py --all        (every episode, replacing what is there)
Then: python scripts/make_thumbs.py
Output: site/assets/ep/<NN>.jpg, 640 x 360.

Why this is careful: the RSS feed often repeats the show cover instead of the episode's own art, and the
Spotify pages that do have it change their layout from time to time. So each episode tries several sources,
in order, and every image is checked before it is saved:
  1. data/art_overrides.json   {"23": "https://...jpg"} or {"23": "art/ep23.png"} (a file in the project):
     set any episode's image by hand; wins over the rest
  2. Spotify's public oEmbed endpoint for the episode. Spotify ids are read from the show's pages on Spotify
     for Creators (the RSS <link>), and the oEmbed title must match the episode's title, so a wrong id can
     never put another episode's art on this one.
  3. The episode page's own preview image (og:image).
  4. The feed's per-episode image (data/episodes.json "image"), when it is not the show cover.
An image is rejected if it is too small or is just the show cover. Square art is set on a blurred,
widened copy of itself, so every file is 16:9. If no source works, the existing file is left alone and the
episode is listed at the end; the site then shows the show cover for it.
"""
import argparse
import io
import json
import re
import urllib.parse

from PIL import Image, ImageFilter, ImageStat

import common
from common import ROOT, http_get, rel

OUT = ROOT / "site" / "assets" / "ep"
OVERRIDES = ROOT / "data" / "art_overrides.json"
COVER = ROOT / "site" / "assets" / "cover.jpg"   # the show cover, used where an episode has no art
SIZE = (640, 360)


def words(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower())) - {"ep", "episode", "the", "a", "of", "and"}


def same_title(a, b):
    """Two titles name the same episode: most of the shorter one's words are in the longer one."""
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def fingerprint(im):
    """A tiny grey thumbnail, for telling whether two images are the same picture."""
    return list(im.convert("L").resize((16, 9)).tobytes())


def looks_like(a, b, limit=12):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) < limit


def to_16x9(im):
    """640 x 360. 16:9 art is resized; anything else is centred on a blurred, filled copy of itself."""
    im = im.convert("RGB")
    w, h = im.size
    if abs(w / h - 16 / 9) < 0.03:
        return im.resize(SIZE, Image.LANCZOS)
    bg = im.resize((SIZE[0], round(SIZE[0] * h / w)), Image.LANCZOS)
    top = max(0, (bg.height - SIZE[1]) // 2)
    bg = bg.crop((0, top, SIZE[0], top + SIZE[1])).filter(ImageFilter.GaussianBlur(24))
    bg = Image.eval(bg, lambda v: int(v * 0.8))   # a little darker, so the art stands out
    fg = im.copy()
    fg.thumbnail(SIZE, Image.LANCZOS)
    bg.paste(fg, ((SIZE[0] - fg.width) // 2, (SIZE[1] - fg.height) // 2))
    return bg


SPOTIFY_ID = re.compile(r"open\.spotify\.com(?:\\u002F|\\/|/)episode(?:\\u002F|\\/|/)([A-Za-z0-9]{22})")


def page(url):
    try:
        return http_get(url).decode("utf-8", "ignore")
    except Exception as err:
        print(f"  page unavailable: {url} ({err})")
        return ""


class Spotify:
    """Spotify episode ids, gathered from the show's Creators pages and confirmed by title through oEmbed.

    An episode's own page doesn't always link its Spotify id (older ones often don't), so ids are also read
    from the show page and the newest episode's page, which list many episodes (on first use, so their messages
    come under the first episode's heading). Every id is looked up once; an episode only ever gets the art whose
    oEmbed title matches its own.
    """
    def __init__(self, eps):
        self.ids, self.meta, self.pages = [], {}, set()
        self.newest = max(eps, key=lambda e: e["n"]).get("link")

    def read(self, url):
        if url and url not in self.pages:
            self.pages.add(url)
            self.ids += [i for i in dict.fromkeys(SPOTIFY_ID.findall(page(url))) if i not in self.ids]

    def lookup(self, sid):
        if sid not in self.meta:
            try:
                o = json.loads(http_get("https://open.spotify.com/oembed?url=" + urllib.parse.quote(f"https://open.spotify.com/episode/{sid}", safe="")))
                self.meta[sid] = (o.get("title"), o.get("thumbnail_url"))
            except Exception as err:   # 403/404: an episode Spotify no longer shows (unpublished), not a fault here
                if getattr(err, "code", None) not in (403, 404):
                    print(f"  Spotify oEmbed lookup failed for episode id {sid} ({err})")
                self.meta[sid] = (None, None)
        return self.meta[sid]

    def art_for(self, ep, html):
        if self.newest:
            self.read(self.newest.split("/episodes/")[0])   # the show page
            self.read(self.newest)
        self.ids += [i for i in dict.fromkeys(SPOTIFY_ID.findall(html)) if i not in self.ids]
        for sid in self.ids:
            title, thumb = self.lookup(sid)
            if thumb and same_title(title, ep["title"]):
                return thumb
        return None


def candidates(ep, overrides, spotify):
    """(source name, image URL) pairs to try for this episode, best first. Network errors skip a source."""
    if str(ep["n"]) in overrides:
        yield "override", overrides[str(ep["n"])]
    html = page(ep["link"]) if ep.get("link") else ""
    thumb = spotify.art_for(ep, html)
    if thumb:
        yield "spotify", thumb
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html) or re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', html)
    if m:
        yield "page image", m.group(1).replace("&amp;", "&")
    if ep.get("image"):
        yield "feed image", ep["image"]


def fetch(ep, overrides, cover_fp, spotify):
    for source, url in candidates(ep, overrides, spotify):
        try:
            data = http_get(url) if url.startswith(("http://", "https://")) else (ROOT / url).read_bytes()
            im = Image.open(io.BytesIO(data))
            im.load()
        except Exception as err:
            print(f"  {source}: unusable ({err})")
            continue
        if min(im.size) < 300:
            print(f"  {source}: too small ({im.size[0]}x{im.size[1]})")
            continue
        art = to_16x9(im)
        if cover_fp and looks_like(fingerprint(art), cover_fp):
            print(f"  {source}: just the show cover")
            continue
        if ImageStat.Stat(art.convert("L")).stddev[0] < 8:
            print(f"  {source}: blank image")
            continue
        return source, art
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", type=int, nargs="*", help="episode numbers (replaces their art)")
    ap.add_argument("--all", action="store_true", help="every episode (replaces all art)")
    a = ap.parse_args()
    eps = common.episodes()
    overrides = common.load_json(OVERRIDES, missing_ok=True) or {}
    OUT.mkdir(parents=True, exist_ok=True)
    if a.all:
        todo = eps
    elif a.n:
        todo = [e for e in eps if e["n"] in set(a.n)]
        for n in sorted(set(a.n) - {e["n"] for e in eps}):
            print(f"WARNING: episode {n} is not in data/episodes.json; skipped")
    else:
        todo = [e for e in eps if not (OUT / f"{e['n']:02d}.jpg").exists()]
    cover_fp = fingerprint(to_16x9(Image.open(COVER))) if COVER.exists() else None
    spotify = Spotify(eps)
    failed = []
    for ep in todo:
        print(f"ep {ep['n']}: {ep['title']}")
        source, art = fetch(ep, overrides, cover_fp, spotify)
        if art is None:
            failed.append(ep["n"])
            print("  no usable artwork found; left as it was")
            continue
        dest = OUT / f"{ep['n']:02d}.jpg"
        art.save(dest, "JPEG", quality=88, optimize=True, progressive=True)
        print(f"  saved from {source} to {rel(dest)}")
    print(f"{len(todo) - len(failed)} of {len(todo)} saved." + (f" No art for {failed}: add them to {rel(OVERRIDES)}." if failed else ""))
    if len(todo) - len(failed):
        print("Next: python scripts/make_thumbs.py")


if __name__ == "__main__":
    main()
