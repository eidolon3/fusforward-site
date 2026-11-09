"""The papers, tools and companies mentioned on the show, each tied to the moments it comes up: site/data/mentions.js.
The episode pages read it for their Show Notes (the papers discussed) and the notes in the transcript's margin.

Run:  python scripts/build_mentions.py               -> site/data/mentions.js
      python scripts/build_mentions.py --candidates  -> print paper candidates to review

Papers, in two steps:
  1. Candidates (--candidates): every place a speaker refers to a study ("we published", "the paper", "a paper in",
     "that study", "preprint"...) is scored against every PubMed title in data/pubmed/*.txt (the guests' records
     from fetch_pubmed.py, and mentioned.txt) by the rare title words (wordfreq Zipf < 4.3) that also occur within
     ~180 words around it, weighted by rarity.
  2. VERIFIED below: the candidates (and a few found by searching for a title's key words) that were checked by
     reading the transcript around them. Only these are written. Each one names the PMID, the episode and a phrase
     that is located in the transcript to get the exact second and the speaker. If a phrase is missing the build
     stops, so a re-transcription cannot silently shift a moment. Every VERIFIED paper's MEDLINE record must be in
     data/pubmed/mentioned.txt; the build reads no other PubMed file.
Tools and companies: the TOOLS and COMPANIES lists below, each name matched by its regular expression across every
transcript in out/episodes/; hits within 45 s of each other in an episode count as one moment.

Output: window.FF_MENTIONS = {papers: [{id, title, authors, n_authors, year, journal, preprint, doi, url, pubmed,
                                        moments: [{ep, t, who, quote}]}],
                              tools: [{name, desc, url, moments: [{ep, t}]}], companies: (as tools)}
"""
import argparse
import bisect
import re
import sys
from functools import cache

from wordfreq import zipf_frequency

import common
from build_site_data import DEFS, write_js
from common import FOLD_MAX, ROOT, SENTENCE_END, load_json, rel

OUT = ROOT / "site" / "data" / "mentions.js"
PUBMED_DIR = ROOT / "data" / "pubmed"
MENTIONED = PUBMED_DIR / "mentioned.txt"


# ---------------------------------------------------------------- transcripts
@cache
def transcripts():
    """{episode: {words, speakers, text (the words joined by spaces), starts (each word's offset in text)}}."""
    eps, hidden = {}, common.hidden()   # a hidden episode (data/hidden.json) is not on the site, so no mention points into it
    for f in sorted((ROOT / "out" / "episodes").glob("*.json")):
        if f.stem.isdigit() and int(f.stem) in hidden:
            continue
        d = load_json(f)
        starts, pos = [], 0
        for w in d["words"]:
            starts.append(pos)
            pos += len(w["w"]) + 1
        eps[d["n"]] = {"words": d["words"], "speakers": d["speakers"], "text": " ".join(w["w"] for w in d["words"]),
                       "starts": starts}
    return eps


def norm(s):
    return " ".join(t.strip("-'") for t in re.sub(r"[^\w\s'-]", "", s.lower()).split())


def locate(ep, phrase):
    """First word index where `phrase` starts (punctuation and case ignored)."""
    want = norm(phrase).split()
    low = [norm(w["w"]) for w in transcripts()[ep]["words"]]
    for i in range(len(low) - len(want) + 1):
        if low[i:i + len(want)] == want:
            return i
    sys.exit(f"phrase not found in ep {ep}: {phrase!r}")


