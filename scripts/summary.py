"""One table for the whole series, from the master files and intermediate files.

Run:  python scripts/summary.py
Output: out/reports/summary.md
"""
import argparse

import common
from common import NARRATOR, ROOT

OUT = ROOT / "out"


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    rows, tot = [], {"min": 0, "words": 0, "fix": 0, "unc": 0}
    masters = sorted((p for p in (OUT / "episodes").glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
    for p in masters:
        m = common.load_json(p)
        n = m["n"]
        spk = common.load_json(OUT / "speakers" / f"{n:02d}.json")
        fx = common.load_fixes(n)
        words = sum("x" not in w for w in m["words"])
        talk = {}  # from the master, so reviewed speaker corrections count
        for t in m["turns"]:
            talk[m["speakers"][t["p"]]] = talk.get(m["speakers"][t["p"]], 0) + t["e"] - t["s"]
        people = ", ".join(f"{k if k.startswith('Unknown') else k.split()[-1]} {v / 60:.1f}"
                           for k, v in sorted(talk.items(), key=lambda x: -x[1]) if k != NARRATOR)
        moved = sum(v for k, v in spk["turns_moved"].items() if NARRATOR not in k)
        ed = m.get("edits", {})
        rows.append(f"| {n} | {m['duration_s'] / 60:.0f} | {words:,} | {people} | {moved} | {len(fx['speaker'])} | "
                    f"{ed.get('boundaries_moved', 0)} | {len(fx['fix'])} | {len(fx['replace'])} | {len(fx['uncertain'])} |")
        tot["min"] += m["duration_s"] / 60
        tot["words"] += words
        tot["fix"] += len(fx["fix"]) + len(fx["replace"])
        tot["unc"] += len(fx["uncertain"])

    lines = [
        "# FUS Forward transcripts: quality summary",
        "",
        f"{len(rows)} episodes · {tot['min'] / 60:.1f} h · {tot['words']:,} words · "
        f"{tot['fix']} word fixes and corrections · {tot['unc']} words marked uncertain "
        f"({100 * tot['unc'] / max(tot['words'], 1):.2f}%)",
        "",
        "| Ep | Min | Words | Talk time (min) | Turns moved by voice check | Speaker reviews | Boundaries moved | Fixes | Audit corrections | Uncertain |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ] + rows
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "reports" / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
