"""Build the master transcript for an episode, then the files made from it.

Run:  python scripts/build_episode.py 16 [--show-boundaries]
Reads out/raw/<NN>.json (words), out/speakers/<NN>.json (names) and data/fixes/<NN>.json.
Writes out/episodes/<NN>.json, the master file, and from it out/text/<NN>.md, out/vtt/<NN>.vtt
and out/srt/<NN>.srt. Never edit those four by hand: change the inputs and rebuild.

Master file words: {"w": text, "s": start, "e": end, "p": speaker index, "lp": logprob,
"u": 1 if marked uncertain, "x": 1 for audio events like [laughs]}.

data/fixes/<NN>.json, applied in this order (every entry is checked first; a missing key stops the build):
  fix        [{"i", "k", "from", "to", "why"}] swap a flagged span (raw word index i, k words) for a listed term.
             `from` is compared without punctuation or case, so the text show_flags.py prints can be pasted.
  uncertain  [{"i", "why"}] mark a word [?] by raw word index, or [{"near_s", "text", "why"}] by text anchor
  replace    [{"near_s", "from", "to", "why"}] word corrections: the word sequence `from` (compared without
             punctuation or case; a possessive 's is kept) nearest near_s, within 10 s, becomes `to`. Each
             word keeps its timing; when the word count changes, the span's time is shared out by length.
             No match is an error, so nothing fails silently. With "all": true every match in the episode
             is corrected (near_s is then optional). A `from` left uncorrected within 120 s of a
             correction is printed as a warning (the same misspelling said twice).
  speaker    [{"from_s", "to_s", "who", "why"}] or [{"near_s", "text", "who", "why"}]: the words starting in
             [from_s, to_s), or the word sequence `text` nearest near_s, are given to `who`. Applied after the
             voice naming and the boundary repair below, so these explicit reviews win.
  open_questions  ["..."] notes for whoever listens to the audio; not applied.
Every key is optional.
The stock cold open (data/cold_open.json: one recording, the same in every episode that opens with it) is
put in place of whatever the transcriber made of it, with fixed speakers; nothing else touches it.
Between naming and the speaker list, turn boundaries are repaired: a turn that opens with a fragment of at
most 3 words starting lower-case and ending a sentence ("suicidal thought.") gives it back to the previous
turn when that turn's last word did not end a sentence and the gap is under 1.5 s. A lone backchannel
("yeah.") is left alone: it is as likely the other person's interjection, but a tag question ("right?")
goes back. A cut-off tail of at most 3 words starting lower-case and ending in "-" ("the-", "was on
the-", "coupling-") goes back the same way: the speaker was talked over mid-phrase.
After the reviewed speaker corrections: a "..." token (the transcriber's mark that a speaker resumes
after an interruption) goes with the words that follow it; a bare "." left after an audio event is
dropped; and a turn with no words, only audio events ("[laughs]"), joins a neighbouring turn.
Captions follow the website's download exactly (cues() and exportText() in site/web/index.html): a cue
ends at 14 words, at 6 s, or at a sentence end after 6 words, and never crosses a turn; SRT names the
speaker on a turn's first cue only.
--show-boundaries prints each moved fragment.
"""
import json
import re
import sys
from bisect import bisect_right

import common
from build_terms import terms_for
from common import NARRATOR, ROOT, SENTENCE_END, hms, norm_key, rel

OUT = ROOT / "out"
POSSESSIVE = re.compile(r"['’]s$")
# A lone one of these opening a turn is as likely the other person's interjection (step 5).
BACKCHANNEL = {"yeah", "yes", "yep", "no", "okay", "ok", "right", "sure", "mm-hmm", "uh-huh", "wow", "exactly"}
COLD_HEAD_S = 8         # the cold open's `detect` phrase is said within this many seconds of the start
NEAR_S = 10             # a text anchor's first word must start within this many seconds of its near_s
LEFTOVER_S = 120        # a `from` left uncorrected this close to a correction is printed as a warning
TURN_LEAD_S = 0.01      # a word starting this little before a voice turn already belongs to it
TURN_TAIL_S = 0.5       # a word starting up to this long after a voice turn's end still belongs to it
FRAGMENT_WORDS = 3      # boundary repair moves at most this many words back to the previous turn...
FRAGMENT_GAP_S = 1.5    # ...and only across a pause shorter than this
ELLIPSIS_GAP_S = 1.0    # a "..." goes with the next speaker's words when they follow within this many seconds
# Captions: the rules of cues() in site/web/index.html. Change both together.
CUE_WORDS = 14          # a cue ends at this many words,
CUE_S = 6               # or when its last word ends this many seconds after its first began,
CUE_SENTENCE_WORDS = 6  # or at a sentence end once it has this many words
CUE_MIN_S = 0.5         # and lasts at least this long on screen
CUE_END = re.compile(r"[.?!][\"”]?$")   # the site's sentence end for cues (narrower than SENTENCE_END)


