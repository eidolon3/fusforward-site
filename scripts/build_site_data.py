"""Write the site's data files from the master transcripts.

Run:  python scripts/build_site_data.py
Reads data/episodes.json (the feed), data/guests.json, data/affiliations.json and out/episodes/NN.json. A feed
episode without its master file yet is skipped, with a note; one missing from guests.json stops the build.
Output (site/data/), as .js files so pages also work opened straight from disk:
  episodes.js  window.FF_EPISODES: one entry per episode (title, date, guests, affiliation, audio, art, word count,
               talk time). title is the feed title without "Ep. N"; display_title also drops the guest's name in
               front ("A very fus future"); both start with a capital
  ep/NN.js     FF._ep(n, {...}): the words as columns (compact; shared/core.js FF.episode() decodes them):
               ww [text], ws [start minus the previous word's start, in hundredths of a second], wd [end minus
               start, hundredths], wp speakers as one base-36 digit per word, wf flags as one digit per word;
               turns [[speaker, start, end, w0, w1]].
               flags: 1 = marked uncertain, 2 = audio event like [laughs], 4 = hidden in the clean read;
               c: {word index: text} where the clean read shows a word differently ("so," -> "So");
               x: "Elsewhere in the series" for an episode with guests (scripts/site_xref.py)
  search.js    window.FF_SEARCH: transcript chunks of <= 35 words [[episode, start, speaker, text]]
  glossary.js  window.FF_GLOSSARY: listed terms that come up, with a definition where written and every hit
               as [episode, start, speaker]
build_explainers.py, build_mentions.py and build_quotes.py import DEFS, write_js and read_js from here.
"""
import argparse
import json
import re
import sys
import unicodedata
from email.utils import parsedate_to_datetime

from wordfreq import zipf_frequency

import clean_read
import site_xref
from build_terms import read
import common
from common import FOLD_MAX, HOSTS, NARRATOR, ROOT, hidden as hidden_eps, load_json, rel

SITE = ROOT / "site" / "data"
ART = ROOT / "site" / "assets" / "ep"
# "Ep. 23 Title", "Episode 23: Title", "Ep 23 - Title"
EP_PREFIX = re.compile(r"^\s*Ep(?:isode)?\.?\s*\d+\s*[:.\-–—]?\s*", re.I)

