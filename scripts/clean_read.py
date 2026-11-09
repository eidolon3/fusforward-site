"""Clean read: decide which words to hide in the readable transcript, without changing it.

Run:  python scripts/clean_read.py 22 [--sample 60]
Reads out/episodes/<NN>.json. Writes out/clean/<NN>.html, a check page: the transcript before and after,
side by side, the "after" as the site shows it (build_site_data.py applies the same decide(), display()
and finish()). --sample prints that many random hidden spots in context, for checking the rules.

Rules, safest first. Each one only hides words; none adds or changes one.
  sound     tagged audio events: [laughs], [clears throat]
  filler    uh, um, er, hmm, mm-hmm
  repeat    the same 1-3 words again right after a comma or a cut-off: "I, I, I", "the- the"; a short
            function word said twice with no comma at all ("it it", "the the") counts too
  cut-off   a word broken off with "-": "Nev- never" keeps "never"; "You just kept- I never" drops the
            abandoned phrase back to the last punctuation mark, if that is at most 3 words back. A word
            broken off by someone else ("a battle- [Mm-hmm] ... where") is kept, without its dash; a broken-off
            sound ("wanna m- give") goes alone; a phrase too long to drop whole is kept whole, except a short
            fragment that is no word of its own ("cycles of pre- positive"), which goes alone.
            A trailing-off "word..." (or "word, uh...") inside a turn followed by a restart (a capital) goes
            when it is itself broken off or said again: "Cal... California", "So... So we". The
            words before it stay: "how I felt about... I was" is a thought left hanging, not a false start
  pause / interjection   "..." pauses, and a "Yeah ..." from someone else left inside a turn
  like      "like" set off by commas: ", like," or a sentence-opening "Like,"; not before a number
  you know  ", you know," / ", you know?" (not "do you know", "you know what")
  I mean    a clause-opening "I mean,"
  right     a tag ", right?"
For display, a sentence end carried by a hidden word moves to the word before it, a word that now opens
a sentence gets a capital, and the commas around a dropped "you know" / "I mean" / "like" go with it.
A "..." is not a sentence end: no capital after it. A restart after a dropped cut-off keeps the sentence
going ("in my lab, we want to-- Because" -> "in my lab, because") unless the word is a name (never written
lower-case in the episode). A turn never ends on a comma. finish() then repairs what only shows across
turns, as FF.renderReadable lays them out: the first word of a speaker's block gets a capital, as does a
turn that carries on a block after a folded interjection when the block's last sentence ended; a function
word said again across that interjection ("And- [Yeah.] and like") is shown once; and no paragraph ends on
a comma.
"""
import html
import random
import re
from collections import Counter

from wordfreq import zipf_frequency

import common
from common import FOLD_MAX, ROOT, SENTENCE_END as END, mmss

OUT = ROOT / "out" / "clean"

FILLERS = {"uh", "um", "uhm", "er", "erm", "ah", "hmm", "mm", "mhm", "mm-hmm", "uh-huh"}
BACKCHANNEL = {"yeah", "yes", "mm-hmm", "uh-huh", "right", "okay", "sure", "exactly", "totally", "wow"}
# Said twice for emphasis, not a stutter: "no, no", "really, really".
EMPHATIC = {"no", "yes", "yeah", "very", "really", "so", "much", "way", "bye", "okay", "ok"}
# A comma after these is the speaker's own ("Well, you know, it's" keeps "Well,").
KEEP_COMMA = {"yeah", "yes", "no", "well", "oh", "okay", "ok", "now", "look"}
# Joining words: "And, you know, you get" drops the comma even at the start of a sentence.
GLUE = {"the", "a", "an", "of", "to", "as", "and", "but", "or", "so", "with", "for", "in", "on", "at", "from", "about", "into",
        "that", "which", "because", "than", "is", "are", "was", "were", "my", "your", "our", "their", "his", "her", "its"}
