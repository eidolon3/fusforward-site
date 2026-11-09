"""Per-episode quality report, from the master file and the intermediate files.

Run:  python scripts/report.py 16
Reads out/episodes/<NN>.json, out/speakers/<NN>.json, out/flags/<NN>.json (flag.py) and data/fixes/<NN>.json.
Output: out/reports/<NN>.md (also printed). It lists the turns whose voice match is weak (worth a listen),
speakers who seem to say their own name (likely mislabels), and the fixes applied.
"""
import re
import sys

import common
from build_terms import terms_for
from common import LOW_SIM, NARRATOR, ROOT, mmss, rel

OUT = ROOT / "out"
WEAK_MAX = 40       # weak voice-match turns listed
SELF_NAMED_MAX = 15  # self-naming hits listed


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


def weak_turns(spk):
    """Turns flagged low, or closer to another voice than to the one they were given."""
    return [t for t in spk["turns"] if "sim" in t and (t.get("low") or t.get("alt_sim", -1) > t["sim"])]


def self_named(m, nick):
    """Speakers apparently saying their own name. People address others by name, so each hit is likely a
    mislabel (quotes like "Charles and Keith look like idiots" count too). The stock cold open is skipped:
    there the narrator names both hosts."""
    cold = common.load_json(ROOT / "data" / "cold_open.json")
    skip_until = cold["end_s"] if m.get("edits", {}).get("cold_open") else 0
    words = [w for w in m["words"] if "x" not in w]
    hits = []
    for i, w in enumerate(words):
        who = m["speakers"][w["p"]]
        if who == NARRATOR or w["s"] < skip_until:
            continue
        forms = {norm(who.split()[0]).strip()} | set(nick.get(who, []))
        if norm(w["w"]).strip() in forms:
            ctx = " ".join(x["w"] for x in words[max(0, i - 5):i + 5])
            hits.append(f"{mmss(w['s'])} {who}: {ctx}")
    return hits


def main():
    n = common.parser(__doc__).parse_args().n
    m = common.load_json(OUT / "episodes" / f"{n:02d}.json")
    spk = common.load_json(OUT / "speakers" / f"{n:02d}.json")
    flags_path = OUT / "flags" / f"{n:02d}.json"
    flags = common.load_json(flags_path, missing_ok=True)
    if flags is None:
        sys.exit(f"{rel(flags_path)} is missing: run python scripts/flag.py {n} first")
    fixes = common.load_fixes(n)
    nick = common.load_json(ROOT / "data" / "nicknames.json")
    words = [w for w in m["words"] if "x" not in w]
    named = self_named(m, nick)
    weak = weak_turns(spk)
    text = " " + norm(" ".join(w["w"] for w in words)) + " "
    terms = terms_for(n)
    heard = {t: text.count(" " + norm(t) + " ") for t in terms}
    near = sum(f["kind"] == "near_miss" for f in flags)
    low = sum(f["kind"] == "low_confidence" for f in flags)
    edits = m.get("edits", {})

    lines = [
        f"# Ep {n} quality report",
        "",
        f"**{m['title']}** · {m['duration_s'] / 60:.0f} min · {len(words):,} words · scribe_v2",
        "",
        "## Speakers",
        "",
        "| Speaker | Talk time | ElevenLabs label(s) |",
        "|---|---|---|",
    ]
    labels = {}
    for l, name in spk["label_names"].items():
        labels.setdefault(name, []).append(l)
    for name, t in spk["talk_min"].items():
        lines.append(f"| {name} | {t} min | {', '.join(labels.get(name, ['(moved turns only)']))} |")
    moved = spk["turns_moved"]
    lines += [
        "",
        f"Turns moved by the voice check: {sum(moved.values()) if moved else 0}"
        + (" (" + ", ".join(f"{k}: {v}" for k, v in moved.items()) + ")" if moved else "")
        + ". Many moves mean ElevenLabs merged people under one label.",
        "",
        f"Reviewed speaker corrections (data/fixes 'speaker'): {len(fixes['speaker'])}, "
        f"{edits.get('speaker_words_reassigned', 0)} words; turn-boundary fragments moved back: "
        f"{edits.get('boundaries_moved', 0)}.",
        "",
        f"Turns whose voice match is weak (similarity < {LOW_SIM}, or closer to another voice), worth a listen: "
        f"{len(weak)}" + (f" (the first {WEAK_MAX})" if len(weak) > WEAK_MAX else ""),
    ] + [f"- {mmss(t['start'])} ({t['start']:.1f} s) {t['name']} {t['sim']:.2f}"
         + (f"; closest other voice: {t['alt']} {t['alt_sim']:.2f}" if "alt" in t else "")
         for t in weak[:WEAK_MAX]] + [
        "",
        f"Speakers apparently saying their own name (likely mislabels): {len(named)}",
    ] + [f"- {x}" for x in named[:SELF_NAMED_MAX]] + [
        "",
        "## Words",
        "",
        f"- Flags: {near} near-misses of listed terms, {low} low-confidence rare words.",
        f"- Fixed: {len(fixes['fix'])}"
        + ("".join(f"\n  - {f['from']} → {f['to']} ({f.get('why', '')})" for f in fixes["fix"])),
        f"- Corrected from the read-through (text-based): {len(fixes['replace'])}"
        + ("".join(f"\n  - {r['from']} → {r['to']} ({r.get('why', '')})" for r in fixes["replace"])),
        f"- Marked uncertain `[?]`: {len(fixes['uncertain'])} "
        f"({100 * len(fixes['uncertain']) / max(len(words), 1):.2f}% of words).",
        f"- Listed terms heard: {sum(1 for c in heard.values() if c)} of {len(terms)} "
        "(most listed terms are for other episodes; this shows which ones came up).",
    ]
    if fixes["open_questions"]:
        lines += ["", "## Open questions", ""] + [f"- {q}" for q in fixes["open_questions"]]
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "reports" / f"{n:02d}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