class FixError(Exception):
    """A data/fixes entry that doesn't fit the transcript; main() names the file."""


def core(text):
    """(leading punctuation, the word, trailing punctuation)."""
    return re.match(r"^(\W*)(.*?)(\W*)$", text).groups()


def key_words(text):
    return [core(t)[1].lower() for t in text.split()]


def same_words(got, seq):
    """got (key words from the transcript) is seq; the last may carry a possessive 's that seq lacks."""
    return got[:-1] == seq[:-1] and (got[-1] == seq[-1] or POSSESSIVE.sub("", got[-1]) == seq[-1])


def text_of(ws):
    return " ".join(x["w"] + ("[?]" if x.get("u") else "") for x in ws)


def load_items(raw):
    """Words and audio events, in order, and the item index of each word. Indexes in fixes count words only,
    as flag.py does."""
    items, word_ix = [], []
    for w in raw["words"]:
        if w["type"] == "spacing":
            continue
        item = {"w": w["text"], "s": round(w["start"], 2), "e": round(w["end"], 2), "lp": round(w["logprob"], 3)}
        if w["type"] == "audio_event":
            item["x"] = 1
        else:
            word_ix.append(len(items))
        items.append(item)
    return items, word_ix


def check_fixes(n, fixes, word_ix, spk):
    """Raw word indexes must point at words, and speaker reviews at people the episode knows: the voiceprints,
    this episode's guests, the names the voice check gave, and any series guest (a cameo, like Noah Philip's
    clip after ep 13's outro)."""
    for f in fixes["fix"]:
        if not (0 <= f["i"] and 1 <= f["k"] and f["i"] + f["k"] <= len(word_ix)):
            raise FixError(f"fix {f}: words {f['i']}..{f['i'] + f['k'] - 1} are outside the {len(word_ix)} words")
    for u in fixes["uncertain"]:
        if "i" in u and not 0 <= u["i"] < len(word_ix):
            raise FixError(f"uncertain {u}: word {u['i']} is outside the {len(word_ix)} words")
    all_guests = common.guests()
    known = ({p.stem for p in (ROOT / "data" / "voiceprints").glob("*.npy")} | set(common.HOSTS) | {NARRATOR}
             | set(all_guests.get(str(n), [])) | {t["name"] for t in spk["turns"]}
             | {g for k, gs in all_guests.items() if k.isdigit() for g in gs})
    for o in fixes["speaker"]:
        if o["who"] not in known:
            raise FixError(f"speaker {o}: {o['who']!r} is not a known speaker (a host, a guest in data/guests.json, "
                           f"or {NARRATOR})")


def stale_names(n, spk):
    """Guest names in out/speakers/<NN>.json that data/guests.json doesn't give this episode, and the reverse:
    a guest added or respelt after name_speakers.py ran."""
    guests = set(common.guests().get(str(n), []))
    named = {t["name"] for t in spk["turns"]} - set(common.HOSTS) - {NARRATOR, "Merged hosts"}
    named = {x for x in named if not x.startswith("Unknown")}
    return sorted(named ^ guests)


def apply_term_fixes(items, word_ix, fixes, terms):
    """Step 1: swap a flagged span for a listed term, keeping punctuation and timings."""
    listed = set(terms)
    for f in fixes["fix"]:
        span = [items[word_ix[j]] for j in range(f["i"], f["i"] + f["k"])]
        got = " ".join(x["w"] for x in span)
        if not same_words(key_words(got), key_words(f["from"])):
            raise FixError(f"fix at word {f['i']} expects {f['from']!r}, transcript has {got!r}")
        if f["to"] not in listed:
            raise FixError(f"fix target {f['to']!r} is not a listed term (data/terms/)")
        new = f["to"].split()
        if len(new) == len(span):
            for x, word in zip(span, new):
                pre, mid, post = core(x["w"])
                if POSSESSIVE.search(mid) and not POSSESSIVE.search(word):
                    word += mid[-2:]  # keep a possessive: "Ellie Martin's" -> "Elly Martin's"
                x["w"] = pre + word + post
        else:
            pre, post = core(span[0]["w"])[0], core(span[-1]["w"])[2]
            span[0]["w"], span[0]["e"] = pre + f["to"] + post, span[-1]["e"]
            for x in span[1:]:
                x["drop"] = 1
        for x in span:
            x["fixed"] = 1


