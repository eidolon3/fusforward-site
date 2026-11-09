"""Explainers and definitions for the FUS Forward transcript site: site/data/explainers.js.

Keith Murphy keeps asking guests to "explain that to our listeners". The clips where someone explains a term are
kept by hand in CURATED below, each read in context: clear, accurate, self-contained, 20-120 s long (the build
checks this after snapping) and teaching the show's subject. This script snaps each span to word boundaries, names
the speaker, and writes one-line plain-English definitions for the jargon a newcomer meets: the glossary's terms
(3+ mentions) and the common acronyms, reusing build_site_data.DEFS verbatim. Tools and companies are left to
build_mentions.py, which describes them. Output:
  window.FF_EXPLAIN = {explainers: [{id, n, s, e, title, terms, who, level, caveat?}],
                       defs: {term: {def, expand?, also?, mark?}}}
A clip's id is its episode and the whole second of its first word ("16-2230"); site/web/essentials.js and CAVEATS
name clips by it, so a re-timed transcript that moves a first word across a second changes the id.

Run:  python scripts/build_explainers.py                  after build_site_data.py; then build_quotes.py
      python scripts/build_explainers.py --candidates 16  print episode 16's likely explanations, to pick new clips
"""
import argparse
import re
import sys
from collections import Counter
from functools import cache

from wordfreq import zipf_frequency

from build_mentions import COMPANIES, TOOLS
from build_site_data import DEFS, read_js, write_js
from common import HOSTS, NARRATOR, ROOT, SENTENCE_END, load_json, rel

EPS = ROOT / "out" / "episodes"
SITE = ROOT / "site" / "data"
LEVELS = ("basics", "intermediate", "deep cut")
CLIP_S = (20, 120)   # shortest and longest clip, in seconds


@cache
def episode(n):
    return load_json(EPS / f"{n:02d}.json")


# ---------- candidates (--candidates N): sentences worth reading in context for new clips ----------
ASK = re.compile(
    r"\b(explain|break (that|it|this) down|walk (us|me|our listeners) through|for (our|the) (listeners|listenership|audience)|"
    r"for (the )?people (at home|who might not know)|for those who (don't|do not) know|what does (that|it|this|[\w-]+) (mean|stand for)|"
    r"tell (us|me) what|what exactly is|teach people)", re.I)
WHAT_IS = re.compile(r"\bwhat(?: is|'s|’s) (?:an? |the )?([\w-]+(?: [\w-]+)?)\?", re.I)
VOL = re.compile(
    r"\b(is basically|are basically|what we call|what's called|what is called|stands for|refers to|is essentially|"
    r"in other words|for people who are not familiar|for those who don't know|which means|meaning that)\b", re.I)


def sentences(words, w0, w1):
    out, st = [], w0
    for i in range(w0, w1):
        if SENTENCE_END.search(words[i]["w"]) or i == w1 - 1:
            out.append((st, i + 1))
            st = i + 1
    return out


def jargon(phrase):
    """'what is derating?' is a request for a definition; 'what's next?' is not."""
    return min(zipf_frequency(w, "en") for w in re.findall(r"[A-Za-z]+", phrase) or ["the"]) < 3.6


def candidates(n):
    """(start, speaker, sentence) wherever a host asks for an explanation (or "what is X?" about a rare word) or
    anyone volunteers a definition ("what we call", "stands for") in episode n."""
    d = episode(n)
    W, sp = d["words"], d["speakers"]
    found = []
    for t in d["turns"]:
        who = sp[t["p"]]
        if who == NARRATOR:
            continue
        for a, b in sentences(W, t["w0"], t["w1"]):
            txt = " ".join(w["w"] for w in W[a:b])
            m = WHAT_IS.search(txt)
            if (who in HOSTS and (ASK.search(txt) or (m and jargon(m.group(1))))) or VOL.search(txt):
                found.append((W[a]["s"], who, txt))
    return found