def quote_at(ep, i, cap=34):
    """A short quote in the speaker's own words: from word i (after "…" when the speaker's previous word does not end a
    sentence) to the first sentence end at least 8 words on, or the end of the turn, or `cap` words.
    Short interjections by others (FOLD_MAX words or fewer), sound tags and "uh"/"um" are left out."""
    ws = transcripts()[ep]["words"]
    p = ws[i]["p"]

    def run(j):  # length of the other-speaker run starting at j
        n = 0
        while j < len(ws) and ws[j]["p"] != p:
            n, j = n + 1, j + 1
        return n

    prev = next((w for w in reversed(ws[max(0, i - 6):i]) if w["p"] == p), None)
    out = ["…"] if prev is not None and not SENTENCE_END.search(prev["w"]) else []
    past, j = 0, i
    while j < len(ws):
        w = ws[j]
        if w["p"] != p:
            r = run(j)
            if r > FOLD_MAX:
                break
            j += r
            continue
        j += 1
        if w["w"].startswith("[") or re.fullmatch(r"(uh|um)[,.-]*", w["w"], re.I):
            continue
        out.append(w["w"])
        past += 1
        if past >= 8 and SENTENCE_END.search(w["w"]):
            break
        if len(out) >= cap:
            out[-1] = out[-1].rstrip(",;:-") + "…"
            break
    q = " ".join(out)
    q = re.sub(r"\s*\.\.\.\s*", " ", q)
    q = re.sub(r"(?<![\w-])(\w{1,4})-+ (?=\w)", "", q)  # drop false starts like "neu- neuromodulation"
    for _ in range(2):
        q = re.sub(r"\b(\w+), \1\b", r"\1", q)  # "the, the" -> "the"
    q = q.replace("… ", "…").strip()
    if not q:  # only fillers and sound tags before the turn ends
        return ""
    if q.startswith("…") and q[1:2].isupper():
        q = q[1:]  # it starts a sentence after all
    return q[0].upper() + q[1:] if q[0] != "…" else q


def moment(ep, i, q):
    e = transcripts()[ep]
    w = e["words"][i]
    return {"ep": ep, "t": round(w["s"], 2), "who": e["speakers"][w["p"]], "quote": q}


# ---------------------------------------------------------------- PubMed
def medline(path):
    """The records of a MEDLINE-format file (blank-line separated) as [{field tag: [values]}]."""
    recs, cur, key = [], {}, None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            if cur:
                recs.append(cur)
            cur, key = {}, None
            continue
        if line[:4].strip() and line[4:6] == "- ":
            key = line[:4].strip()
            cur.setdefault(key, []).append(line[6:].strip())
        elif key:
            cur[key][-1] += " " + line.strip()
    if cur:
        recs.append(cur)
    return recs


def pubmed(paths):
    """{PMID: record} for the titled records in paths; the first file holding a PMID wins."""
    recs = {}
    for f in paths:
        for r in medline(f):
            if "PMID" in r and "TI" in r:
                recs.setdefault(r["PMID"][0], r)
    return recs


STOP = set("using with from that this were their which into between during after within among based study "
           "effects effect human humans".split())


def distinctive(s):
    return {t for t in re.findall(r"[a-z][a-z0-9\-]+", s.lower())
            if len(t) > 3 and t not in STOP and zipf_frequency(t, "en") < 4.3}


CUE = re.compile(r"\b(paper|papers|study|studies|published|publish|preprint|journal|we showed|we found|"
                 r"our work|article|publication)\b", re.I)


def candidates(min_score=5.0):
    titles = [(pmid, r, distinctive(" ".join(r["TI"]))) for pmid, r in pubmed(sorted(PUBMED_DIR.glob("*.txt"))).items()]
    for ep, e in transcripts().items():
        low = [norm(w["w"]) for w in e["words"]]
        last = -999
        for m in CUE.finditer(e["text"]):
            i = bisect.bisect_right(e["starts"], m.start()) - 1
            if i - last < 40:
                continue
            win = set(low[max(0, i - 70): i + 110])
            scored = sorted(((sum(5.5 - zipf_frequency(t, "en") for t in k & win), sorted(k & win), p, r)
                             for p, r, k in titles), key=lambda x: -x[0])
            if scored[0][0] < min_score:
                continue
            last = i
            w = e["words"][i]
            print(f"\nEp {ep} {w['s']:.0f}s {e['speakers'][w['p']]} [{m.group(0)}]")
            for sc, kw, p, r in scored[:3]:
                print(f"  {sc:5.1f} {kw} PMID {p}: {r['TI'][0][:110]}")
            print("  ", " ".join(x["w"] for x in e["words"][max(0, i - 30): i + 55]))