def respell_terms(items, word_ix, terms):
    """Step 2: listed names the model got right but cased or accented differently ("Sonomind" -> "SonoMind").
    Only terms whose spelling carries information: inner capitals, all-caps acronyms, or accents."""
    special = [t for t in terms if re.search(r"[a-z][A-Z]|^[A-Z0-9]{2,}$|[^\x00-\x7f]", t)]
    recased = 0
    words_only = [items[j] for j in word_ix]
    for t in special:
        tw, tn = t.split(), norm_key(t)
        for j in range(len(words_only) - len(tw) + 1):
            span = words_only[j:j + len(tw)]
            if any("fixed" in x for x in span) or norm_key(" ".join(x["w"] for x in span)) != tn:
                continue
            for x, word in zip(span, tw):
                pre, mid, post = core(x["w"])
                if mid != word:
                    x["w"], recased = pre + word + post, recased + 1
    return recased


def swap_cold_open(items):
    """Step 2b: the stock cold open is one recording (data/cold_open.json): its words and speakers are fixed.
    It is recognised by its `detect` phrase near the start and a word of its narration before its end."""
    cold = common.load_json(ROOT / "data" / "cold_open.json")
    head = " ".join(x["w"] for x in items if x["s"] < COLD_HEAD_S and "x" not in x).lower()
    found = (cold["detect"] in head
             and any(cold["detect_narration"] in x["w"].lower() for x in items if x["s"] < cold["end_s"]))
    if found:
        items[:] = [dict(x, lock=1) for x in cold["words"]] + [x for x in items if x["s"] >= cold["end_s"]]
    return found


def find_all(items, seq, events=False, near_s=None, within=None):
    """Every match of the word sequence seq (as lists of item indexes), optionally within `within` s of near_s.
    With events, audio-event tokens count too ("510 [k]", where the model heard "(k)" as an event)."""
    ws = [j for j, x in enumerate(items) if (events or "x" not in x) and "lock" not in x]
    hits = []
    for a in range(len(ws) - len(seq) + 1):
        if within is not None and abs(items[ws[a]]["s"] - near_s) > within:
            continue
        if same_words([core(items[ws[a + t]]["w"])[1].lower() for t in range(len(seq))], seq):
            hits.append([ws[a + t] for t in range(len(seq))])
    return hits


def find(items, text, near_s, what, events=False):
    """Indexes in items of the words of text nearest near_s (its first word within NEAR_S)."""
    hits = find_all(items, key_words(text), events, near_s, NEAR_S)
    if not hits:
        raise FixError(f"{what}: {text!r} not found within {NEAR_S} s of {near_s}")
    return min(hits, key=lambda h: abs(items[h[0]]["s"] - near_s))


def correct(items, r, span):
    """Make the words at span (item indexes) r["to"]."""
    old = [items[j] for j in span]
    was_event = [bool(x.pop("x", None)) for x in old]  # an event token that is really part of a word ("[k]")
    new = r["to"].split()
    poss = bool(POSSESSIVE.search(core(old[-1]["w"])[1])) and not POSSESSIVE.search(r["from"])
    prev = next((items[j]["w"] for j in range(span[0] - 1, -1, -1) if "x" not in items[j]), "")
    if core(old[0]["w"])[1][:1].isupper() and (not prev or SENTENCE_END.search(prev)) and new[0][:1].islower():
        new[0] = new[0][0].upper() + new[0][1:]  # a sentence's first word keeps its capital
    if len(new) == len(old):
        for x, word in zip(old, new):
            pre, mid, post = core(x["w"])
            x["w"] = pre + word + post
    else:
        s0, e1, lp = old[0]["s"], old[-1]["e"], min(x["lp"] for x in old)
        pre, post = core(old[0]["w"])[0], "" if was_event[-1] else core(old[-1]["w"])[2]
        total, at, made = sum(len(w) + 1 for w in new), s0, []
        for k, word in enumerate(new):
            end = e1 if k == len(new) - 1 else round(at + (e1 - s0) * (len(word) + 1) / total, 2)
            made.append({"w": (pre if k == 0 else "") + word + (post if k == len(new) - 1 else ""),
                         "s": round(at, 2), "e": end, "lp": lp})
            at = end
        items[span[0]:span[-1] + 1] = made
        old = made
    if poss:
        old[-1]["w"] = re.sub(r"^(.*?)(\W*)$", lambda m: m.group(1) + "'s" + m.group(2), old[-1]["w"], count=1)
    for x in old:
        x.pop("u", None)  # a reviewed correction is no longer the model's guess
        x["w"] = re.sub(r"([,;:])\1+", r"\1", x["w"])  # "Sree,," when `to` brings its own comma