DEFS = {
    "ITRUSST": "International Transcranial Ultrasonic Stimulation Safety and Standards consortium: researchers who publish consensus safety and reporting guidelines for the field.",
    "PRF": "Pulse repetition frequency: how many ultrasound pulses are fired per second; in nested protocols, the faster of the two rates.",
    "pulse repetition frequency": "How many ultrasound pulses are fired per second (PRF); in nested protocols, the faster of the two rates.",
    "duty cycle": "The fraction of time the ultrasound is actually on.",
    "ISPPA": "Spatial-peak pulse-average intensity: intensity at the focus, averaged over one pulse.",
    "ISPTA": "Spatial-peak temporal-average intensity: intensity at the focus, averaged over the whole sonication including off time.",
    "mechanical index": "The derated peak negative pressure (in MPa) divided by the square root of the frequency (in MHz); an index of inertial-cavitation risk, capped at 1.9 for diagnostic imaging.",
    "thermal index": "An estimate of how much the beam could heat tissue: the acoustic power divided by the power needed to warm tissue by 1 °C.",
    "cavitation": "Gas bubbles forming, oscillating or collapsing in a sound field.",
    "inertial cavitation": "Violent bubble collapse, the kind that can damage tissue.",
    "blood-brain barrier": "The vessel lining that keeps most drugs out of the brain; ultrasound with microbubbles can open it briefly.",
    "microbubbles": "Gas-filled contrast agents that oscillate in an ultrasound field; used to open the blood-brain barrier.",
    "skull aberration": "Distortion of the beam by the skull's uneven thickness and density.",
    "aberration correction": "Undoing the skull's distortion so the beam still focuses: by timing each element of an array, or with an acoustic lens shaped for that skull.",
    "time reversal": "Recording waves that spread from a point and sending them back reversed in time so they refocus there, even through the skull; done physically with transducers, or numerically by back-propagating recordings, as in photoacoustic image reconstruction.",
    "k-Wave": "Open-source toolbox for simulating how sound travels through tissue and bone.",
    "BabelBrain": "Open-source planning tool for transcranial ultrasound, from Samuel Pichardo's lab.",
    "sonogenetics": "Making chosen neurons sensitive to ultrasound by giving them a mechanosensitive protein.",
    "auditory confound": "Ultrasound stimulation can be heard through the skull, which can explain some apparent brain effects.",
    "MR-ARFI": "MR acoustic radiation force imaging: MRI measures the tiny push at the focus to show where the beam lands.",
    "thalamotomy": "A small lesion in the thalamus, for tremor in its ventral intermediate (Vim) nucleus; focused-ultrasound thalamotomy treats essential tremor.",
    "HIFU": "High-intensity focused ultrasound, used to heat and destroy tissue.",
    "LIFU": "Low-intensity focused ultrasound, used to change brain activity without damaging tissue.",
    "TUS": "Transcranial ultrasound stimulation.",
    "tFUS": "Transcranial focused ultrasound.",
    "histotripsy": "Destroying tissue mechanically with very short, very intense pulses.",
    "pseudo-CT": "CT-like skull images synthesized from MRI, to plan the beam without radiation.",
    "Hounsfield units": "The CT density scale, used to estimate the skull's acoustic properties.",
    "neuronavigation": "Tracking the transducer against the person's MRI so the target is hit.",
    "sonication": "One application of ultrasound to a target.",
    "transducer": "The device that turns electrical signals into ultrasound.",
    "phased array": "A transducer made of many elements, each fired with its own timing to steer and shape the beam.",
    "acoustic lens": "A shaped piece placed on a transducer to focus or correct the beam, e.g. for one person's skull.",
    "essential tremor": "A common movement disorder; the first brain condition for which the FDA approved MR-guided focused ultrasound (thalamotomy, 2016).",
    "nucleus accumbens": "A deep brain region central to reward and motivation.",
    "amygdala": "A deep brain region central to fear and emotion.",
    "non-human primates": "Monkeys used in research, usually macaques.",
    "functional ultrasound": "Imaging brain activity through blood-flow changes, with ultrasound.",
    "MRgFUS": "MR-guided focused ultrasound: MRI aims the beam and monitors heating.",
}


# The show itself, and "Neuron" the journal (it matches every "neuron"): not glossary material.
SHOW = {"FUS Forward", "FUS win", "FUS wins", "Vanderbilt", "Attune", "Neuron"}
# Second spellings in the term lists (they help the transcriber); the glossary files their mentions under the first name.
ALIAS = {"JF Aubry": "Jean-François Aubry", "Samuel Pichardo": "Sam Pichardo"}
# Listed for the transcriber, but not ideas or people a reader looks up.
NOT_GLOSSARY = re.compile(r"\b(University|College|Officer)\b|^(Center of Excellence|open letter)$")


# Episode term lists mix researchers in with topics. A name of capitalized words (with particles
# like "de" or "van 't") and none of these institution words is treated as a person.
NAME = re.compile(r"^[A-Z][\w'’-]+(?: (?:de|van|von|di|da|del|der|le|la|'t))*(?: [A-Z][\w'’-]+)+$")
NOT_PERSON = re.compile(
    r"Universit|Institut|Hospital|Clinic|Capital|Cent(?:re|er)|Foundation|Therapeutic|Medical|Physic|"
    r"Imaging|Research|Neuro|Lab|Biotech|College|Societ|Corporation|Nature|Cell|Reports|National|"
    r"Officer|Chief|Investment|Polytechnic|Brain|Providence|Hotchkiss|Sunnybrook|Butler|Mayo|Donders|Stanford|Duke|Imagine")


def is_person(term):
    return bool(NAME.match(term)) and not NOT_PERSON.search(term)


def spell(title):
    """Feed titles drop accents the guests' names carry."""
    return title.replace("Jean-Francois", "Jean-François")


def capital(t):
    return t[:1].upper() + t[1:]


def match_key(s):
    """Lower case, accents dropped, letters and digits only: "Jean-François" -> "jeanfrancois"."""
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)))


def display_title(title, guests):
    """The title without the guest's name in front: "Lennart Verhagen a very fus future" -> "A very fus future"."""
    for name in ([" & ".join(guests)] if guests else []) + guests:
        if match_key(title).startswith(match_key(name)) and len(title) > len(name):
            return capital(title[len(name):].strip())
    return capital(title)


