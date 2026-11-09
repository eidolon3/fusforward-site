"""Name the speakers by voice, and re-check every speaker turn against those voices.

Run:  python scripts/name_speakers.py 16
      python scripts/name_speakers.py 16 --enroll "Charles Caskey=speaker_1" "Keith Murphy=speaker_2"
--enroll saves those ElevenLabs speakers' voices as host voiceprints (data/voiceprints/); do it once.
Needs ffmpeg and the episode's audio in audio/ (fetch_feed.py), but only for spans not embedded yet:
embeddings are cached in out/speakers/<NN>_emb2.npz.

Each ElevenLabs label is named by its closest host voiceprint; labels that match no host are
the guests (data/guests.json, longest talker first). Then every turn, and every sentence of a long
turn, is compared with all the voices in the episode (hosts, guests, the intro narrator) and moved
when it clearly sounds like someone else. This repairs runs where diarization merged people under
one label, including a guest under a label named as a host. Any voice can take any turn:
  - a turn of 3 s or more moves when another voice beats its label's by MARGIN;
  - a turn or sentence of 1-3 s moves only on stronger evidence (SHORT_MARGIN, and the new voice
    must itself match well), and a stronger one again between the two hosts, whose voices are
    closer to each other than to any guest (HOST_MARGIN), so short turns don't flap on noise;
    a host turn that hardly matches its own host at all (HOST_OWN) moves to the other host on a
    smaller margin (HOST_MARGIN2/HOST_BEST2): "CC 0.45 vs KM 0.10" is not a tie;
  - a turn of 0.8-1 s (EMB_MIN) is judged too, on the strictest evidence (TINY_*);
  - then runs of short turns that will show as one turn (consecutive turns given the same name, none
    of them 3 s long) are judged once more as a whole, since each piece alone is often too short to
    embed ("I was gonna ask you about L-STEM" = three pieces under 1 s each).
Output: out/speakers/<NN>.json. Each turn carries "sim" (similarity to the voice it was given),
"alt"/"alt_sim" (the closest other voice) and "low": 1 when sim < LOW_SIM, for review (report.py lists
them); "how" says why a turn's name differs from its label's ("voice", "sandwich", "intro text", "merged").
"""
import json
import shutil
import subprocess
import sys
from collections import Counter

import numpy as np

import common
from common import AUDIO, HOSTS, LOW_SIM, NARRATOR, ROOT, SENTENCE_END, rel

VP = ROOT / "data" / "voiceprints"
OUT = ROOT / "out" / "speakers"
# The SpeechBrain model, pinned to the Hugging Face commit the voiceprints and caches were made with.
ECAPA = "speechbrain/spkrec-ecapa-voxceleb"
ECAPA_REVISION = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
SR = 16000
TURN_GAP = 0.5      # seconds; a pause this long starts a new turn even under the same label
MATCH = 0.45        # cosine similarity for a label to count as a host
SPLIT = 0.60        # a second label this close to one host (and not the other) is that host, split in two
MIN_SEG = 1.0       # seconds; shorter turns ("yeah", "mm-hmm") don't go into anyone's voice...
EMB_MIN = 0.8       # ...but turns from this long are judged, on the TINY_* evidence
MIN_MOVE = 3.0      # a turn this long moves on its own...
AS_SHORT = MIN_MOVE - 0.01  # a sentence or a run is judged as a short turn, whatever its length
MARGIN = 0.10       # ...if another voice beats its label's by this
SHORT_MARGIN = 0.15  # a 1-3 s turn or sentence needs this margin...
SHORT_BEST = 0.35    # ...and the new voice must match it at least this well
HOST_MARGIN = 0.25   # between the two hosts, a 1-3 s turn needs this margin
HOST_BEST = 0.50     # ...and this match,
HOST_OWN = 0.30      # unless it barely sounds like its own host: then
HOST_MARGIN2 = 0.20  # this margin
HOST_BEST2 = 0.35    # and this match are enough
TINY_MARGIN = 0.25   # a 0.8-1 s turn moves only on this margin,
TINY_BEST = 0.40     # this match,
TINY_OWN = 0.25      # and a poor match to its own voice
GUEST_OWN = 0.40     # a guest's voice is rebuilt from long turns that match it at least this well...
GUEST_TURNS = 5      # ...once it has this many
CHECK_PASSES = 2     # assign turns, rebuild the guests' voices, and assign again
SANDWICH_GAP = 1.0   # seconds; a short turn this close to the same speaker on both sides joins them
RUN_MAX = 10.0       # seconds; runs of short turns judged as a whole are at most this long
# Seconds: the stock narrator speaks only in the cold open, so no later turn is theirs, and an earlier turn
# carrying the intro's words is.
NARRATOR_UNTIL = 120
INTRO_PHRASES = ("caskey and keith murphy", "next frontier of ultrasound")
PIECE_MIN_TURN = 4.0  # turns this long are also checked sentence by sentence