def apply_replacements(items, fixes):
    """Step 3: word corrections by text anchor and time; then the text-anchored uncertain marks.
    Returns (corrections made, warnings about the same `from` left nearby)."""
    replaced = 0
    for r in fixes["replace"]:
        ev = "[" in r["from"]
        if r.get("all"):
            hits = find_all(items, key_words(r["from"]), ev)
            if not hits:
                raise FixError(f"replace (all): {r['from']!r} not found")
            for span in reversed(hits):  # from the end, so a change in word count doesn't shift later matches
                correct(items, r, span)
                replaced += 1
            continue
        correct(items, r, find(items, r["from"], r["near_s"], "replace", events=ev))
        replaced += 1
    leftovers = []
    for r in fixes["replace"]:
        seq, ev = key_words(r["from"]), "[" in r["from"]
        if not r.get("all") and key_words(r["to"]) != seq:
            for h in find_all(items, seq, ev, r["near_s"], LEFTOVER_S):
                leftovers.append(f"{r['from']!r} still at {items[h[0]]['s']:.1f} (corrected near {r['near_s']})")
    for u in fixes["uncertain"]:
        if "i" not in u:
            for j in find(items, u["text"], u["near_s"], "uncertain"):
                items[j]["u"] = 1
    return replaced, list(dict.fromkeys(leftovers))


def assign_speakers(items, spk, overrides):
    """Step 4: speaker per word, from the voice-checked turns; events take the previous word's speaker.
    Returns the speaker names that "p" indexes."""
    names = list(dict.fromkeys([t["name"] for t in spk["turns"]] + [o["who"] for o in overrides]
                               + [x["who"] for x in items if "who" in x]))
    starts = [t["start"] for t in spk["turns"]]
    last = 0
    for x in items:
        k = bisect_right(starts, x["s"] + TURN_LEAD_S) - 1
        if "who" in x:
            last = names.index(x.pop("who"))
        elif "x" not in x and k >= 0 and x["s"] <= spk["turns"][k]["end"] + TURN_TAIL_S:
            last = names.index(spk["turns"][k]["name"])
        x["p"] = last
        x.pop("fixed", None)
    return names


def make_turns(items):
    out = []
    for i, x in enumerate(items):
        if out and out[-1]["p"] == x["p"]:
            out[-1]["e"], out[-1]["w1"] = x["e"], i + 1
        else:
            out.append({"p": x["p"], "s": x["s"], "e": x["e"], "w0": i, "w1": i + 1})
    return out


def repair_boundaries(items):
    """Step 5: "suicidal thought." opening a turn ends the previous speaker's sentence. Returns the moved fragments."""
    moved = []
    for t in make_turns(items)[1:]:
        ws = [j for j in range(t["w0"], t["w1"]) if "x" not in items[j]]
        prev = [j for j in range(t["w0"] - 1, -1, -1) if "x" not in items[j]][:1]
        if not ws or not prev or SENTENCE_END.search(items[prev[0]]["w"]) or "lock" in items[prev[0]]:
            continue
        if not core(items[ws[0]]["w"])[1][:1].islower() or items[ws[0]]["s"] - items[prev[0]]["e"] > FRAGMENT_GAP_S:
            continue
        k = next((k for k in range(min(FRAGMENT_WORDS, len(ws)))
                  if SENTENCE_END.search(items[ws[k]]["w"]) or items[ws[k]]["w"].endswith("-")), None)
        if k is None or any(items[ws[m]]["w"].endswith("-") for m in range(k)):
            continue
        if k == 0 and core(items[ws[0]]["w"])[1].lower() in BACKCHANNEL and items[ws[0]]["w"].lower() != "right?":
            continue  # a lone "yeah." is as likely the other person's interjection; "right?" is a tag question
        w0 = core(items[ws[0]]["w"])[1].lower()
        if k == 0 and len(w0) <= 2 and len(ws) > 1 and core(items[ws[1]]["w"])[1].lower().startswith(w0):
            continue  # "s- so I think": the new speaker's own stutter
        p = items[prev[0]]["p"]
        for j in range(t["w0"], ws[k] + 1):  # events inside the fragment go with it
            items[j]["p"] = p
        moved.append(f"{items[ws[0]]['s']:.1f} {' '.join(items[j]['w'] for j in ws[:k + 1])}")
    return moved