def write_js(path, prefix, obj, suffix=";"):
    """obj as compact JSON between prefix and suffix. "</" and U+2028/U+2029 are escaped, so the text can never
    close a <script> element or break an older JavaScript parser; both read the escapes back as the same string."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    s = s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    path.write_text(prefix + s + suffix, encoding="utf-8")


def read_js(path, name):
    """The value a data file assigns to window.<name> (the first JSON value after "window.<name>=")."""
    t = path.read_text(encoding="utf-8")
    m = re.search(rf"window\.{name}\s*=\s*", t)
    if not m:
        sys.exit(f"{rel(path)} has no window.{name}; rebuild it")
    return json.JSONDecoder().raw_decode(t, m.end())[0]


CLEAN_TEXT = ROOT / "out" / "clean-text"


def clean_text(ep, m, hide, shown):
    """The clean read as Markdown, laid out as FF.renderReadable (site/shared/core.js) lays it out with clean on: a block
    per speaker, paragraphs of about PARA_WORDS words broken at sentence ends, folded interjections ("Mm-hmm") left out.
    FF.cleanText makes the same text for the site's download; change the three together."""
    W, names, pw = m["words"], m["speakers"], clean_read.PARA_WORDS
    md = [f"# {ep['title']}", "", f"{ep['date']} · {', '.join(names)}", "",
          "Clean read: fillers, stutters, false starts and short interjections are hidden; no word is changed or added. "
          f"Every word as said: out/text/{m['n']:02d}.md. [?] marks words the model was unsure of.", ""]
    block, cur = None, None   # block: [who, start, paragraphs]; cur: [words, count, ends a sentence]

    def flush():
        nonlocal cur
        if cur and cur[0]:
            block[2].append(" ".join(cur[0]))
        cur = None

    def close():
        nonlocal block
        flush()
        if block:
            md.extend([f"**[{common.hms(block[1])[:8]}] {block[0]}:** " + "\n\n".join(block[2]), ""])
        block = None

    for k, t in enumerate(m["turns"]):
        vis = [i for i in range(t["w0"], t["w1"]) if i not in hide]
        if not vis or (len(vis) <= FOLD_MAX and k > 0):   # nothing shown, or a folded interjection
            continue
        who = names[t["p"]]
        if block and block[0] == who:   # the same speaker after a folded interjection: the same block
            if cur and cur[2] and cur[1] >= pw * .7:
                flush()
        else:
            close()
            block = [who, t["s"], []]
        for i in vis:
            if cur is None:
                cur = [[], 0, False]
            cur[0].append(shown[i] + (" [?]" if W[i].get("u") else ""))
            cur[1] += 1
            cur[2] = bool(clean_read.PARA_END.search(shown[i]))
            if (cur[2] and cur[1] >= pw * .7) or cur[1] >= pw * 1.6:
                flush()
    close()
    return "\n".join(md)