def unit(v):
    norm = np.linalg.norm(v)
    return v / norm if norm else v  # an all-zero vector (silence) stays zero rather than NaN


def key(a, b):
    return f"{a:.2f}-{b:.2f}"


def dur(s):
    return s["end"] - s["start"]


def voice(seg_list):
    """A voice from turns of MIN_SEG or more (0.8-1 s turns are judged, but too short to build on)."""
    embs = [s["emb"] * dur(s) for s in seg_list if "emb" in s and dur(s) >= MIN_SEG]
    return unit(np.sum(embs, axis=0)) if embs else None


class Embeddings:
    """Voice embeddings of time spans, cached in out/speakers/<NN>_emb2.npz: they only depend on the audio.
    The audio and the model load on first use, so a fully cached episode needs neither."""

    def __init__(self, n, ep):
        self.n, self.ep = n, ep
        self.path = OUT / f"{n:02d}_emb2.npz"
        self.cache, self.enc, self.wave = {}, None, None
        if self.path.exists():
            c = np.load(self.path)
            self.cache = dict(zip(c["keys"].tolist(), c["emb"]))

    def __getitem__(self, span):
        return self.cache[key(*span)]

    def ensure(self, spans):
        """Embed the spans not cached yet, and save the cache."""
        todo = [sp for sp in dict.fromkeys(spans) if key(*sp) not in self.cache]
        if not todo:
            return
        if self.wave is None:
            self.wave = self.load_audio()
        import torch
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import FetchConfig, LocalStrategy
        if self.enc is None:
            self.enc = EncoderClassifier.from_hparams(
                source=ECAPA, savedir=str(ROOT / "models" / "ecapa"), fetch_config=FetchConfig(revision=ECAPA_REVISION),
                run_opts={"device": "cuda" if torch.cuda.is_available() else "cpu"}, local_strategy=LocalStrategy.COPY)
        with torch.no_grad():
            for a, b in todo:
                x = torch.from_numpy(self.wave[int(a * SR):int(b * SR)].copy()).unsqueeze(0)
                self.cache[key(a, b)] = unit(self.enc.encode_batch(x).squeeze().cpu().numpy())
        np.savez(self.path, keys=np.array(list(self.cache)), emb=np.stack(list(self.cache.values())))
        print(f"embedded {len(todo)} new spans")

    def load_audio(self):
        audio = AUDIO / self.ep["audio_file"]
        if not audio.exists():
            sys.exit(f"{rel(audio)} is missing (needed for spans not in {rel(self.path)} yet): "
                     f"run python scripts/fetch_feed.py {self.n}")
        if not shutil.which("ffmpeg"):
            sys.exit("ffmpeg is not on PATH: install it (https://ffmpeg.org) to decode the audio")
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                           capture_output=True)
        if r.returncode:
            sys.exit(f"ffmpeg failed on {rel(audio)}:\n{r.stderr.decode('utf-8', 'replace')}")
        return np.frombuffer(r.stdout, dtype=np.float32)


def make_turns(words):
    """Turns: break on label change or a pause of TURN_GAP or more."""
    segs = []
    for k, w in enumerate(words):
        if segs and segs[-1]["label"] == w["speaker_id"] and w["start"] - segs[-1]["end"] < TURN_GAP:
            segs[-1]["end"], segs[-1]["w1"] = w["end"], k + 1
        else:
            segs.append({"start": w["start"], "end": w["end"], "label": w["speaker_id"], "w0": k, "w1": k + 1})
    return segs