def apply_speaker_reviews(items, overrides, names):
    """Step 6: reviewed speaker corrections (data/fixes "speaker"), last so they win. Returns words reassigned."""
    reassigned = 0
    for o in overrides:
        if "text" in o:
            span = find(items, o["text"], o["near_s"], "speaker")
            sel = range(span[0], span[-1] + 1)
        else:
            sel = [j for j, x in enumerate(items) if o["from_s"] <= x["s"] < o["to_s"]]
            if not sel:
                raise FixError(f"speaker: no words in [{o['from_s']}, {o['to_s']})")
        if any("lock" in items[j] for j in sel):
            raise FixError(f"speaker: {o} touches the fixed cold open")
        for j in sel:
            reassigned += items[j]["p"] != names.index(o["who"])
            items[j]["p"] = names.index(o["who"])
    return reassigned


def tidy(items, names):
    """Step 7: tidy-ups that would otherwise leave turns with nothing in them.
    Returns (items, names, the turns, "..." moved, event-only turns merged)."""
    # A bare "." after an audio event ("[chuckles] .") is a zero-length artefact.
    items = [x for x in items if not ("x" not in x and re.fullmatch(r"[.,;:]+", x["w"]) and x["w"] != "...")]
    # "..." marks a speaker resuming after an interruption: it goes with the words that follow.
    ellipses = 0
    for j, x in enumerate(items):
        if "x" in x or "lock" in x or x["w"] not in ("...", "…"):
            continue
        nxt = next((k for k in range(j + 1, len(items)) if "x" not in items[k] and core(items[k]["w"])[1]), None)
        if nxt is not None and items[nxt]["s"] - x["e"] < ELLIPSIS_GAP_S and items[nxt]["p"] != x["p"]:
            x["p"], ellipses = items[nxt]["p"], ellipses + 1
    # A turn of only audio events (and "..."): the laugh joins the turn around it, else the one before.
    merged = 0
    for t in make_turns(items):
        if any("x" not in items[j] and core(items[j]["w"])[1] for j in range(t["w0"], t["w1"])):
            continue
        if any("lock" in items[j] for j in range(t["w0"], t["w1"])):
            continue
        before = items[t["w0"] - 1]["p"] if t["w0"] > 0 else None
        after = items[t["w1"]]["p"] if t["w1"] < len(items) else None
        to = before if before is not None else after
        for j in range(t["w0"], t["w1"]):
            items[j]["p"] = to
        merged += 1
    for x in items:
        x.pop("lock", None)
    used = sorted({x["p"] for x in items})
    names = [names[p] for p in used]
    for x in items:
        x["p"] = used.index(x["p"])
    return items, names, make_turns(items), ellipses, merged


def cues(items, turns):
    """Caption cues as (turn, first cue of its turn, words), by the rules of cues() in site/web/index.html."""
    out = []
    for t in turns:
        a = t["w0"]
        for i in range(t["w0"], t["w1"]):
            k = i - a + 1
            if (i == t["w1"] - 1 or k >= CUE_WORDS or items[i]["e"] - items[a]["s"] >= CUE_S
                    or (k >= CUE_SENTENCE_WORDS and CUE_END.search(items[i]["w"]))):
                out.append((t, a == t["w0"], items[a:i + 1]))
                a = i + 1
    return out


def vtt_text(s):
    """VTT cue text is markup: a bare & or < would break it ("R&D", "<v"). Escaped as the site's exportText does."""
    return s.replace("&", "&amp;").replace("<", "&lt;")