# ---------- the keepers (read in context; precision over recall) ----------
# (episode, start s, end s, question-style title, terms (keys of the definitions), level)
# Spans start on the explainer's first word and stop before tangents; each was read in context.
# The first term is the clip's main subject: an episode page's margin note on a term prefers the clips that list it first.
CURATED = [
    # --- The fundamentals (the show rarely explains these; the clearest passages it has)
    (15, 1123.2, 1154.5, "Why do we think of the brain as electrical?", [], "basics"),
    (12, 2946.14, 3046.1, "How long does a pulse have to be to actually push tissue?", [], "deep cut"),
    (14, 799.2, 829.5, "Do simulators disagree because of the solver or the skull?", [], "deep cut"),
    (19, 2095.8, 2151.0, "Why switch from a 1 kHz to a 5 Hz pulse rate, and why go offline?", [], "intermediate"),
    (19, 1852.3, 1895.3, "How can a small nudge produce huge learning effects?", [], "intermediate"),
    (2, 566.0, 606.25, "What is ultrasound, physically?", ["frequency"], "basics"),
    (1, 521.0, 574.2, "Why is getting through the skull such a big deal?", ["frequency"], "basics"),
    (13, 1168.8, 1217.6, "What can focused ultrasound do: remove tissue, or tune a circuit?", ["LIFU", "HIFU"], "basics"),
    (1, 638.0, 667.3, "Does the brain “speak” ultrasound?", [], "basics"),

    # --- How sound moves neurons
    (2, 212.2, 247.8, "Which ion channels respond to ultrasound?", ["ion channels", "mechanosensitive", "Piezo1"], "basics"),
    (12, 949.4, 991.5, "A cell is far smaller than the wave. What does it actually feel?", ["acoustic radiation force", "frequency", "mechanosensitive"], "intermediate"),
    (2, 626.1, 672.0, "Why do bubbles grow more at low frequencies?", ["cavitation", "frequency"], "intermediate"),
    (12, 1152.0, 1192.6, "Why do microbubbles lower the threshold?", ["microbubbles", "sonogenetics", "blood-brain barrier"], "intermediate"),
    (5, 2534.75, 2555.6, "Stirring the fluid, or triggering the cells?", ["mechanosensitive", "ion channels", "glymphatic"], "deep cut"),
    (20, 1653.6, 1703.3, "Can sonogenetics outshine the brain's own response to ultrasound?", ["sonogenetics", "MscL", "mechanosensitive"], "deep cut"),
    (19, 1766.2, 1831.5, "Does ultrasound make neurons fire, or just nudge them?", ["frontal eye fields", "ITRUSST"], "intermediate"),
    (5, 2987.3, 3038.6, "If ablation uses ultrasound too, why didn't it show neuromodulation?", ["HIFU", "LIFU"], "intermediate"),
    (3, 4229.8, 4328.0, "Does the brain's state change what ultrasound does?", ["brain state"], "deep cut"),

    # --- Dialling in the dose
    (11, 133.6, 179.6, "What is a nested (double) PRF?", ["PRF", "double PRF", "carrier frequency"], "basics"),
    (11, 933.75, 954.6, "Does fancy pulsing keep the brain from heating?", ["duty cycle", "PRF", "pulse duration"], "intermediate"),
    (2, 692.6, 777.2, "Is higher or lower frequency better for neuromodulation?", ["frequency", "acoustic radiation force"], "intermediate"),
    (7, 1154.6, 1207.5, "How small is the focus, and what sets its size?", ["focal spot", "focus", "frequency"], "basics"),
    (22, 344.3, 366.2, "Focal size or targeting accuracy: what's the difference?", ["focal spot", "focus"], "basics"),
    (19, 1600.6, 1636.4, "Same energy, different effect: exposure versus dose", ["target engagement", "brain state"], "intermediate"),

    # --- Getting through the skull
    (16, 1582.5, 1629.2, "Can ultrasound really get through the skull?", ["skull aberration", "attenuation", "focal spot"], "basics"),
    (16, 2230.5, 2279.3, "How does the skull distort the beam?", ["skull aberration", "speed of sound", "aberration correction"], "basics"),
    (16, 2279.9, 2341.2, "Phased array or acoustic lens: two ways to correct for the skull", ["aberration correction", "phased array", "acoustic lens", "transducer"], "intermediate"),
    (1, 1290.0, 1312.6, "Single element or array: what's the difference?", ["transducer", "phased array", "aberration correction"], "basics"),
    (22, 509.4, 558.95, "Why is hair a problem for transcranial ultrasound?", ["transducer", "phased array"], "basics"),
    (14, 556.1, 611.4, "Why use CT to plan through the skull?", ["CT", "speed of sound", "attenuation", "skull aberration"], "intermediate"),
    (14, 2283.0, 2352.5, "What does a CT scan miss about the skull?", ["CT", "Hounsfield units", "attenuation", "microstructure"], "deep cut"),
    (3, 1465.87, 1525.75, "Why make skull images from MRI instead of CT?", ["pseudo-CT", "CT"], "intermediate"),

    # --- Simulating and aiming
    (10, 886.9, 968.4, "What is BabelBrain, and how do people use it?", ["BabelBrain", "neuronavigation", "transducer"], "basics"),
    (14, 649.05, 688.0, "Why does skull modeling matter for dose?", ["attenuation", "CT"], "basics"),
    (2, 1394.95, 1452.9, "How accurate are skull simulations?", ["k-Wave", "focus"], "intermediate"),
    (22, 2202.4, 2253.0, "What makes an acoustic simulation trustworthy?", ["k-Wave"], "intermediate"),
    (22, 2279.0, 2324.9, "Is a more detailed skull model always more accurate?", ["k-Wave"], "deep cut"),
    (6, 2091.7, 2144.1, "Same transducer output for everyone, or same pressure in the brain?", ["transducer", "attenuation"], "intermediate"),
    (6, 1490.65, 1553.0, "How do you aim a single-element transducer in the scanner?", ["neuronavigation", "transducer", "amygdala"], "intermediate"),
    (2, 1106.9, 1131.1, "What is MR-ARFI?", ["MR-ARFI", "acoustic radiation force"], "intermediate"),
    (19, 874.8, 926.1, "Can we measure delivered dose?", ["MR-ARFI", "skull aberration"], "intermediate"),

    # --- Hearing, shams and controls
    (1, 232.3, 253.0, "What is the auditory confound?", ["auditory confound"], "basics"),
    (1, 327.95, 355.0, "Why can people hear ultrasound stimulation?", ["auditory confound", "PRF"], "basics"),
    (20, 876.3, 927.3, "How do you rule out hearing? Make the mice deaf", ["auditory confound", "transducer"], "intermediate"),
    (3, 1996.6, 2071.6, "Can testing after stimulation sidestep the sound problem?", ["auditory confound", "offline effects"], "intermediate"),
    (6, 518.3, 571.0, "What makes a good sham? A lesson from TMS", ["sham", "TMS", "auditory confound"], "intermediate"),
    (17, 1173.5, 1209.2, "How do you build controls into a human study?", ["active control", "sham", "offline effects", "temporal window"], "basics"),
    (19, 1222.9, 1251.9, "Why do trials need an active control site?", ["active control", "sham", "treatment-resistant depression"], "intermediate"),

    # --- Is it working?
    (19, 992.9, 1036.5, "What is target engagement, and why do funders demand it?", ["target engagement", "fMRI", "TMS"], "basics"),
    (3, 3844.71, 3930.9, "Proving you hit the nucleus accumbens, with DBS patients", ["nucleus accumbens", "DBS", "target engagement"], "intermediate"),
    (17, 1613.2, 1676.5, "What did GABA and glutamate show after amygdala stimulation?", ["MRS", "GABA", "glutamate", "amygdala"], "deep cut"),
    (19, 2356.4, 2407.4, "Can blood-vessel effects fake an fMRI result?", ["fMRI", "active control"], "intermediate"),
    (17, 2454.1, 2532.5, "How long do 80 seconds of ultrasound last?", ["offline effects", "amygdala", "fMRI"], "intermediate"),
    (19, 2196.2, 2238.2, "Online or offline: when should you stimulate?", ["offline effects", "plasticity"], "intermediate"),
    (14, 1491.1, 1573.2, "No response: wrong treatment, or did the sound not get through?", ["ITRUSST", "attenuation"], "intermediate"),
    (16, 2996.4, 3079.6, "Why nail the targeting before tuning the parameters?", ["skull aberration", "aberration correction"], "intermediate"),

    # --- Safety and regulation
    (4, 242.3, 313.7, "Where does the 1.9 mechanical-index limit come from?", ["mechanical index", "LIFU", "HIFU"], "basics"),
    (4, 346.1, 415.8, "Where might cavitation start to cause harm?", ["mechanical index", "cavitation", "frequency"], "intermediate"),
    (14, 1987.5, 2017.5, "What is derating?", ["derating"], "intermediate"),
    (19, 170.62, 226.2, "What is ITRUSST?", ["ITRUSST"], "basics"),
    (16, 3856.8, 3934.3, "What do the ITRUSST safety guidelines actually do?", ["ITRUSST", "non-significant risk"], "intermediate"),
    (4, 52.1, 113.9, "What happened in the first serious adverse event?", ["serious adverse event"], "basics"),
    (4, 696.7, 738.1, "Why does it matter that it happened above MI 1.9?", ["mechanical index", "ITRUSST", "serious adverse event"], "intermediate"),
    (19, 2840.1, 2889.2, "Will low-intensity ultrasound ever cause a serious adverse event?", ["serious adverse event"], "intermediate"),
    (6, 1292.2, 1363.8, "What does an FDA “significant risk” call mean?", ["non-significant risk", "IDE"], "intermediate"),
    (4, 615.8, 655.7, "Why follow patients after a device is approved?", ["serious adverse event"], "intermediate"),

    # --- Deep targets and treatments
    (9, 2762.3, 2827.9, "What is essential tremor, and how does focused ultrasound treat it?", ["essential tremor", "thalamotomy", "DBS"], "basics"),
    (22, 3211.5, 3252.7, "Why start clinical trials with essential tremor?", ["essential tremor", "biomarkers"], "basics"),
    (10, 1636.75, 1694.2, "Why did tremor fall only 10–15 minutes after sonication?", ["essential tremor", "offline effects", "ion channels"], "intermediate"),
    (17, 465.35, 523.2, "Why reach for the amygdala with ultrasound?", ["amygdala", "TMS"], "basics"),
    (17, 559.8, 603.8, "Is the amygdala one target or many?", ["amygdala"], "intermediate"),
    (6, 2534.6, 2609.05, "What is the default mode network?", ["default mode network"], "intermediate"),
    (6, 2643.8, 2684.3, "What is the salience network, and how does it tie to PTSD?", ["amygdala", "PTSD"], "intermediate"),
    (3, 2657.3, 2740.1, "Why perturb a reward circuit we already know well?", ["nucleus accumbens", "fMRI"], "intermediate"),
    (16, 2796.8, 2839.6, "White matter or grey matter: which should we target?", ["white matter tracts", "DBS", "focal spot"], "deep cut"),
    (3, 3138.2, 3185.9, "Why pair ultrasound with training or therapy?", ["plasticity"], "intermediate"),
    (4, 751.6, 791.7, "When is cavitation used on purpose?", ["cavitation", "blood-brain barrier", "microbubbles"], "intermediate"),
    (5, 1042.8, 1106.0, "Why release drugs with a mechanical push instead of heat?", ["liposomes", "ketamine"], "deep cut"),
]