def make_pieces(segs, words):
    """Long turns cut at sentence ends into pieces of at least MIN_SEG (shorter sentences join the next one),
    so a host question inside a guest's long answer can be found. [(turn index, w0, w1)]"""
    pieces = []
    for si, s in enumerate(segs):
        if dur(s) < PIECE_MIN_TURN:
            continue
        cuts, a = [], s["w0"]
        for k in range(s["w0"], s["w1"]):
            if SENTENCE_END.search(words[k]["text"]) and k + 1 < s["w1"]:
                if words[k]["end"] - words[a]["start"] >= MIN_SEG and words[s["w1"] - 1]["end"] - words[k + 1]["start"] >= MIN_SEG:
                    cuts.append((a, k + 1))
                    a = k + 1
        if cuts:
            cuts.append((a, s["w1"]))
            if words[cuts[-1][1] - 1]["end"] - words[cuts[-1][0]]["start"] < MIN_SEG:
                cuts[-2:] = [(cuts[-2][0], cuts[-1][1])]
            if len(cuts) > 1:
                pieces += [(si, a, b) for a, b in cuts]
    return pieces


def name_labels(labels, label_voice, prints, talk, guests):
    """Name each label. Returns (names {label: name}, the merged labels, similarity {label: {voiceprint: sim}})."""
    sim = {l: {h: float(label_voice[l] @ hv) for h, hv in prints.items()} for l in labels if label_voice[l] is not None}
    # Closest host first, greedily, so two labels can't take one host...
    names = {}
    for l, h, s in sorted(((l, h, s) for l, d in sim.items() for h, s in d.items()), key=lambda x: -x[2]):
        if s >= MATCH and l not in names and h not in names.values():
            names[l] = h
    # A leftover label that sounds like both hosts is the two of them merged (ep 12), often with the
    # guest too: its turns are given to the closest voice later rather than named as a guest.
    merged = {l for l, d in sim.items() if l not in names and sum(v >= MATCH for v in d.values()) >= 2}
    # ...then labels ElevenLabs split off from one host (ep 10, 14). Guest turns mixed into them are
    # moved out by the turn check.
    for l, d in sim.items():
        if l not in names and l not in merged and d and max(d.values()) >= SPLIT:
            names[l] = max(d, key=d.get)
    # ...then the rest are guests by talk time. Labels too short to have a voice stay unknown.
    rest = [l for l in sorted(labels, key=lambda l: -talk[l])
            if l not in names and l not in merged and label_voice[l] is not None]
    for i, l in enumerate(rest):
        names[l] = guests[i] if i < len(guests) else f"Unknown {i + 1 - len(guests)}"
    for l in labels:
        names.setdefault(l, "Merged hosts" if l in merged else "Unknown")
    return names, merged, sim


def episode_voices(segs, names, merged, label_voice, prints):
    """Voices to check turns against: every voiceprint (even one no label matched, since a merged label can
    hide a host entirely), plus each guest's voice built only from turns that don't sound like a host
    (a merged label would otherwise blend two people)."""
    voices = dict(prints)
    for l, name in names.items():
        if name not in prints and l not in merged and label_voice[l] is not None:
            pure = [s for s in segs if s["label"] == l and "emb" in s and dur(s) >= MIN_SEG
                    and max((float(s["emb"] @ hv) for hv in prints.values()), default=0) < MATCH]
            voices[name] = voice(pure) if pure else label_voice[l]
    return voices


class Judge:
    """Which voice a span should carry, given the episode's voices (which check_turns updates)."""

    def __init__(self, voices, hosts):
        self.voices, self.hosts = voices, hosts

    def __call__(self, emb, cur, span_s, t):
        """(name, scores) for a span of span_s seconds starting at t, now named cur."""
        scores = {v: float(emb @ vv) for v, vv in self.voices.items() if v != NARRATOR or t < NARRATOR_UNTIL}
        if cur not in scores:  # "Merged hosts", or the narrator after the cold open: closest voice
            return max(scores, key=scores.get), scores
        best = max(scores, key=scores.get)
        gain = scores[best] - scores[cur]
        if best == cur:
            return cur, scores
        if span_s >= MIN_MOVE:
            return (best if gain >= MARGIN else cur), scores
        if span_s < MIN_SEG:
            ok = gain >= TINY_MARGIN and scores[best] >= TINY_BEST and scores[cur] < TINY_OWN
            return (best if ok else cur), scores
        if cur in self.hosts and best in self.hosts:
            ok = (gain >= HOST_MARGIN and scores[best] >= HOST_BEST
                  or scores[cur] < HOST_OWN and gain >= HOST_MARGIN2 and scores[best] >= HOST_BEST2)
            return (best if ok else cur), scores
        return (best if gain >= SHORT_MARGIN and scores[best] >= SHORT_BEST else cur), scores


