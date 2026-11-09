"""Merge term lists for one episode and check them against ElevenLabs keyterm limits.

Run:  python scripts/build_terms.py 16
Merges data/terms/core.txt, people.txt, companies.txt and <NN>.txt, in that order, dropping repeats
(case-insensitive). Lines starting with # are comments. Prints the merged list; returns it when imported.
"""
import sys

import common
from common import ROOT, rel

TERMS = ROOT / "data" / "terms"
BAD = set("<>{}[]\\")
MAX_CHARS, MAX_WORDS, MAX_TERMS = 49, 5, 1000   # ElevenLabs' keyterm limits


def read(name, required=False):
    """The terms in data/terms/<name>, one per line. A missing file is [] unless required."""
    p = TERMS / name
    if not p.exists():
        if required:
            sys.exit(f"{rel(p)} is missing: every episode's key terms start from it")
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8-sig").splitlines() if l.strip() and not l.startswith("#")]


def terms_for(n):
    """The merged keyterms for episode n; exits naming the file if one breaks the ElevenLabs limits."""
    files = ["core.txt", "people.txt", "companies.txt", f"{int(n):02d}.txt"]
    merged, seen = [], set()
    for f in files:
        for t in read(f, required=f != files[-1]):
            if t.lower() in seen:
                continue
            if len(t) > MAX_CHARS or len(t.split()) > MAX_WORDS or BAD & set(t):
                sys.exit(f"data/terms/{f}: {t!r} breaks the ElevenLabs keyterm limits (at most {MAX_CHARS} "
                         f"characters and {MAX_WORDS} words, none of < > {{ }} [ ] \\). Shorten or remove it.")
            seen.add(t.lower())
            merged.append(t)
    if len(merged) > MAX_TERMS:
        sys.exit(f"episode {n} has {len(merged)} keyterms; ElevenLabs takes at most {MAX_TERMS}. "
                 f"Trim data/terms/{int(n):02d}.txt or the shared lists.")
    return merged


def main():
    args = common.parser(__doc__).parse_args()
    t = terms_for(args.n)
    print(f"{len(t)} keyterms")
    print("; ".join(t))


if __name__ == "__main__":
    main()