# Notes shown under a clip where what is said on air is inaccurate or contested (keyed by clip id).
CAVEATS = {
    "4-242": "The FDA's mechanical index was introduced in 1991–92. Its 1.9 cap reproduces the output of diagnostic scanners sold before 1976; it is not a measured threshold for bioeffects.",
    "9-2762": "The thalamotomy lesion is a few millimetres across, in the thalamus's Vim nucleus, not the whole thalamus. Focused ultrasound was used in the brain from the 1950s; tremor was the first FDA-approved brain treatment (2016).",
    "2-212": "Which ion channels respond to ultrasound in the living brain, and how directly, is still debated.",
    "4-751": "The glioblastoma blood-brain-barrier-opening trials are early-phase studies of safety and feasibility; a survival benefit has not yet been shown.",
}


# ---------- definitions ----------
# Written here, only where the meaning is settled; DEFS wins wherever it has the term.
MINE = {
    "FUS": "Focused ultrasound: sound far above human hearing, shaped to converge on a small spot deep in the body.",
    "ultrasound neuromodulation": "Changing brain activity with ultrasound, gently and reversibly, rather than destroying tissue.",
    "low-intensity focused ultrasound": "Focused ultrasound at energies low enough to change brain activity without damaging tissue (LIFU).",
    "high-intensity focused ultrasound": "Focused ultrasound strong enough to heat and destroy a small target, as in tremor treatment (HIFU).",
    "transcranial ultrasound stimulation": "Stimulating the brain with ultrasound sent through the intact skull (TUS).",
    "TMS": "A magnetic coil held against the head induces currents that stimulate the brain's surface; it can't reach deep targets focally, only by also stimulating the tissue above them.",
    "EEG": "Recording the brain's electrical activity through electrodes on the scalp.",
    "DBS": "An implanted electrode delivers electrical pulses to a deep brain target; used for Parkinson's disease and tremor.",
    "ECT": "A brief, controlled seizure induced under anaesthesia; one of the most effective treatments for severe depression.",
    "fMRI": "MRI that tracks changes in blood oxygen to show which brain areas are active.",
    "tDCS": "A weak electric current passed through scalp electrodes that nudges neurons toward or away from firing.",
    "BCI": "A system that reads brain activity, stimulates it, or both, to link the brain to a computer.",
    "brain-computer interface": "A system that reads brain activity, stimulates it, or both, to link the brain to a computer (BCI).",
    "CT": "An X-ray scan that shows bone in fine detail; used to model how sound crosses the skull.",
    "PET": "A scan that tracks a radioactive tracer, such as labelled glucose, to show where the brain is most active.",
    "CSF": "The clear fluid that surrounds and cushions the brain and spinal cord.",
    "PTSD": "Lasting fear, intrusive memories and hyperarousal after a traumatic event.",
    "GABA": "The brain's main inhibitory messenger: it makes neurons less likely to fire.",
    "glutamate": "The brain's main excitatory messenger: it makes neurons more likely to fire.",
    "MRS": "An MRI method that measures the concentration of chemicals, such as GABA and glutamate, in one brain region.",
    "ULM": "Tracking single injected microbubbles to map blood vessels far finer than ordinary ultrasound can resolve.",
    "IRB": "The ethics committee that must approve research on people.",
    "IDE": "FDA permission to test a significant-risk device in a clinical study.",
    "non-significant risk": "An FDA category for device studies that pose little risk; they can go ahead with ethics-board approval instead of a full FDA exemption (IDE).",
    "serious adverse event": "A medical harm during a trial that is life-threatening, needs hospital care or causes lasting damage, whether or not the treatment caused it.",
    "PETRA": "An MRI sequence with a near-zero echo time that picks up signal from bone, used to make CT-like skull images.",
    "MscL": "A bacterial ion channel that opens when the cell membrane is stretched; used in sonogenetics to make neurons respond to ultrasound.",
    "Piezo1": "An ion channel found in many cell types that opens under mechanical force; a candidate for how cells sense ultrasound.",
    "ion channels": "Pores in the cell membrane that open and close to let charged particles through; they set a neuron's electrical activity.",
    "mechanosensitive": "Responding to mechanical force such as stretch or pressure; mechanosensitive channels are one route by which ultrasound may act on neurons.",
    "liposomes": "Tiny spheres with a fatty double-layer shell, like a cell membrane, used to carry drugs.",
    "nanoparticles": "Particles a few billionths of a metre across, engineered to carry drugs or contrast agents.",
    "glymphatic": "The brain's waste-clearance route: cerebrospinal fluid flows along the spaces around blood vessels and exchanges with the fluid between brain cells.",
    "hydrophone": "A small underwater microphone used to measure the pressure an ultrasound beam produces.",
    "speed of sound": "How fast sound travels in a material: about 1,500 m/s in soft tissue and roughly twice that in skull bone, which is why the skull bends and shifts the beam.",
    "shear wave": "A slow, sideways-moving wave in tissue, set off when the beam pushes on it.",
    "shear wave elastography": "Imaging tissue stiffness by timing shear waves: they travel faster through stiffer tissue.",
    "photoacoustic": "Imaging in which a laser pulse is absorbed by tissue such as blood, which expands slightly and gives off sound that is then recorded.",
    "piezoelectric": "Describes crystals that change shape when a voltage is applied, and make a voltage when squeezed; the working part of most transducers.",
    "acoustic radiation force": "The steady push a sound beam exerts on tissue as the tissue absorbs or reflects it; it moves tissue by a few microns.",
    "metamaterial": "An engineered material whose structure bends or shapes waves in ways ordinary materials can't.",
    "metrology": "The science of measurement; here, knowing exactly what pressure an ultrasound device produces.",
    "microstructure": "Fine internal structure; in the skull, the spongy inner bone that scatters sound in ways a CT scan can't resolve.",
    "theta burst": "A pattern borrowed from TMS: short bursts repeated about five times a second (the brain's theta rhythm).",
    "double PRF": "Two repetition rates nested inside each other: fast pulses grouped into bursts that themselves repeat at a slower rate.",
    "pulse train": "A run of repeated pulses delivered as one block, often repeated with rests in between.",
    "pulse duration": "How long each ultrasound pulse lasts, from switching on to switching off.",
    "carrier frequency": "The ultrasound wave's own frequency, usually a few hundred kilohertz for the brain, which the pulsing switches on and off.",
    "frequency": "How many pressure cycles per second the wave makes. Lower frequencies cross the skull more easily; higher ones give a smaller focus.",
    "focus": "The small region where the beam converges and the pressure is highest; the one spot meant to be stimulated.",
    "focal spot": "The size and shape of the focus: usually a few millimetres wide and several times longer along the beam.",
    "attenuation": "The loss of beam energy as sound travels through tissue, and especially bone, by absorption and scattering.",
    "derating": "Reducing a pressure or intensity measured in water by a standard tissue loss (0.3 dB per cm per MHz) to estimate what reaches tissue; a convention from diagnostic imaging.",
    "free field": "Measuring a transducer's output in open water with nothing in the way, as a clean baseline before skull or tissue is added.",
    "power Doppler": "An ultrasound mode that measures the strength of echoes from moving blood, a stand-in for how much blood is in each spot.",
    "default mode network": "Brain regions that are most active at rest, when the mind turns inward; linked to rumination in depression.",
    "active control": "A comparison in which ultrasound goes to a different brain target, so effects of sound, touch or expectation are matched.",
    "sham": "A fake session that mimics the real one without delivering the active dose, to control for placebo effects.",
    "offline effects": "Changes in brain activity that outlast the ultrasound and are measured after stimulation ends.",
    "temporal window": "The thin patch of skull at the temple, where ultrasound passes most easily.",
    "biomarkers": "Measurable signals, such as a pattern of brain activity, that track a disease or a treatment's effect.",
    "neurotech": "Devices that record from or stimulate the nervous system.",
    "vagus nerve": "A long nerve running from the brainstem to the heart and gut; stimulating it is an approved treatment for epilepsy and depression.",
    "frontal eye fields": "A region of the frontal lobe that controls eye movements and visual attention.",
    "threat learning": "Learning to predict danger from cues, as in fear conditioning; the amygdala is central to it.",
    "white matter tracts": "Bundles of nerve fibres that carry signals between brain regions.",
    "cryopreservation": "Preserving cells or tissue by cooling them to very low temperatures.",
    "psychedelics": "Drugs such as psilocybin, LSD and DMT that alter perception; being tested as treatments for depression, anxiety and PTSD.",
    "ketamine": "An anaesthetic that, at lower doses, has fast-acting antidepressant effects.",
    "treatment-resistant depression": "Depression that hasn't improved after at least two adequate courses of treatment.",
    "self-experimentation": "Researchers or hobbyists trying an experimental technique, such as brain ultrasound, on themselves.",
    "lived experience": "First-hand knowledge of a condition from having it, rather than from studying it.",
    "Percept": "Medtronic's deep brain stimulation system, which can also record brain signals through its leads.",
    "DARPA": "The US military's funder of high-risk, high-reward research.",
    "ARPA-H": "A US agency funding high-risk health research on the DARPA model.",
    "UCL": "University College London, where k-Wave was developed.",
    # used by the Explained clips (quiet, see QUIET)
    "target engagement": "Evidence that stimulation actually changed the circuit it was aimed at, from a brain or behavioural readout rather than symptoms alone.",
    "plasticity": "The brain's ability to strengthen or weaken its own connections; effects that outlast stimulation are thought to rely on it.",
    "brain state": "What the brain is doing at the moment of stimulation (resting, working on a task, in pain, anaesthetised); the same dose can act differently in different states.",
}
EXPAND = {
    "PRF": "pulse repetition frequency", "ISPPA": "spatial-peak pulse-average intensity", "ISPTA": "spatial-peak temporal-average intensity",
    "MI": "mechanical index", "ITRUSST": "International Transcranial Ultrasonic Stimulation Safety and Standards consortium",
    "TUS": "transcranial ultrasound stimulation", "tFUS": "transcranial focused ultrasound", "LIFU": "low-intensity focused ultrasound",
    "HIFU": "high-intensity focused ultrasound", "MRgFUS": "magnetic resonance-guided focused ultrasound", "DBS": "deep brain stimulation",
    "TMS": "transcranial magnetic stimulation", "ECT": "electroconvulsive therapy", "EEG": "electroencephalography",
    "fMRI": "functional magnetic resonance imaging", "BBB": "blood-brain barrier", "MR-ARFI": "magnetic resonance acoustic radiation force imaging",
    "FUS": "focused ultrasound", "BCI": "brain-computer interface", "tDCS": "transcranial direct current stimulation", "CT": "computed tomography",
    "PET": "positron emission tomography", "CSF": "cerebrospinal fluid", "PTSD": "post-traumatic stress disorder",
    "GABA": "gamma-aminobutyric acid", "MRS": "magnetic resonance spectroscopy", "ULM": "ultrasound localization microscopy",
    "IRB": "institutional review board", "IDE": "investigational device exemption", "MscL": "mechanosensitive channel of large conductance",
    "PETRA": "pointwise encoding time reduction with radial acquisition", "DARPA": "Defense Advanced Research Projects Agency",
    "ARPA-H": "Advanced Research Projects Agency for Health", "UCL": "University College London",
}
ALSO = {   # other spellings in the transcripts (plurals ending in -s are matched anyway)
    "MR-ARFI": ["ARFI"], "double PRF": ["nested PRF"], "pulse duration": ["pulse length", "pulse width"],
    "focal spot": ["focal size", "focal point", "focal region"], "non-human primates": ["non-human primate", "nonhuman primates", "NHP"],
    "blood-brain barrier": ["blood brain barrier"], "k-Wave": ["kWave"], "BabelBrain": ["Babel Brain"],
    "microbubbles": ["microbubble", "micro-bubbles"], "liposomes": ["liposome"], "nanoparticles": ["nanoparticle"],
    "biomarkers": ["biomarker"], "ion channels": ["ion channel"], "sonication": ["sonicate", "sonicating", "sonicated"],
    "glymphatic": ["glymphatics"], "psychedelics": ["psychedelic"], "Hounsfield units": ["Hounsfield unit"],
    "theta burst": ["theta-burst"], "offline effects": ["offline effect"], "white matter tracts": ["white matter tract"],
    "frequency": ["frequencies"], "default mode network": ["default network", "default-mode network"], "free field": ["free-field"],
    "skull aberration": ["skull aberrations"], "acoustic lens": ["acoustic lenses"], "brain-computer interface": ["brain computer interface"],
    "mechanical index": ["mechanical indices"], "auditory confound": ["auditory confounds"], "pseudo-CT": ["pseudo CT", "pseudo-CTs"],
    "functional ultrasound": ["functional ultrasound imaging"], "transcranial ultrasound stimulation": ["transcranial ultrasonic stimulation"],
    "Piezo1": ["Piezo 1"],
}
# Acronyms that share a definition with the term they stand for.
ALIAS = {"MI": "mechanical index", "BBB": "blood-brain barrier"}
# Defined, but not marked in the transcripts (mark: false): the show's own subject, said all the time; "focus", mostly
# a verb on air ("we focus on"); and terms only there for the clips.
QUIET = {"FUS", "LIFU", "TUS", "tFUS", "low-intensity focused ultrasound", "transcranial ultrasound stimulation",
         "ultrasound neuromodulation", "focus", "neurotech", "lived experience", "self-experimentation",
         "target engagement", "plasticity", "brain state"}