# Checked by reading the transcript around each moment. (pmid, [(episode, phrase located in the transcript)], note);
# the note records why the match holds, for whoever checks it next, and is not shown on the site.
# Each PMID's MEDLINE record is in data/pubmed/mentioned.txt.
VERIFIED = [
    ("41072763", [(1, "the acceptance of the ITRUSST consensus on non-significant risk")],
     "Charles names the ITRUSST safety consensus 'now published in Brain Stimulation'."),
    ("41309575", [(3, "one thing that, uh, is true in that study is that we purposefully activated the nucleus accumbens")],
     "Elsa on her nucleus accumbens study."),
    ("42106337", [(3, "But we've done this in another study")],
     "Loose reference: Elsa: 'another study' targeting the dorsal anterior cingulate during rest, pain and recovery from pain."),
    ("39190585", [(3, "who wrote this really, really important paper in eLife")],
     "Elsa's FUS win: Ben Kop's 2024 eLife paper on the auditory confound."),
    ("41338480", [(4, "there were two follow-up letters from Elsa Fouragnan and Kim Butts Pauly")],
     "Keith on the published responses to the serious adverse event report."),
    ("41317895", [(4, "as the ITRUSST open letter was developed")],
     "Keith on the ITRUSST open letter after the adverse event."),
    ("41214344", [(5, "can it also do that second part"), (5, "also in the paper, which we")],
     "Raag: 'that's what this last paper was about' - ultrasound clearing blood debris in hemorrhagic stroke models."),
    ("31230462", [(6, "the study Keith's talking about is a study where we took veterans")],
     "Noah on the first randomised trial of theta burst TMS for PTSD."),
    ("42780377", [(6, "So we got a cooperative kinda first in human study")],
     "Noah: first-in-human study, depression and anxiety, amygdala vs. somatosensory cortex control."),
    ("38670224", [(7, "Can it just be the list of parameters that we put in that paper?")],
     "Elly (first author) on the ITRUSST reporting standard."),
    ("41207505", [(10, "That was a really, uh, kind of flagship study from Sam's group this past year")],
     "Charles introduces Sam's essential tremor study."),
    ("35984788", [(10, "Actually, in BabelBrain, we're using Maria's, Maria's papers")],
     "Loose reference: Keith and Sam on Maria Miscouridou's MR-to-pseudo-CT mapping."),
    ("20547127", [(11, "And the paper, this is important")],
     "Keith reads the title: the paper with the first double PRF."),
    ("24413698", [(11, "they published this one")],
     "Charles: Legon et al. 2014, the much-cited human study."),
    ("21886108", [(11, "a Nature Protocols paper was written on the back of this in mice")],
     "Charles: the protocol paper that spread the parameters."),
    ("38253533", [(12, "you were using your technology to image the hippocampus")],
     "Keith asks Pengfei about his Alzheimer's mouse ULM paper."),
    ("36050189", [(14, "how does that paper square with the benchmarking paper")],
     "Charles on the simulation benchmark by Aubry, Pichardo, Treeby and others."),
    ("36549480", [(14, "Jean-François' worst case scenario. I loved that paper"), (16, "the three-layer model that we")],
     "The three-layer skull transmission model (Attali, Aubry et al.)."),
    ("17139734", [(16, "even the, the, the twin arrays on each side of the, of the head")],
     "Loose reference: Jean-François on dual-array transcranial focusing and transfer matrices."),
    ("41926919", [(17, "It was just published in"), (17, "we did find that after amygdala ultrasound, that GABA was increased")],
     "Miriam's Neuron paper on amygdala ultrasound."),
    ("41720796", [(19, "The other was more fundamental in, in choice behavior for saccades")],
     "Lennart on the frontal eye fields study."),
    ("41880511", [(19, "One was in the context of threat learning and extinction")],
     "Lennart on the amygdala threat learning study."),
    ("31707258", [(20, "I have another paper that is about Piezo1")],
     "Zhihai: his Piezo1 paper in iScience."),
    ("41853842", [(20, "surgically make the mice deaf")],
     "Zhihai on ultrasound and visual cortex in deafened mice."),
    ("39700626", [(22, "Elly Martin and I had this long-running paper")],
     "Brad on the years-long model vs. experiment comparison through skull."),
    ("37256814", [(22, "you guys have that paper on this")],
     "OpenUST, Morgan Roberts' open-source ring array."),
    ("41870476", [(16, "you propose also different ways to estimate the transmission"), (16, "first off, thank you very much")],
     "JF on Charles's paper (first author Cooper Donovan) testing the through-transmit aberration correction from Jan Kubanek's group."),
    ("41177518", [(4, "there is a peer-reviewed journal article from the institute where"),
                  (4, "That mechanical index was not reported in the original publication of the serious adverse event")],
     "The published report of the serious adverse event in the substance use disorder trial."),
    ("41205799", [(4, "there were two follow-up letters from Elsa Fouragnan and Kim Butts Pauly")],
     "Kim Butts Pauly's letter in response to the adverse event report."),
    ("39471185", [(3, "Keith and I talked about it in, uh, in the paper that we wrote")],
     "Elsa on the perspective she and Keith wrote in PLOS Biology."),
    ("18958151", [(11, "There's an original, I think, 2008 paper from Jamie Tyler's group"), (11, "It's cited over 800 times")],
     "Charles and Keith on Jamie Tyler's 2008 PLoS One paper: brain slices, short pulses, no double PRF."),
    ("29804920", [(1, "there were just like two papers in mouse"),
                  (17, "Neuron also published the auditory confound papers that came out of the Brain Initiative")],
     "One of the two 2018 Neuron papers on the auditory confound (in mice)."),
    ("29804919", [(1, "there were just like two papers in mouse"),
                  (17, "Neuron also published the auditory confound papers that came out of the Brain Initiative")],
     "The other 2018 Neuron auditory-confound paper (in guinea pigs)."),
    ("40624336", [(2, "work led by Hector Estrada and Daniel Razansky")],
     "Keith's FUS win: holographic stimulation lowers the ultrasound needed. He says Nature Communications on air; it was published in Nature Biomedical Engineering."),
    ("42243115", [(20, "to enhance the REM sleep, the paper published in Nature Communications")],
     "Zhihai's FUS win: Huiliang Wang's ultrasound patch for REM sleep enhancement."),
]