def check_turns(segs, names, merged, sim, prints, judge):
    """Assign every turn; then rebuild each guest's voice from the long turns it now has (CHECK_PASSES times).
    Merged-label turns too short to judge take the voice of the nearest judged turn under that label."""
    voices = judge.voices
    for _ in range(CHECK_PASSES):
        for s in segs:
            s["name"], s["how"] = names[s["label"]], None
            if "emb" in s:
                new, s["scores"] = judge(s["emb"], s["name"], dur(s), s["start"])
                if new != s["name"]:
                    s["name"], s["how"] = new, "merged" if s["label"] in merged else "voice"
        for name in voices:
            if name in prints:
                continue
            own = [s for s in segs if s["name"] == name and "emb" in s and dur(s) >= MIN_MOVE
                   and s["scores"][name] >= GUEST_OWN]
            if len(own) >= GUEST_TURNS:
                voices[name] = voice(own)
    for s in segs:
        if s["label"] in merged and "emb" not in s:
            near = [x for x in segs if x["label"] == s["label"] and "emb" in x]
            if near:
                s["name"] = min(near, key=lambda x: abs(x["start"] - s["start"]))["name"]
            else:
                s["name"] = max(sim[s["label"]], key=sim[s["label"]].get)
            s["how"] = "merged"


def check_pieces(segs, pieces, words, emb, judge):
    """Sentences of long turns: a sentence that clearly sounds like someone else becomes its own turn.
    Returns the new turn list."""
    by_seg = {}
    for si, a, b in pieces:
        by_seg.setdefault(si, []).append((a, b))
    out = []
    for si, s in enumerate(segs):
        if si not in by_seg:
            out.append(s)
            continue
        for a, b in by_seg[si]:
            p = dict(s, start=words[a]["start"], end=words[b - 1]["end"], w0=a, w1=b)
            p["emb"] = emb[(p["start"], p["end"])]
            new, p["scores"] = judge(p["emb"], s["name"], min(dur(p), AS_SHORT), p["start"])
            if new != s["name"]:
                p["name"], p["how"] = new, "voice (sentence)"
            out.append(p)
    return out


def intro_text(segs, words):
    """The show's intro is one fixed recording ("Follow Charles Caskey and Keith Murphy as they explore the next
    frontier..."). Early turns carrying its words are the narrator even when they're too short or too
    overlapped to judge by voice (ep 3)."""
    for s in segs:
        if s["start"] < NARRATOR_UNTIL:
            text = " ".join(w["text"] for w in words[s["w0"]:s["w1"]]).lower()
            if any(p in text for p in INTRO_PHRASES) and s["name"] != NARRATOR:
                s["name"], s["how"] = NARRATOR, "intro text"


def sandwiches(segs):
    """Short turns sandwiched between two turns of one other speaker, under the same label, join them,
    unless the voice check moved them on its own evidence."""
    for k in range(1, len(segs) - 1):
        a, s, b = segs[k - 1], segs[k], segs[k + 1]
        if (dur(s) < MIN_MOVE and a["name"] == b["name"] != s["name"] and not (s.get("how") or "").startswith("voice")
                and a["label"] == s["label"] == b["label"]
                and s["start"] - a["end"] < SANDWICH_GAP and b["start"] - s["end"] < SANDWICH_GAP):
            s["name"], s["how"] = a["name"], "sandwich"


def repair_runs(segs, emb, judge):
    """Runs of short turns that will show as one turn: consecutive turns given the same name, none of them
    MIN_MOVE long, judged once more as a whole (first word of the run to the last), since that is the turn a
    reader sees."""
    runs, k = [], 0
    while k < len(segs):
        j = k
        while j + 1 < len(segs) and segs[j + 1]["name"] == segs[k]["name"]:
            j += 1
        runs.append((k, j + 1))
        k = j + 1
    judged = []
    for a, b in runs:
        grp = segs[a:b]
        span = grp[-1]["end"] - grp[0]["start"]
        if (b - a >= 2 and EMB_MIN <= span <= RUN_MAX and grp[0]["name"] != NARRATOR
                and all(dur(s) < MIN_MOVE for s in grp)):
            judged.append((a, b, (grp[0]["start"], grp[-1]["end"])))
    emb.ensure(sp for _, _, sp in judged)
    for a, b, sp in judged:
        grp = segs[a:b]
        new, sc = judge(emb[sp], grp[0]["name"], min(sp[1] - sp[0], AS_SHORT), sp[0])
        if new != grp[0]["name"]:
            for s in grp:
                s["name"], s["how"], s["scores"] = new, "voice (run)", sc
                s.setdefault("emb", emb[sp])