I_WORDS = {"i", "i'm", "i've", "i'll", "i'd"}
REAL_END = re.compile(r"(?:[?!]|(?<!\.)\.)[\"”’)]*$")  # a sentence end; "..." is not one
BREAK = re.compile(r"([,;:.?!]|\.\.\.)[\"”’)]*$")
# A paragraph may end after a word that ends like this: ends() in FF.renderReadable (site/shared/core.js),
# where "…" counts too. Used by finish() and paras() below.
PARA_END = re.compile(r"[.?!…][\"”’)]*$")
PARA_WORDS = 80  # FF.renderReadable's paraWords
# Said twice with no comma, these are a stutter ("it it"), never meant: "that that" and "had had" can be.
FUNCTION = {"the", "a", "an", "of", "to", "and", "but", "or", "so", "in", "on", "at", "for", "with", "it", "i", "you",
            "we", "they", "he", "she", "is", "was", "are", "my", "your", "our", "their", "this", "there", "what", "if"}
# Whole words of three letters or fewer. A broken-off "pre-", "com-" or "sh-" is none of these: a fragment.
SHORT_WORDS = {"i", "a", "an", "at", "be", "by", "do", "go", "he", "if", "in", "is", "it", "me", "my", "no", "of", "oh", "on",
               "or", "so", "to", "up", "us", "we", "all", "and", "any", "are", "but", "can", "did", "for", "get", "got", "had",
               "has", "her", "him", "his", "how", "its", "let", "may", "new", "not", "now", "one", "our", "out", "say",
               "see", "she", "the", "too", "two", "use", "was", "way", "who", "why", "yes", "yet", "you"}
# A restart with one of these opens a new sentence; lower-cased it would read on ("understand it well").
OPENERS = {"well", "so", "now", "okay", "ok", "yeah", "yes", "no", "right", "oh", "anyway", "wait", "sorry", "actually"}
# The episode whose lower-case words were last collected, and those words (see lower_ok).
_lower_seen = (None, set())


def lower_ok(words, t):
    """True when t's word is written lower-case somewhere in the episode, so it's not a name."""
    global _lower_seen
    if _lower_seen[0] is not words:  # held, not just its id(), so a new episode's list can't be mistaken for it
        _lower_seen = (words, {core(w["w"]) for w in words if w["w"][:1].islower()})
    c = core(t)
    return bool(c) and c in _lower_seen[1] and c not in I_WORDS and not re.sub(r"\W", "", t).isupper()


def is_fragment(c):
    """A broken-off piece that is no word of its own: "pre", "un", "col"; not "as", "try" or "lot"."""
    return 0 < len(c) <= 3 and c.isalpha() and c not in SHORT_WORDS and zipf_frequency(c, "en") < 5.4


def core(w):
    return re.sub(r"[^\w'-]", "", w.lower()).strip("-'")