JOURNAL = {
    "Proceedings of the National Academy of Sciences of the United States of America": "PNAS",
    "IEEE transactions on ultrasonics, ferroelectrics, and frequency control": "IEEE Trans Ultrason Ferroelectr Freq Control",
    "The Journal of the Acoustical Society of America": "J Acoust Soc Am",
    "The Journal of neuroscience": "Journal of Neuroscience",
    "The American journal of psychiatry": "American Journal of Psychiatry",
    "medRxiv": "medRxiv (preprint)", "bioRxiv": "bioRxiv (preprint)", "ArXiv": "arXiv (preprint)",
    "Advanced science (Weinheim, Baden-Wurttemberg, Germany)": "Advanced Science",
    "eLife": "eLife", "iScience": "iScience",
}
SMALL = {"of", "and", "the", "in", "for", "on", "a", "an", "to"}


def journal(r):
    jt = r.get("JT", [""])[0].split(" : ")[0].strip()
    if jt in JOURNAL:
        return JOURNAL[jt]
    if jt.split(" ")[0] in JOURNAL:
        return JOURNAL[jt.split(" ")[0]]
    return " ".join(w if (i and w in SMALL) else (w[0].upper() + w[1:]) for i, w in enumerate(jt.split()))


def authors(r):
    au = r.get("AU", [])
    return ", ".join(au) if len(au) <= 3 else f"{', '.join(au[:2])} … {au[-1]}"


