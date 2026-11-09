"""Fetch PubMed records (MEDLINE text): a guest's papers for building term lists, or papers mentioned on the show.

Run:  python scripts/fetch_pubmed.py 16 "Aubry JF[Author]"
      python scripts/fetch_pubmed.py --pmid 41072763 39190585
The first writes data/pubmed/<NN>.txt, then prints frequent coauthors (as "First Last") and recent titles.
It writes nothing when no record matches, and keeps an existing file that has more records than the new
answer (--force replaces it anyway).
--pmid appends those records to data/pubmed/mentioned.txt (the Show Notes papers, build_mentions.py), skipping
any already there.
"""
import argparse
import re
import sys
import time
import urllib.parse
from collections import Counter

from common import ROOT, http_get, rel

OUT = ROOT / "data" / "pubmed"
EU = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
RETMAX = 400
PAUSE_S = 0.4   # NCBI allows 3 requests a second without an API key
PMID = re.compile(r"^PMID- *(\d+)", re.M)
# A MEDLINE field runs until the next tag line: a tag of 2-4 capitals padded to 4 characters ("PG  - ", "FAU - ").
TITLE = re.compile(r"^TI  - (.+?)(?=\n[A-Z]{2,4} *- )", re.M | re.S)


def get(path, **params):
    """An E-utilities answer as text. Exits with a sentence when offline or when NCBI answers with an error."""
    # NCBI asks callers to name their tool, so heavy use can be traced to a project rather than blocked.
    url = EU + path + "?" + urllib.parse.urlencode({**params, "tool": "fusforward-transcripts"})
    try:
        text = http_get(url, timeout=60).decode("utf-8")
    except OSError as e:   # offline, DNS, timeouts, HTTP errors (urllib.error.URLError is an OSError)
        code = getattr(e, "code", None)
        sys.exit(f"PubMed answered HTTP {code} ({e.reason}). Try again in a minute." if code else
                 f"Could not reach PubMed ({getattr(e, 'reason', e)}). Check your internet connection.")
    err = re.search(r"<ERROR>(.*?)</ERROR>|\"error\"\s*:\s*\"([^\"]+)\"", text, re.S)
    if err or re.match(r"\s*<(!DOCTYPE )?html", text, re.I):
        sys.exit(f"PubMed answered with an error: {(err and (err.group(1) or err.group(2)) or text[:200]).strip()}")
    return text


def records(medline):
    """The MEDLINE records in a text, each without its surrounding blank lines."""
    return [r.strip("\n") for r in re.split(r"\n\s*\n", medline.replace("\r\n", "\n")) if PMID.search(r)]


def first_last(name):
    last, _, first = name.partition(", ")
    return f"{first} {last}".strip()


def guest_papers(n, query, force):
    found = get("esearch.fcgi", db="pubmed", term=query, retmax=RETMAX)
    count = re.search(r"<Count>(\d+)</Count>", found)
    if not count:
        sys.exit(f"PubMed's search gave no count; it answered: {found[:200]}")
    ids = re.findall(r"<Id>(\d+)</Id>", found)
    if not ids:
        sys.exit(f"no PubMed records match {query!r}: check the spelling (e.g. \"Aubry JF[Author]\"). Nothing written.")
    if int(count.group(1)) > RETMAX:
        print(f"WARNING: {count.group(1)} records match; only the first {RETMAX} are fetched. Narrow the query.")
    time.sleep(PAUSE_S)
    medline = get("efetch.fcgi", db="pubmed", id=",".join(ids), rettype="medline", retmode="text")
    recs = records(medline)
    dest = OUT / f"{n:02d}.txt"
    had = len(records(dest.read_text(encoding="utf-8"))) if dest.exists() else 0
    if had > len(recs) and not force:
        print(f"WARNING: {rel(dest)} has {had} records, this answer only {len(recs)}; kept the old file "
              "(run again with --force to replace it).")
    else:
        OUT.mkdir(parents=True, exist_ok=True)
        dest.write_text(medline, encoding="utf-8")
        print(f"ep {n}: {len(recs)} records -> {rel(dest)}")

    fau = Counter(m for r in recs for m in re.findall(r"^FAU - (.+)$", r, re.M))
    titles = [re.sub(r"\s+", " ", m) for r in recs for m in TITLE.findall(r)]
    # The most frequent author of a guest's own papers is the guest: [1:] leaves them out.
    print("  coauthors:", "; ".join(f"{first_last(k)} ({v})" for k, v in fau.most_common(30)[1:] if v >= 2))
    for t in titles[:8]:
        print("  -", t[:110])


def mentioned(pmids):
    dest = OUT / "mentioned.txt"
    text = dest.read_text(encoding="utf-8") if dest.exists() else ""
    have = set(PMID.findall(text))
    new = [p for p in dict.fromkeys(pmids) if p not in have]
    for p in sorted(set(pmids) & have):
        print(f"PMID {p}: already in {rel(dest)}")
    if not new:
        return
    recs = records(get("efetch.fcgi", db="pubmed", id=",".join(new), rettype="medline", retmode="text"))
    got = {PMID.search(r).group(1): r for r in recs}
    for p in new:
        if p not in got:
            print(f"PMID {p}: PubMed has no such record; check the number")
    add = [got[p] for p in new if p in got]
    if add:
        dest.write_text((text.rstrip("\n") + "\n\n" if text.strip() else "") + "\n\n".join(add) + "\n", encoding="utf-8")
        for r in add:
            title = TITLE.search(r)
            title = re.sub(r"\s+", " ", title.group(1))[:90] if title else "no title"
            print(f"PMID {PMID.search(r).group(1)}: added to {rel(dest)} ({title})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("n", type=int, nargs="?", help="episode number")
    p.add_argument("query", nargs="?", help='a PubMed query, e.g. "Aubry JF[Author]"')
    p.add_argument("--pmid", nargs="+", metavar="ID", help="append these PubMed records to data/pubmed/mentioned.txt")
    p.add_argument("--force", action="store_true", help="replace data/pubmed/<NN>.txt even with fewer records")
    a = p.parse_args()
    if a.pmid:
        if a.n is not None:
            p.error("--pmid takes PubMed ids only, no episode or query")
        bad = [x for x in a.pmid if not x.isdigit()]
        if bad:
            p.error(f"a PMID is a number, not {', '.join(bad)}")
        mentioned(a.pmid)
    elif a.n is None or not a.query:
        p.error('give an episode number and a query, e.g. 16 "Aubry JF[Author]", or --pmid ID ...')
    else:
        guest_papers(a.n, a.query, a.force)


if __name__ == "__main__":
    main()