def decide(words, w0, w1, hide, strip):
    """Fill hide {word index: rule} for the words of one turn, and strip with interrupted words."""
    for i in range(w0, w1):
        if words[i].get("x"):
            hide[i] = "sound"
        elif core(words[i]["w"]) in FILLERS:
            hide[i] = "filler"
        elif words[i]["w"] == "...":
            hide[i] = "pause"  # a pause, or where a turn resumes after someone else's interjection
    vis = lambda: [i for i in range(w0, w1) if i not in hide]
    W = lambda i: words[i]["w"]

    # Repeats, before cut-offs (so "I, I, I-- often" loses all three I's) and again after them.
    def repeats():
        v, j = vis(), 0
        while j < len(v):
            for n in (3, 2, 1):
                a, b = v[j:j + n], v[j + n:j + 2 * n]
                same = len(b) == n and [core(W(i)) for i in a] == [core(W(i)) for i in b]
                bare = (n == 1 and same and W(a[0]).lower() == W(b[0]).rstrip(",.?!").lower() and W(a[0]).lower() in FUNCTION
                        and not (len(W(b[0])) == 1 and W(b[0]).isupper()))  # "it it", "And and"; not "a A plus B"
                if (same and (re.search(r"[,-]$", W(a[-1])) or bare)
                        and not (n == 1 and core(W(a[0])) in EMPHATIC)):
                    for i in a:
                        hide[i] = "repeat"
                    j += n
                    break
            else:
                j += 1
    repeats()

    v = vis()

    def trails(j):
        """v[j] trails off ("about..." or "about, uh...") into a restart later in the same turn."""
        i = v[j]
        if j == len(v) - 1 or W(i).endswith("-"):
            return False
        nx = W(v[j + 1])
        if not nx[:1].isupper() or re.match(r"[\"“]", nx) or core(nx) in BACKCHANNEL:
            return False  # carries on, a quote, or maybe someone else's "Yeah": keep
        # its own "...", or a filler's ("about, uh... What"); not a bare "...", which marks an interruption
        return W(i).endswith("...") or any(W(k).endswith("...") and hide.get(k) == "filler" for k in range(i + 1, v[j + 1]))

    for j, i in enumerate(v):
        if trails(j):
            # Only a broken-off word goes, never the phrase before it: "how I felt about... I was" is a
            # thought left hanging, and dropping it would change what was said.
            stem, nxt = core(W(i)), core(W(v[j + 1]))
            if stem and (nxt == stem or (len(stem) >= 3 and nxt.startswith(stem))):  # "So... So we", "Cal... California"
                hide[i] = "cut-off"
            continue
        if not W(i).endswith("-"):
            continue
        # Interrupted, not abandoned: the turn ends there (someone else talks), or a laugh or a "Yeah" the
        # diarization left in this turn is followed by "...", where the speaker carries on. Keep the
        # word, drop its dash (and that stray "Yeah ...").
        k = i + 1
        while k < w1 and (core(W(k)) in BACKCHANNEL or words[k].get("x")):
            k += 1
        if j == len(v) - 1 or (k < w1 and W(k) == "..."):
            strip.add(i)
            for b in range(i + 1, min(k + 1, w1)):
                hide.setdefault(b, "interjection")
            continue
        if re.match(r"[\"“]", W(v[j + 1])):
            continue  # "you were like- "Well, ..."": the dash introduces a quote
        hide[i] = "cut-off"
        nxt = core(W(v[j + 1]))
        if nxt.startswith(core(W(i))):
            continue  # "Nev- never": the word is said again in full
        back, k = [], j - 1
        while k >= 0 and not BREAK.search(W(v[k])) and len(back) < 4:
            back.append(v[k])
            k -= 1
        same = [m for m, b in enumerate(back[:3]) if core(W(b)) == nxt]
        if same:
            back = back[:same[0] + 1]  # "smoothing can el- can eliminate": the restart repeats "can"
        elif (len(core(W(i))) == 1 and core(W(i)) not in {"i", "a"}) or zipf_frequency(core(W(i)), "en") < 3.5:
            back = []  # a broken-off sound ("wanna m- give"): only it goes
        elif len(back) > 3 or (k >= 0 and not BREAK.search(W(v[k]))):
            # The abandoned phrase starts too far back to drop whole: keep it, except a fragment that is no word
            # of its own ("cycles of pre- positive"), which goes alone.
            if is_fragment(core(W(i))) and W(i)[:1].islower() and W(v[j + 1])[:1].islower():   # mid-sentence, not "MRI-" or "pro-- Oh,"
                continue
            del hide[i]
            continue
        for b in back:
            hide[b] = "cut-off"
    repeats()

    v = vis()
    opens = lambda j: j == 0 or BREAK.search(W(v[j - 1])) or W(v[j] - 1) == "..."
    for j, i in enumerate(v):
        c, nx = core(W(i)), v[j + 1] if j + 1 < len(v) else None
        if c == "like" and W(i).endswith(",") and opens(j) and not (nx and re.match(r"\d", W(nx))):
            hide[i] = "like"
        elif c == "you" and nx and core(W(nx)) == "know" and re.search(r"[,.?]$", W(nx)) and opens(j):
            hide[i] = hide[nx] = "you know"
        elif c == "i" and nx and core(W(nx)) == "mean" and W(nx).endswith(",") and opens(j):
            hide[i] = hide[nx] = "I mean"
        elif c == "right" and W(i).endswith("?") and j > 0 and W(v[j - 1]).endswith(","):
            hide[i] = "right"
    repeats()  # "carried a lot, you know, carried a lot" is a repeat once "you know" is gone