def write_outputs(n, ep, raw, items, names, turns, edits):
    """The master file and its Markdown, VTT and SRT copies. Returns the number of caption cues."""
    master = {
        "n": n, "title": ep["title"], "date": ep["date"], "audio_url": ep["audio_url"],
        "duration_s": round(raw["audio_duration_secs"], 1), "speakers": names,
        "source": {"model": "scribe_v2", "raw": f"{n:02d}", "transcription_id": raw["transcription_id"]},
        "edits": edits, "words": items, "turns": turns,
    }
    for d in ("episodes", "text", "vtt", "srt"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    (OUT / "episodes" / f"{n:02d}.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")

    md = [f"# {ep['title']}", "", f"{ep['date']} · {', '.join(names)}", "",
          "Machine transcript (ElevenLabs scribe_v2). [?] marks words the model was unsure of.", ""]
    for t in turns:
        md.append(f"**[{hms(t['s'])[:8]}] {names[t['p']]}:** {text_of(items[t['w0']:t['w1']])}")
        md.append("")
    (OUT / "text" / f"{n:02d}.md").write_text("\n".join(md), encoding="utf-8")

    vtt, srt = [], []
    cs = cues(items, turns)
    for k, (t, first, ws) in enumerate(cs, 1):
        a, b = ws[0]["s"], max(ws[-1]["e"], ws[0]["s"] + CUE_MIN_S)
        who, words = names[t["p"]], " ".join(x["w"] for x in ws)
        vtt.append(f"{k}\n{hms(a)} --> {hms(b)}\n<v {vtt_text(who)}>{vtt_text(words)}")
        srt.append(f"{k}\n{hms(a, ',')} --> {hms(b, ',')}\n{who + ': ' if first else ''}{words}")
    # newline="\n": the same bytes on every system, as the site's download
    with open(OUT / "vtt" / f"{n:02d}.vtt", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("WEBVTT\n\n" + "\n\n".join(vtt) + "\n")
    with open(OUT / "srt" / f"{n:02d}.srt", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n\n".join(srt) + "\n")
    return len(cs)


def build(n, show_boundaries=False):
    """Episode n's master file and copies: the steps below, in order. A fixes entry that doesn't fit raises FixError."""
    ep = common.episode(n)
    raw = common.load_json(OUT / "raw" / f"{n:02d}.json")
    spk = common.load_json(OUT / "speakers" / f"{n:02d}.json")
    fixes = common.load_fixes(n)
    items, word_ix = load_items(raw)
    check_fixes(n, fixes, word_ix, spk)
    stale = stale_names(n, spk)
    if stale:
        print(f"WARNING: the guests in out/speakers/{n:02d}.json and data/guests.json differ ({', '.join(stale)}): "
              f"data/guests.json changed after name_speakers.py ran. Run python scripts/name_speakers.py {n}, "
              "then this again.")

    terms = terms_for(n)
    apply_term_fixes(items, word_ix, fixes, terms)
    recased = respell_terms(items, word_ix, terms)
    for u in fixes["uncertain"]:
        if "i" in u:
            items[word_ix[u["i"]]]["u"] = 1
    items = [x for x in items if "drop" not in x]
    cold_open = swap_cold_open(items)
    replaced, leftovers = apply_replacements(items, fixes)
    names = assign_speakers(items, spk, fixes["speaker"])
    boundaries = repair_boundaries(items)
    reassigned = apply_speaker_reviews(items, fixes["speaker"], names)
    items, names, turns, ellipses, merged = tidy(items, names)

    edits = {"fixes": len(fixes["fix"]), "replaced": replaced, "uncertain": len(fixes["uncertain"]),
             "boundaries_moved": len(boundaries), "speaker_words_reassigned": reassigned,
             "cold_open": cold_open, "ellipses_moved": ellipses, "event_turns_merged": merged}
    n_cues = write_outputs(n, ep, raw, items, names, turns, edits)
    print(f"ep {n}: {sum('x' not in x for x in items)} words, {len(turns)} turns, {n_cues} captions; "
          f"{len(fixes['fix'])} fixes, {replaced} replaced, {recased} re-spelled, {len(fixes['uncertain'])} uncertain; "
          f"{len(boundaries)} boundary fragments moved, {reassigned} words given to another speaker by review; "
          f"cold open {'fixed' if cold_open else 'not stock'}, {ellipses} '...' moved, {merged} event-only turns merged")
    for w in leftovers:
        print("  WARNING leftover:", w)
    if show_boundaries:
        print("\n".join("  " + b for b in boundaries))


def main():
    ap = common.parser(__doc__)
    ap.add_argument("--show-boundaries", action="store_true", help="print each moved boundary fragment")
    args = ap.parse_args()
    try:
        build(args.n, args.show_boundaries)
    except FixError as e:
        sys.exit(f"{rel(common.fixes_path(args.n))}: {e}")


if __name__ == "__main__":
    main()