# build_mentions.py's tools and companies: described there, so not defined here unless DEFS has them.
ORGS = {name.lower() for name, *_ in TOOLS + COMPANIES}


def build_explainers(defs):
    out = []
    for n, s, e, title, terms, level in CURATED:
        d = episode(n)
        ws = [w for w in d["words"] if w["s"] >= s - 0.3 and w["e"] <= e + 0.3]
        if not ws:
            sys.exit(f"ep {n} {s}-{e} {title!r}: no words in the span")
        if level not in LEVELS:
            sys.exit(f"{title!r}: level {level!r} is not one of {', '.join(LEVELS)}")
        s0, e0 = ws[0]["s"], ws[-1]["e"]
        if not CLIP_S[0] <= e0 - s0 <= CLIP_S[1]:
            sys.exit(f"{title!r}: {e0 - s0:.1f} s is outside {CLIP_S[0]}-{CLIP_S[1]} s")
        undefined = [t for t in terms if t not in defs]
        if undefined:
            sys.exit(f"{title!r}: no definition for {', '.join(undefined)}")
        who = Counter(d["speakers"][w["p"]] for w in ws).most_common(1)[0][0]
        out.append({"id": f"{n}-{int(s0)}", "n": n, "s": round(s0, 2), "e": round(e0, 2), "title": title, "terms": terms,
                    "who": who, "level": level})
    ids = Counter(x["id"] for x in out)
    if max(ids.values()) > 1:
        sys.exit(f"duplicate clip ids: {', '.join(i for i, k in ids.items() if k > 1)}")
    if set(CAVEATS) - set(ids):
        sys.exit(f"CAVEATS for unknown clips: {', '.join(sorted(set(CAVEATS) - set(ids)))}")
    for x in out:
        if x["id"] in CAVEATS:
            x["caveat"] = CAVEATS[x["id"]]
    return out