def display(words, w0, w1, hide, strip):
    """Visible text for each shown word of a turn, with punctuation and capitals repaired."""
    shown, out, cap = [i for i in range(w0, w1) if i not in hide], {}, True
    pending, pause, comma = None, False, False  # what the hidden run before the next shown word carried
    cut = False  # the hidden run ended a false start
    for i in range(w0, w1):
        t = words[i]["w"].rstrip("-") if i in strip else words[i]["w"]
        r = hide.get(i)
        if r in ("pause", "interjection"):
            cap = cap and bool(out)  # a turn resuming after "..." carries on mid-sentence
            pause = pause or (r == "pause" and bool(out))
            continue
        if r:
            m = END.search(t)
            if r in ("cut-off", "repeat"):
                cut = True  # a false start's own "..." or "." is not carried over; "do-- Do you" -> "do you"
            elif m and not cut:  # "the flag of, uh... I mean," keeps its trailing off: "the flag of..."
                pending = "." if r in ("you know", "right") else "..." if t.rstrip("\"”’)").endswith("...") else m.group(0)
            comma = t.endswith(",")
            continue
        if out:
            last = max(out)
            prev = out[last]
            # A sentence's first word keeps its comma ("This, um, I've written"), unless it's "And", "But"...
            before = [k for k in out if k < last]
            opener = not before or bool(END.search(out[max(before)]))
            if pending:
                if not END.search(prev):
                    out[last] = re.sub(r"[,;:]$", "", prev) + pending
                cap = bool(REAL_END.search(out[last]))  # no capital after "..."
            elif cut and not REAL_END.search(prev) and t[:1].isupper() and lower_ok(words, t):
                if core(t) in OPENERS and core(prev) not in GLUE:
                    out[last] = re.sub(r"[,;:]$", "", prev) + "."  # "time, so you get-- Yeah," -> "time. Yeah,"
                else:
                    t = t[0].lower() + t[1:]  # the restart carries the sentence on: "in my lab, because"
            elif pause and not cut and not BREAK.search(prev) and last not in strip:
                out[last] = prev + ("." if t[:1].isupper() and core(t) not in I_WORDS else ",")
            elif comma and prev.endswith(",") and core(prev) not in KEEP_COMMA and (not opener or core(prev) in GLUE):
                out[last] = prev[:-1]  # "underweight, you know, industrial design", "the infamous, uh, concert"
        pending, pause, comma, cut = None, False, False, False
        out[i] = t[0].upper() + t[1:] if cap and t[:1].islower() and (i - 1 in hide or i == shown[0]) else t
        cap = bool(REAL_END.search(out[i]))
    if out and max(out) < w1 - 1 and not END.search(out[max(out)]):
        # The turn ends on hidden words ("easily addressed, uh-"): end on what they carried, else trail off.
        out[max(out)] = re.sub(r"[,;:]$", "", out[max(out)]) + (pending or ("..." if out[max(out)].endswith(",") else ""))
    elif out and out[max(out)].endswith(","):
        out[max(out)] = out[max(out)][:-1]  # cut off by the next speaker: no dangling comma
    return out