def missing_record(pmid):
    """The exit message for a VERIFIED PMID that is not in mentioned.txt, naming a guest file that has it."""
    have = next((f for f in sorted(PUBMED_DIR.glob("*.txt")) if f != MENTIONED and pmid in pubmed([f])), None)
    where = (f"copy its record from {rel(have)}" if have else "download its record from "
             f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&rettype=medline&retmode=text")
    return f"PMID {pmid} (VERIFIED) has no record in {rel(MENTIONED)}: {where} and append it there, after a blank line."


def paper(pmid, places, records):
    if pmid not in records:
        sys.exit(missing_record(pmid))
    r = records[pmid]
    doi = next((x.split()[0] for x in r.get("LID", []) + r.get("AID", []) if x.endswith("[doi]")), None)
    title = re.sub(r"\s+", " ", " ".join(r["TI"])).strip()
    moms = []
    for ep, phrase in places:
        i = locate(ep, phrase)
        q = quote_at(ep, i)
        if not q:
            sys.exit(f"PMID {pmid}: nothing quotable at ep {ep} {phrase!r}")
        moms.append(moment(ep, i, q))
    return {
        "id": pmid, "title": title.rstrip("."), "authors": authors(r), "n_authors": len(r.get("AU", [])),
        "year": int(r["DP"][0][:4]), "journal": journal(r), "preprint": "Preprint" in r.get("PT", []),
        "doi": doi, "url": f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "pubmed": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "moments": sorted(moms, key=lambda m: (m["ep"], m["t"])),
    }


# ---------------------------------------------------------------- tools and companies
# name, regex (whole word, case-insensitive; a name that is also an ordinary word is matched capitalised, with (?-i:)),
# one-line description (only where sure), official link (only where sure). Descriptions marked "on the show" come from
# what is said in the episodes.
TOOLS = [
    ("k-Wave", r"k-?wave", "Open-source MATLAB toolbox for simulating acoustic waves, from Brad Treeby and Ben Cox at UCL.",
     "https://github.com/ucl-bug/k-wave"),
    ("k-Plan", r"k-?plan", "Transcranial ultrasound planning software built on k-Wave.", None),
    ("BabelBrain", r"babel ?brain", DEFS["BabelBrain"], "https://github.com/ProteusMRIgHIFU/BabelBrain"),
    ("Brainsight", r"brainsight", "Neuronavigation system from Rogue Research; BabelBrain can be called from it.", None),
    ("3D Slicer", r"3d slicer", "Open-source platform for medical image analysis.", "https://www.slicer.org/"),
    ("OpenUST", r"open ?ust", "Open-source ultrasound tomography ring array from UCL.", None),
    ("NeuroFUS", r"neuro ?fus", "BrainBox's turnkey transcranial ultrasound stimulation system, made with Sonic Concepts (Jamie Tyler tells its origin in Ep 15).",
     None),
    ("Verasonics", r"verasonics", "Programmable research ultrasound systems, used here to drive custom transducers.",
     "https://verasonics.com/"),
]
COMPANIES = [
    ("Insightec", r"insightec", "Maker of Exablate, the MR-guided focused ultrasound system used to treat essential tremor.",
     "https://www.insightec.com/"),
    ("NeuroHarmonics", r"neuro ?harmonics", "Company Brad Treeby started, focused on clinical translation (on the show, Ep 22).", None),
    ("Attune", r"(?-i:Attune)", "Keith Murphy's ultrasound neuromodulation company.", None),
    ("SonoMind", r"sonomind", "Co-founded by Jean-François Aubry; personalised ultrasound for treatment-resistant depression (Ep 16).", None),
    ("Openwater", r"(?-i:Open ?[Ww]ater)", "Mary Lou Jepsen's medical-device company, with open-source ultrasound hardware.", None),
    ("BrainBox", r"brain ?box", "UK neurostimulation company behind the NeuroFUS system, with Sonic Concepts.", None),
    ("Sonic Concepts", r"sonic concepts", "Focused ultrasound transducer maker.", None),
    ("SuperSonic Imagine", r"supersonic imagine", "French ultrasound imaging company known for shear wave elastography.", None),
    ("Imasonic", r"imasonic", "French ultrasound transducer manufacturer.", None),
    ("Gestala", r"gestala", "Phoenix Peng's ultrasound brain-computer interface company (Ep 21).", None),
    ("Merge Labs", r"merge labs", "Brain-computer interface company; discussed on the show as commercialising sonogenetics.", None),
    ("Forest Neurotech", r"(?-i:Forest)(?: neurotech)?", "Nonprofit research organisation building ultrasound brain-interface technology.", None),
    ("Neuralink", r"neuralink", "Implanted brain-computer interface company.", "https://neuralink.com/"),
    ("Synchron", r"synchron", "Brain-computer interface implanted through the blood vessels.", None),
    ("Medtronic", r"medtronic", "Medical-device company; maker of deep brain stimulation systems including Percept.",
     "https://www.medtronic.com/"),
    ("Abbott", r"(?-i:Abbott)", "Medical-device company; its DBS for depression trial comes up in Ep 9.", None),
    ("Midjourney", r"midjourney", "The AI image company; its move into ultrasound tomography is discussed in Ep 22.", None),
    ("Satori Neuro", r"satori(?: neuro)?", "Satori's neuro-focused investment programme, Amy Kruse is its Chief Investment Officer (Ep 13).", None),
    ("Rogue Research", r"rogue research", "Canadian company that makes the Brainsight neuronavigation system.", None),
]


def hits(rx):
    rx = re.compile(r"(?<![\w-])" + rx + r"(?![\w])", re.I)
    out = []
    for ep, e in transcripts().items():
        last = -1e9
        for m in rx.finditer(e["text"]):
            i = bisect.bisect_right(e["starts"], m.start()) - 1
            w = e["words"][i]
            if w["s"] - last < 45:
                continue
            last = w["s"]
            out.append({"ep": ep, "t": round(w["s"], 2)})
    return out


def entry(name, rx, desc, url):
    return {"name": name, "desc": desc, "url": url, "moments": hits(rx)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", action="store_true", help="print paper candidates to review instead of building")
    if ap.parse_args().candidates:
        candidates()
        return
    if not MENTIONED.exists():
        sys.exit(f"{rel(MENTIONED)} is missing: it holds the PubMed records of the VERIFIED papers")
    records = pubmed([MENTIONED])
    shown = set(transcripts())
    papers = [paper(p, [pl for pl in places if pl[0] in shown], records) for p, places, _note in VERIFIED
              if any(pl[0] in shown for pl in places)]
    papers.sort(key=lambda p: (p["moments"][0]["ep"], p["moments"][0]["t"]))
    tools = [entry(*t) for t in TOOLS]
    comps = [entry(*c) for c in COMPANIES]
    for group in (tools, comps):
        for e in group:
            if not e["moments"]:
                print(f"no hits for {e['name']} in the episodes on the site: left out (a typo in its pattern? a hidden episode?)")
        group[:] = sorted((e for e in group if e["moments"]), key=lambda e: -len(e["moments"]))
    write_js(OUT, "window.FF_MENTIONS=", {"papers": papers, "tools": tools, "companies": comps}, ";\n")
    n = lambda g: sum(len(e["moments"]) for e in g)
    print(f"{len(papers)} papers ({n(papers)} moments), {len(tools)} tools ({n(tools)} moments), "
          f"{len(comps)} companies ({n(comps)} moments) -> {rel(OUT)}")
    for p in papers:
        m = p["moments"][0]
        print(f"  Ep{m['ep']:>2} {m['t']:7.1f} {p['id']} {p['year']} {p['journal'][:28]:28s} {p['title'][:60]} | {m['quote'][:70]}")


if __name__ == "__main__":
    main()