def columns(n, m):
    """Episode n's ep/NN.js object (without x), with the clean read applied (scripts/clean_read.py); writes the clean
    read as text too (out/clean-text/NN.md)."""
    W = m["words"]
    hide, strip = {}, set()
    for t in m["turns"]:
        clean_read.decide(W, t["w0"], t["w1"], hide, strip)
    shown = {}
    for t in m["turns"]:
        shown.update(clean_read.display(W, t["w0"], t["w1"], hide, strip))
    clean_read.finish(W, m["turns"], hide, shown)  # capitals and commas across turns, as the site lays them out
    for i, x in shown.items():
        if not x.strip():
            hide[i] = "empty"   # nothing left to show (a lone "-"): hidden, as the quotes already treat it
    CLEAN_TEXT.mkdir(parents=True, exist_ok=True)
    with open(CLEAN_TEXT / f"{n:02d}.md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(clean_text(feed_entry(n), m, hide, shown))
    flags = [(1 if w.get("u") else 0) | (2 if w.get("x") else 0) | (4 if i in hide else 0) for i, w in enumerate(W)]
    cs, ce = [round(w["s"] * 100) for w in W], [round(w["e"] * 100) for w in W]
    # The page rebuilds each time as a running sum / 100, which gives back exactly the same number.
    if not all(a / 100 == w["s"] and b / 100 == w["e"] for a, b, w in zip(cs, ce, W)):
        sys.exit(f"ep {n}: word times are not in hundredths of a second")
    if len(m["speakers"]) > 36:
        sys.exit(f"ep {n}: {len(m['speakers'])} speakers; wp has one base-36 digit per word")
    return {
        "n": n, "title": m["title"], "duration_s": m["duration_s"], "audio_url": m["audio_url"], "speakers": m["speakers"],
        "ww": [w["w"] for w in W], "ws": [b - a for a, b in zip([0] + cs[:-1], cs)], "wd": [b - a for a, b in zip(cs, ce)],
        "wp": "".join("0123456789abcdefghijklmnopqrstuvwxyz"[w["p"]] for w in W), "wf": "".join(map(str, flags)),
        "turns": [[t["p"], t["s"], t["e"], t["w0"], t["w1"]] for t in m["turns"]],
        "c": {i: x for i, x in shown.items() if x != W[i]["w"] and i not in hide}}


def feed_entry(n):
    """Episode n's data/episodes.json entry (its title and date head the clean text)."""
    return next(e for e in common.episodes() if e["n"] == n)


def entry(ep, m, guests, affiliation):
    """Episode ep's FF_EPISODES entry."""
    n = ep["n"]
    for k in ("link", "audio_url"):
        if not (ep[k] or "").startswith("https://"):
            sys.exit(f"ep {n}: feed {k} is not https: {ep[k]!r}")
    talk = {}
    for t in m["turns"]:
        talk[m["speakers"][t["p"]]] = talk.get(m["speakers"][t["p"]], 0) + t["e"] - t["s"]
    if not ep.get("date"):
        sys.exit(f"ep {n}: data/episodes.json has no date (the feed gave no pubDate). Add one by hand, "
                 'e.g. "date": "Mon, 03 Nov 2026 12:00:00 GMT", and run this again.')
    title = capital(spell(EP_PREFIX.sub("", ep["title"]).strip()))
    own_art = (ART / f"{n:02d}.jpg").exists()  # scripts/fetch_art.py downloads the episodes that have their own art
    return {
        "n": n, "title": title, "display_title": display_title(title, guests), "full_title": spell(ep["title"]),
        "date": parsedate_to_datetime(ep["date"]).date().isoformat(), "duration_s": m["duration_s"],
        "guests": guests, "affiliation": affiliation, "hosts": list(HOSTS),
        "audio_url": ep["audio_url"], "link": ep["link"], "notes": ep["notes"],   # the hosts' text, as the feed has it
        "art": f"assets/ep/{n:02d}.jpg" if own_art else "assets/cover.jpg",  # relative to site/
        "words": sum("x" not in w for w in m["words"]),
        "talk_min": {k: round(v / 60, 1) for k, v in sorted(talk.items(), key=lambda x: -x[1]) if k != NARRATOR},
    }


def chunks(n, m):
    """Search chunks: each turn cut into pieces of <= 35 words, so a hit lands near the right second."""
    out = []
    for t in m["turns"]:
        ws = [w for w in m["words"][t["w0"]:t["w1"]] if "x" not in w]
        for k in range(0, len(ws), 35):
            part = ws[k:k + 35]
            out.append([n, part[0]["s"], m["speakers"][t["p"]], " ".join(w["w"] for w in part)])
    return out


def glossary(masters):
    """Every listed term that comes up, with its hits. Kinds follow the term files."""
    kinds = [("jargon", read("core.txt")), ("person", read("people.txt"))]
    kinds += [("episode", read(f"{n:02d}.txt")) for n in masters]
    seen, gloss = set(), []
    index = {n: [match_key(w["w"]) for w in m["words"]] for n, m in masters.items()}
    where = {}   # token -> [(episode, word index)], in episode and word order
    for n, toks in index.items():
        for i, tok in enumerate(toks):
            where.setdefault(tok, []).append((n, i))
    order = {n: k for k, n in enumerate(index)}
    for kind, terms in kinds:
        for term in terms:
            key = match_key(term)
            if key in seen or len(key) < 3 or term in SHOW:
                continue
            # Single ordinary words ("Neuron" the journal matches every "neuron") and first names alone.
            if " " not in term and not term.isupper() and (zipf_frequency(term.lower(), "en") >= 3.5 or kind == "person"):
                continue
            seen.add(key)
            parts = [match_key(p) for p in term.split()]
            hits = []
            starts = sorted(where.get(parts[0], []) + where.get(parts[0] + "s", []), key=lambda x: (order[x[0]], x[1]))
            for n, i in starts:
                toks = index[n]
                if i + len(parts) <= len(toks) and all(toks[i + j] in (parts[j], parts[j] + "s") for j in range(1, len(parts))):
                    w = masters[n]["words"][i]
                    hits.append([n, w["s"], masters[n]["speakers"][w["p"]]])
            if hits:
                gloss.append({"term": term, "kind": "person" if kind == "person" or is_person(term) else "term",
                              "def": DEFS.get(term, ""), "count": len(hits), "episodes": sorted({h[0] for h in hits}), "hits": hits})
    by = {g["term"]: g for g in gloss}
    for alt, main in ALIAS.items():
        a, b = by.get(alt), by.get(main)
        if a and b:
            b["hits"] = sorted({tuple(h) for h in a["hits"] + b["hits"]}, key=lambda h: (h[0], h[1]))
            b["hits"] = [list(h) for h in b["hits"]]
            b["count"], b["episodes"] = len(b["hits"]), sorted({h[0] for h in b["hits"]})
        elif a:
            a["term"] = main
    gloss = [g for g in gloss if not (g["term"] in ALIAS and g["term"] in by and ALIAS[g["term"]] in by)]
    gloss = [g for g in gloss if not NOT_GLOSSARY.search(g["term"])]
    gloss.sort(key=lambda g: -g["count"])
    return gloss


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    data = ROOT / "data"
    feed, guests, affil = (load_json(data / f) for f in ("episodes.json", "guests.json", "affiliations.json"))
    episodes, search, masters, ep_out, no_thumbs = [], [], {}, {}, []
    print("episodes: clean read, transcript columns, search chunks", flush=True)
    hidden = hidden_eps()
    for ep in feed:
        n = ep["n"]
        if n in hidden:
            print(f"ep {n}: hidden (data/hidden.json), left out of the site")
            (SITE / "ep" / f"{n:02d}.js").unlink(missing_ok=True)
            continue
        path = ROOT / "out" / "episodes" / f"{n:02d}.json"
        if not path.exists():
            print(f"ep {n}: skipped, no {rel(path)} yet (python scripts/build_episode.py {n})")
            continue
        if str(n) not in guests:
            sys.exit(f'ep {n}: not in data/guests.json. Add "{n}": ["First Last"], or "{n}": [] for hosts only.')
        g = guests[str(n)]
        if g and str(n) not in affil:   # "" means "deliberately none", and stays quiet
            print(f"ep {n}: has guests but no affiliation in data/affiliations.json")
        m = masters[n] = load_json(path)
        ep_out[n] = columns(n, m)
        episodes.append(entry(ep, m, g, affil.get(str(n), "")))
        search += chunks(n, m)
        if (ART / f"{n:02d}.jpg").exists() and not all((ART / size / f"{n:02d}.jpg").exists() for size in ("sm", "md")):
            no_thumbs.append(f"{n:02d}")
    if no_thumbs:
        print(f"no sm/ or md/ thumbnail for ep {', '.join(no_thumbs)}: run python scripts/make_thumbs.py")

    (SITE / "ep").mkdir(parents=True, exist_ok=True)
    write_js(SITE / "episodes.js", "window.FF_EPISODES=", episodes)
    write_js(SITE / "search.js", "window.FF_SEARCH=", search)
    print("glossary", flush=True)
    gloss = glossary(masters)
    write_js(SITE / "glossary.js", "window.FF_GLOSSARY=", gloss)
    # The episodes, now that the search chunks and glossary exist for their cross-references.
    print("cross-references (Elsewhere in the series)", flush=True)
    others = site_xref.elsewhere(episodes, gloss, search, masters)
    for n, d in ep_out.items():
        if n in others:
            d["x"] = others[n]
        write_js(SITE / "ep" / f"{n:02d}.js", f"FF._ep({n},", d, ");")
    sizes = ", ".join(f"{p.name} {p.stat().st_size // 1024} KB" for p in sorted(SITE.glob("*.js")))
    print(f"{len(episodes)} episodes, {len(search)} search chunks, {len(gloss)} glossary terms -> {rel(SITE)}: {sizes}")


if __name__ == "__main__":
    main()