def finish(words, turns, hide, shown, para_words=PARA_WORDS):
    """Repairs across turns, laid out as FF.renderReadable (site/shared/core.js) does with clean on.
    shown: {word index: text} from display() for every turn; changed in place, as is hide.
    Turns fold as on the site: one with nothing shown, or (after the first) one of at most FOLD_MAX shown words.
    Paragraphs follow the site's fill(), the same rule as paras() below; change them together. A paragraph
    splits on the shown text: at a sentence end ("…" too) once it has 70% of para_words shown words, anywhere
    at 160%, and at a change of speaker. It carries on across a folded interjection, unless it had just ended a
    sentence at a good length. None ends on a comma. (The site also ends a paragraph at a chapter heading,
    which this can't know.)"""
    text = lambda i: shown.get(i, words[i]["w"])
    who, last = None, None  # the open block's speaker, and its last shown word
    para = {"n": 0, "end": False, "last": None}  # the open paragraph: shown words, ends a sentence, last word

    def end_para():
        i = para["last"]
        if i is not None and text(i).endswith(","):
            shown[i] = text(i)[:-1]
        para.update(n=0, end=False, last=None)

    for k, t in enumerate(turns):
        vis = [i for i in range(t["w0"], t["w1"]) if not (words[i].get("x") or i in hide)]
        if not vis or (k and len(vis) <= FOLD_MAX):
            continue  # folded out of the reading flow
        same = who == t["p"]
        if same and last is not None and len(vis) > 1:
            a, b = text(last), text(vis[0])
            if (core(a) == core(b) and core(a) in FUNCTION and not END.search(a)
                    and not (len(b) == 1 and b.isupper())):
                hide[vis[0]] = "repeat"  # "And- [Yeah.] and like DBS": said again after someone's interjection
                shown.pop(vis[0], None)
                vis = vis[1:]
                if len(vis) <= FOLD_MAX:
                    continue  # now short enough that the site folds it
        if (not same or last is None or REAL_END.search(text(last))) and text(vis[0])[:1].islower():
            shown[vis[0]] = text(vis[0])[0].upper() + text(vis[0])[1:]
        if not same or (para["end"] and para["n"] >= para_words * .7):
            end_para()
        for i in vis:
            para.update(n=para["n"] + 1, end=bool(PARA_END.search(text(i))), last=i)
            if (para["end"] and para["n"] >= para_words * .7) or para["n"] >= para_words * 1.6:
                end_para()
        who, last = t["p"], vis[-1]
    end_para()


def sections(m):
    """The blocks of the verbatim reading, as FF.renderReadable makes them: a turn of 1 to FOLD_MAX words
    (after the first) folds, and a speaker's turns join across it."""
    words, secs = m["words"], []
    for k, t in enumerate(m["turns"]):
        n = sum(1 for i in range(t["w0"], t["w1"]) if not words[i].get("x"))
        if k and 0 < n <= FOLD_MAX:
            continue
        if secs and secs[-1]["p"] == t["p"]:
            secs[-1]["turns"].append(t)
        else:
            secs.append({"p": t["p"], "s": t["s"], "turns": [t]})
    return secs


def paras(tokens, para_words=PARA_WORDS):
    """(index, text, gone) tokens in paragraphs, by the rule of FF.renderReadable's fill() in site/shared/core.js
    (see finish(); change them together); gone tokens (sound tags, hidden words) don't count."""
    out, cur, n = [], [], 0
    for t in tokens:
        cur.append(t)
        if t[2]:
            continue
        n += 1
        if (PARA_END.search(t[1]) and n >= para_words * .7) or n >= para_words * 1.6:
            out.append(cur)
            cur, n = [], 0
    return out + [cur] if cur else out