def build_defs(gloss):
    want = [g["term"] for g in gloss if g["kind"] == "term" and g["count"] >= 3]
    want += list(DEFS) + list(EXPAND) + list(MINE) + list(ALIAS)
    defs, missing, reused = {}, [], 0
    for term in dict.fromkeys(want):
        if term in DEFS or term in ALIAS:
            text = DEFS[ALIAS.get(term, term)]
            reused += 1
        elif term in MINE:
            text = MINE[term]
        elif term.lower() in ORGS:
            continue
        else:
            missing.append(term)
            continue
        d = {"def": text}
        if term in EXPAND:
            d["expand"] = EXPAND[term]
        if term in ALSO:
            d["also"] = ALSO[term]
        if term in QUIET:
            d["mark"] = False
        defs[term] = d
    return defs, missing, reused


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", type=int, metavar="N", help="print episode N's likely explanations instead of building")
    n = ap.parse_args().candidates
    if n is not None:
        if not (EPS / f"{n:02d}.json").exists():
            sys.exit(f"no {rel(EPS / f'{n:02d}.json')}: --candidates takes an episode that has been built")
        found = candidates(n)
        for s, who, txt in found:
            kept = any(c[0] == n and c[1] - 1 <= s <= c[2] for c in CURATED)
            print(f"{'*' if kept else ' '} {s:7.1f}  {who:<22} {txt}")
        print(f"{len(found)} candidates in episode {n}; * already inside a CURATED clip")
        return
    defs, missing, reused = build_defs(read_js(SITE / "glossary.js", "FF_GLOSSARY"))
    ex = build_explainers(defs)
    out = SITE / "explainers.js"
    write_js(out, "window.FF_EXPLAIN=", {"explainers": ex, "defs": defs}, ";\n")
    lv = Counter(x["level"] for x in ex)
    print(f"{len(ex)} explainers ({lv['basics']} basics, {lv['intermediate']} intermediate, {lv['deep cut']} deep cuts) "
          f"from {len({x['n'] for x in ex})} episodes, {sum(x['e'] - x['s'] for x in ex) / 60:.1f} min in all")
    print(f"{len(defs)} definitions ({reused} reused from DEFS, {sum('expand' in d for d in defs.values())} with acronym expansions); "
          f"not defined: {', '.join(missing) or 'none'}")
    for x in ex:
        print(f"  {x['id']:<9} {x['s']:>7.1f}-{x['e']:<7.1f} {x['e'] - x['s']:>4.0f}s  {x['level']:<12} {x['who']:<22} {x['title']}")
    print(f"wrote {rel(out)} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
