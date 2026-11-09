"""Explained's quotes, as the episode pages read them.

Every clip on explained.html shows what is said in its span in the transcript's clean read, the same text an episode
page shows by default: fillers, stutters, false starts and sound tags hidden, and short interjections ("Mm-hmm",
"Yeah") folded away. Nothing else is cut or reworded. A clip with more than one voice keeps each turn under its
speaker's name.

Reads site/web/essentials.js (which clips), site/data/explainers.js and site/data/ep/. Writes site/data/quotes.js:

  window.FF_QUOTES = {clip id: [[speaker, text, times], ...]}

times: when each word of text (split on spaces) starts, in hundredths of a second from the clip's start, so the
page can light up the word being said.

Run:  python scripts/build_quotes.py
after build_site_data.py and build_explainers.py, and again whenever a transcript or a clip changes.
"""
import argparse
import json
import re
import sys

from build_site_data import read_js, write_js
from common import FOLD_MAX, ROOT, rel

SITE = ROOT / "site" / "data"
ESSENTIALS = ROOT / "site" / "web" / "essentials.js"


def load_ep(n):
    """Episode n as the site has it: {speakers, words: [{w, s, p, hide}], turns: [[p, s, e, w0, w1]]}."""
    t = (SITE / "ep" / f"{n:02d}.js").read_text(encoding="utf-8")
    d = json.loads(t[t.index("{"):t.rindex("}") + 1])
    words, cs, c = [], 0, d.get("c") or {}
    for i, txt in enumerate(d["ww"]):
        cs += d["ws"][i]
        f = ord(d["wf"][i]) - 48
        words.append({"w": c.get(str(i), txt), "s": cs / 100, "p": int(d["wp"][i], 36), "hide": bool(f & 6)})   # 2: sound tag, 4: hidden in the clean read
    return {"speakers": d["speakers"], "words": words, "turns": d["turns"]}


def clean_turns(ep, s, e):
    """The clean read between s and e, as [[speaker, text, times], ...] (times: each word's start, in hundredths of a
    second from s)."""
    out = []
    for p, _, _, w0, w1 in ep["turns"]:
        shown = [w for w in ep["words"][w0:w1] if not w["hide"]]
        if len(shown) <= FOLD_MAX:   # a folded interjection, as on the episode pages
            continue
        ws = [(tok, w["s"]) for w in shown if s - .02 <= w["s"] < e for tok in w["w"].split()]
        if not ws:
            continue
        if out and out[-1][0] == p:
            out[-1][1].extend(ws)
        else:
            out.append([p, ws])
    return [[ep["speakers"][p], " ".join(w for w, _ in ws), [max(0, round((t - s) * 100)) for _, t in ws]] for p, ws in out]


def clips():
    """(id, episode, start, end) for every clip the Explained page shows, in page order."""
    t = ESSENTIALS.read_text(encoding="utf-8")
    ids = [i for m in re.finditer(r"ids:\s*\[(.*?)\]", t, re.S) for i in re.findall(r'"([^"]+)"', m.group(1))]
    ex = {x["id"]: x for x in read_js(SITE / "explainers.js", "FF_EXPLAIN")["explainers"]}
    unknown = [i for i in ids if i not in ex]
    if unknown:
        sys.exit(f"{rel(ESSENTIALS)} lists unknown clip {', '.join(unknown)} (not in {rel(SITE / 'explainers.js')})")
    return [(i, ex[i]["n"], ex[i]["s"], ex[i]["e"]) for i in ids]


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    cache, out = {}, {}
    for i, n, s, e in clips():
        if n not in cache:
            cache[n] = load_ep(n)
        q = clean_turns(cache[n], s, e)
        if not q:
            sys.exit(f"{i}: no words between {s} and {e} in episode {n}")
        out[i] = q
    write_js(SITE / "quotes.js", "/* Explained's quotes, in the clean read. Built by scripts/build_quotes.py. */\nwindow.FF_QUOTES=",
             out, ";\n")
    multi = [i for i, q in out.items() if len(q) > 1]
    print(f"{len(out)} clips, {sum(len(t.split()) for q in out.values() for _, t, _ in q)} words, {len(multi)} with more than one voice: {multi}")


if __name__ == "__main__":
    main()
