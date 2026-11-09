"""Print episodes' flags compactly, for review.

Run:  python scripts/show_flags.py 16 [17 ...]
Reads out/flags/<NN>.json (flag.py). One line per flag:
  kind  raw word index+span  start in seconds  ~term it resembles (n) or logprob (l)  | "text" | context
  n 487+2 @1798.43 ~acoustic lens | "acoustics, then" | ... the words around it ...
For data/fixes/<NN>.json: a "fix" takes the index, span and text ("i": 487, "k": 2, "from": "acoustics, then");
a "replace", "uncertain" or "speaker" entry takes the start as its "near_s".
"""
import argparse
import sys

import common
from common import ROOT, rel


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("episodes", nargs="+", type=int, metavar="N", help="episode numbers")
    for n in p.parse_args().episodes:
        path = ROOT / "out" / "flags" / f"{n:02d}.json"
        flags = common.load_json(path, missing_ok=True)
        if flags is None:
            sys.exit(f"{rel(path)} is missing: run python scripts/flag.py {n} first")
        if any("s" not in f for f in flags):
            sys.exit(f"{rel(path)} was written by an older flag.py: run python scripts/flag.py {n} again")
        print(f"===== ep {n}: {len(flags)} flags")
        for f in flags:
            tag = f"~{f['term']}" if f["kind"] == "near_miss" else f"lp{f['logprob']}"
            print(f"{f['kind'][0]} {f['i']}+{f['k']} @{f['s']:.2f} {tag} | \"{f['text']}\" | {f['context']}")


if __name__ == "__main__":
    main()
