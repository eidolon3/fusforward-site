"""Flag words that are probably wrong: low model confidence, or sounding like a listed term.

Run:  python scripts/flag.py 16
Output: out/flags/<NN>.json, one entry per flag: the raw word span (i, k), its text, its start ("s", seconds,
for a near_s in data/fixes; "time", m:ss), its context and, for near-misses, the listed term it resembles.
show_flags.py prints them. Claude reviews these and writes data/fixes/<NN>.json; nothing here changes the
transcript.
"""
import difflib
import json
import re

import jellyfish
from wordfreq import zipf_frequency

import common
from build_terms import terms_for
from common import ROOT

OUT = ROOT / "out" / "flags"
LOW = -0.4      # logprob; about 67% confidence. Only checked on rare words: low confidence on
                # "yeah"/"and" in crosstalk is common and nearly always right.
VERY_LOW = -1.0 # flagged whatever the word
SIMILAR = 0.8   # spelling similarity for a near-miss; 0.9 when every word is common English
RARE = 3.5      # wordfreq Zipf; below this a word is rare (e.g. "Aubry" 2.4, "skull" 4.0)
EDGE = {"a", "an", "and", "as", "at", "but", "for", "in", "is", "of", "on", "or", "so", "the", "to", "with"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def sound(s):
    return jellyfish.metaphone(re.sub(r"[^A-Za-z ]", " ", s)).replace(" ", "")


def rare(word):
    return zipf_frequency(re.sub(r"[^\w']", "", word.lower()), "en") < RARE  # keep apostrophes: "you'll"


def main():
    n = common.parser(__doc__).parse_args().n
    words = [w for w in common.load_json(ROOT / "out" / "raw" / f"{n:02d}.json")["words"] if w["type"] == "word"]

    terms = [(t, norm(t), sound(t), len(t.split())) for t in terms_for(n)]
    # Contiguous shorter pieces of each multi-word term, normalized.
    subs = {t: {norm(" ".join(t.split()[a:b])) for a in range(tk) for b in range(a + 1, tk + 1) if b - a < tk}
            for t, _, _, tk in terms}
    # Words already spelled exactly as a listed term (or its plural): spans touching them aren't near-misses.
    exact = set()
    for i in range(len(words)):
        for k in (1, 2, 3, 4, 5):
            nt = norm(" ".join(w["text"] for w in words[i:i + k]))
            if any(nt in (tn, tn + "s") for _, tn, _, _ in terms):
                exact.update(range(i, i + k))
    flags = []
    for i in range(len(words)):
        for k in (1, 2, 3, 4):
            span = words[i:i + k]
            if len(span) < k:
                break
            text = " ".join(w["text"] for w in span).strip(" ,.?!;:\"'")
            nt = norm(text)
            if len(nt) < 4 or exact & set(range(i, i + k)):
                continue
            if k > 1 and (norm(span[0]["text"]) in EDGE or norm(span[-1]["text"]) in EDGE):
                continue
            need = SIMILAR if any(rare(w["text"]) for w in span) else 0.9
            st = None
            for term, tn, ts, tk in terms:
                if abs(tk - k) > 1 or nt == tn or abs(len(nt) - len(tn)) > max(3, len(tn) // 3):
                    continue
                # Plurals and possessives of a listed term are fine as they are.
                if nt.rstrip("s") == tn.rstrip("s"):
                    continue
                # So is a shorter mention of a listed phrase ("acoustics" for "acoustic lens").
                if k < tk and any(difflib.SequenceMatcher(None, nt, sub).ratio() >= 0.85 for sub in subs[term]):
                    continue
                sm = difflib.SequenceMatcher(None, nt, tn)
                ratio = sm.ratio() if sm.real_quick_ratio() >= 0.6 and sm.quick_ratio() >= 0.6 else 0.0
                # Same sound counts too, for longer terms and spellings at least loosely alike.
                if ratio < need and ratio >= 0.6 and len(tn) >= 6:
                    st = st if st is not None else sound(text)
                if ratio >= need or (ratio >= 0.6 and len(tn) >= 6 and st == ts):
                    flags.append({"kind": "near_miss", "i": i, "k": k, "text": text, "term": term,
                                  "ratio": round(ratio, 2)})
    for i, w in enumerate(words):
        if not norm(w["text"]):
            continue  # "..." and other punctuation-only tokens
        if w["logprob"] < VERY_LOW or (w["logprob"] < LOW and rare(w["text"])):
            flags.append({"kind": "low_confidence", "i": i, "k": 1, "text": w["text"], "logprob": round(w["logprob"], 2)})

    # One entry per span, each with its context and timestamp.
    seen, out = set(), []
    for f in sorted(flags, key=lambda f: (f["i"], -f["k"])):
        key = (f["kind"], f["i"], f["k"], f.get("term"))
        if key in seen:
            continue
        seen.add(key)
        s = words[f["i"]]["start"]
        f["s"] = round(s, 2)
        f["time"] = f"{int(s) // 60:02d}:{int(s) % 60:02d}"
        f["context"] = " ".join(w["text"] for w in words[max(0, f["i"] - 8):f["i"] + f["k"] + 8])
        out.append(f)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{n:02d}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"ep {n}: {sum(f['kind'] == 'near_miss' for f in out)} near-misses, {sum(f['kind'] == 'low_confidence' for f in out)} low-confidence words")


if __name__ == "__main__":
    main()