def write(n, segs, names, sim, voices, talk, labels):
    """out/speakers/<NN>.json, and a summary on screen."""
    moved = Counter()
    for s in segs:
        if s["name"] != names[s["label"]]:
            moved[(names[s["label"]], s["name"])] += 1
        if "scores" in s:
            sc = s["scores"]
            s["sim"] = round(sc.get(s["name"], float(s["emb"] @ voices[s["name"]]) if s["name"] in voices else 0), 3)
            others = {v: x for v, x in sc.items() if v != s["name"]}
            if others:
                alt = max(others, key=others.get)
                s["alt"], s["alt_sim"] = alt, round(others[alt], 3)
            if s["sim"] < LOW_SIM:
                s["low"] = 1
    talk_named = Counter()
    for s in segs:
        talk_named[s["name"]] += dur(s)
    result = {
        "raw": f"{n:02d}",
        "label_names": names,
        "label_similarity": sim,
        "turns_moved": {f"{a} -> {b}": c for (a, b), c in moved.items()},
        "talk_min": {k: round(v / 60, 1) for k, v in talk_named.most_common()},
        "low_turns": sum(1 for s in segs if s.get("low")),
        "turns": [{k: s[k] for k in ("start", "end", "label", "name", "sim", "alt", "alt_sim", "low", "how") if s.get(k) is not None}
                  for s in segs],
    }
    (OUT / f"{n:02d}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print("labels:", {l: f"{names[l]} ({talk[l] / 60:.1f} min)" for l in labels})
    print("label vs host similarity:", {l: {h: round(v, 2) for h, v in d.items()} for l, d in sim.items()})
    print("turns moved:", result["turns_moved"] or "none")
    print("talk time:", result["talk_min"], "| low-similarity turns:", result["low_turns"])


def main():
    ap = common.parser(__doc__)
    ap.add_argument("--enroll", nargs="+", default=[], metavar="NAME=LABEL",
                    help='save a label\'s voice as a host voiceprint, e.g. "Charles Caskey=speaker_1"')
    args = ap.parse_args()
    n = args.n
    enroll = {}
    for a in args.enroll:
        name, eq, label = (x.strip() for x in a.partition("="))
        if not (name and eq and label):
            ap.error(f"--enroll takes NAME=LABEL, not {a!r}")
        enroll[name] = label
    ep = common.episode(n)
    all_guests = common.guests()
    if str(n) not in all_guests:
        sys.exit(f"add episode {n} to data/guests.json (an empty list if it has no guests)")
    words = [w for w in common.load_json(ROOT / "out" / "raw" / f"{n:02d}.json")["words"] if w["type"] == "word"]
    VP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    segs = make_turns(words)
    pieces = make_pieces(segs, words)
    emb = Embeddings(n, ep)
    emb.ensure([(s["start"], s["end"]) for s in segs if dur(s) >= EMB_MIN]
               + [(words[a]["start"], words[b - 1]["end"]) for _, a, b in pieces])
    for s in segs:
        if dur(s) >= EMB_MIN:
            s["emb"] = emb[(s["start"], s["end"])]

    labels = sorted({s["label"] for s in segs})
    talk = Counter()
    for s in segs:
        talk[s["label"]] += dur(s)
    label_voice = {l: voice([s for s in segs if s["label"] == l]) for l in labels}
    for name, label in enroll.items():
        if label_voice.get(label) is None:
            sys.exit(f"--enroll {name}={label}: no voice for {label!r} (labels with one: "
                     f"{', '.join(l for l in labels if label_voice[l] is not None)})")
        np.save(VP / f"{name}.npy", label_voice[label])
        print(f"enrolled {name} from {label}")

    prints = {p.stem: np.load(p) for p in VP.glob("*.npy")}
    names, merged, sim = name_labels(labels, label_voice, prints, talk, all_guests[str(n)])
    judge = Judge(episode_voices(segs, names, merged, label_voice, prints), set(HOSTS) & set(prints))
    check_turns(segs, names, merged, sim, prints, judge)
    segs = check_pieces(segs, pieces, words, emb, judge)
    intro_text(segs, words)
    sandwiches(segs)
    repair_runs(segs, emb, judge)
    write(n, segs, names, sim, judge.voices, talk, labels)


if __name__ == "__main__":
    main()