def main():
    p = common.parser(__doc__)
    p.add_argument("--sample", type=int, default=0, metavar="K", help="print K random hidden spots in context")
    args = p.parse_args()
    n, sample = args.n, args.sample
    m = common.load_json(ROOT / "out" / "episodes" / f"{n:02d}.json")
    OUT.mkdir(parents=True, exist_ok=True)
    words, names, hide, strip = m["words"], m["speakers"], {}, set()
    for t in m["turns"]:
        decide(words, t["w0"], t["w1"], hide, strip)
    after_text = {}
    for t in m["turns"]:
        after_text.update(display(words, t["w0"], t["w1"], hide, strip))
    finish(words, m["turns"], hide, after_text)

    # Side by side: each row is one block of the verbatim reading, with the same words cleaned on the right.
    rows = []
    for sec in sections(m):
        before = [(i, words[i]["w"], bool(words[i].get("x"))) for t in sec["turns"] for i in range(t["w0"], t["w1"])]
        after = [(i, after_text.get(i, words[i]["w"]), i in hide) for i, _, _ in before]
        bh = "".join("<p>" + " ".join(f'<span class="{"ev" if x else ""}">{html.escape(w)}</span>' for _, w, x in p) + "</p>" for p in paras(before))
        ah = "".join("<p>" + " ".join(f'<del title="{hide[i]}">{html.escape(words[i]["w"])}</del>' if h else html.escape(w)
                                      for i, w, h in p) + "</p>" for p in paras(after))
        if not any(not h for _, _, h in after):
            ah = '<p class="gone">(nothing left: all filler)</p>'
        rows.append(f'<div class="who"><b>{html.escape(names[sec["p"]])}</b> {mmss(sec["s"])}</div><div class="b">{bh}</div><div class="a">{ah}</div>')

    counts = Counter(hide.values())
    total = sum(1 for w in words if not w.get("x"))
    spoken_hidden = sum(1 for i, r in hide.items() if r != "sound")
    stats = " · ".join(f"{r} {c}" for r, c in counts.most_common())
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clean read check · Ep {n}</title>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;1,6..72,400&family=Archivo:wght@500;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#f7f4ee;--t1:#1d1b18;--t2:#5d574e;--rule:#ddd6ca;--del:#b3261e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1b1916;--t1:#ede7dc;--t2:#b9b1a4;--rule:#36332e;--del:#ff8a80}}}}
body{{margin:0;background:var(--bg);color:var(--t1);font:18px/1.65 Newsreader,Georgia,serif}}
header{{max-width:1240px;margin:0 auto;padding:40px 16px 8px}}h1{{font:700 26px/1.2 Archivo,sans-serif;margin:0 0 8px}}
.meta{{font:500 14px/1.5 Archivo,sans-serif;color:var(--t2)}}label{{display:inline-flex;gap:8px;align-items:center;margin-top:14px;font:500 14px Archivo,sans-serif;cursor:pointer}}
.grid{{max-width:1240px;margin:0 auto;padding:0 16px 80px;display:grid;grid-template-columns:1fr 1fr;column-gap:48px}}
.col{{position:sticky;top:0;background:var(--bg);font:700 12px Archivo,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--t2);padding:16px 0 8px;border-bottom:1px solid var(--rule)}}
.who{{grid-column:1/-1;margin-top:26px;font:500 13px Archivo,sans-serif;color:var(--t2)}}.who b{{font-weight:700;color:var(--t1);margin-right:6px}}
.b p,.a p{{margin:6px 0 0}}.ev{{font-style:italic;color:var(--t2)}}.gone{{color:var(--t2);font-style:italic}}
del{{display:none;color:var(--del);text-decoration:line-through}}body.diff del{{display:inline}}
@media (max-width:760px){{.grid{{grid-template-columns:1fr}}.col:nth-child(2){{display:none}}.a{{border-left:3px solid var(--rule);padding-left:12px}}}}
</style></head><body>
<header><h1>Clean read check: Ep {n}, {html.escape(re.sub(r"^Ep[.] [0-9]+ *", "", m["title"]))}</h1>
<div class="meta">Left: the transcript as the site shows it now. Right: the same words with the clean-read rules applied. The transcript itself is unchanged.<br>
{total:,} spoken words; {spoken_hidden:,} hidden ({spoken_hidden / total:.1%}), plus {counts["sound"]} sound tags. By rule: {stats}.</div>
<label><input type="checkbox" onchange="document.body.classList.toggle('diff',this.checked)"> Show what was hidden (struck through, hover for the rule)</label></header>
<div class="grid"><div class="col">Before (now)</div><div class="col">After (clean read)</div>{"".join(rows)}</div></body></html>"""
    (OUT / f"{n:02d}.html").write_text(page, encoding="utf-8")
    print(f"ep {n}: {total} spoken words, {spoken_hidden} hidden ({spoken_hidden / total:.1%}); {stats}")

    if sample:
        random.seed(n)
        spoken = sorted(i for i, r in hide.items() if r != "sound")
        for i in sorted(random.sample(spoken, min(sample, len(spoken)))):
            ctx = " ".join(("[" + words[k]["w"] + "]") if k == i else words[k]["w"] for k in range(max(0, i - 6), min(len(words), i + 7)))
            print(f"{hide[i]:>9} | {ctx}")


if __name__ == "__main__":
    main()
