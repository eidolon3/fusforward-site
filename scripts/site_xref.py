""""Elsewhere in the series": for each episode with guests, the other episodes that mention a guest by name.
build_site_data.py calls elsewhere() and stores each episode's result as x in its ep/NN.js, so an episode page has
it without downloading the search index.

  elsewhere(eps, gloss, rows, masters) -> {n: [[a, [[s, who, t], ...], snippet_html], ...]}
      eps, gloss, rows: the FF_EPISODES, FF_GLOSSARY and FF_SEARCH lists; masters: {n: master transcript}.
      One item per other episode a that names a guest, most mentions first. s: the moment (a glossary hit, or the
      start of the search chunk that names the guest), who: the speaker, t: the second to play (the start of the
      word that names the guest), snippet_html: the first mention's words with the name in <mark>.

A guest listed in the glossary as a person is found by its hits; any other guest by searching the search chunks for
the full name in any case, or a surname of five letters or more capitalised as written, so a guest called "Young"
or "Brown" doesn't match every "young" or "brown". Mentions by the intro narrator and mentions in the episode itself
are left out. Word boundaries (W, B below) count only ASCII letters, digits and _ as word characters.

page_norm() and fold() mirror norm() and fold() in site/web/index.html, which match guest names against the
glossary on the page; change them together.
"""
import re
import unicodedata

from common import NARRATOR

W = "A-Za-z0-9_"                                     # an ASCII word character
B = rf"(?:(?<=[{W}])(?![{W}])|(?<![{W}])(?=[{W}]))"  # a boundary between an ASCII word character and anything else


def fold(s):
    """NFD, with the combining marks U+0300-U+036F dropped: "François" -> "Francois"."""
    return re.sub("[\u0300-\u036f]", "", unicodedata.normalize("NFD", s))


def page_norm(s):
    """Folded, lower case, curly apostrophes made straight."""
    return re.sub("[\u2018\u2019]", "'", fold(s).lower())


def re_esc(s):
    return re.sub(r"[.*+?^${}()|[\]\\]", lambda m: "\\" + m.group(0), s)


def esc(s):
    return re.sub(r'[&<>"]', lambda m: {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[m.group(0)], str(s))


def js_split_ws(s):
    return re.split(r"\s+", s)


def name_matcher(g):
    """text -> bool: whether text names guest g (the full name in any case, or a surname of five letters or more
    capitalised as written)."""
    full = re.compile(B + re_esc(page_norm(g)).replace("-", "[- ]?") + B)
    sur = js_split_ws(fold(g).strip())[-1]
    cap = re.compile(B + re_esc(sur[:1].upper() + sur[1:]).replace("-", "[- ]?") + B) if len(sur) >= 5 else None
    straight = lambda t: re.sub("[‘’]", "'", fold(t))   # page_norm() without the lower case
    return lambda t: bool(full.search(page_norm(t)) or (cap and cap.search(straight(t))))


def last_at(a, x):
    lo, hi, r = 0, len(a) - 1, 0
    while lo <= hi:
        m = (lo + hi) >> 1
        if a[m] <= x + .05:
            r, lo = m, m + 1
        else:
            hi = m - 1
    return r


def lower_bound(a, x):
    lo, hi = 0, len(a)
    while lo < hi:
        m = (lo + hi) >> 1
        if a[m] < x:
            lo = m + 1
        else:
            hi = m
    return lo


def cite_snip(row, name):
    words = js_split_ws(row[3])
    parts = [x for x in re.split(r"[\s-]+", page_norm(name)) if len(x) > 2]
    hit = [any(re.sub(r"[^a-z0-9'-]", "", page_norm(w)).startswith(p) for p in parts) for w in words]
    f = max(0, hit.index(True) if True in hit else -1)
    lo = max(0, min(f - 10, len(words) - 26))
    hi = min(len(words), lo + 26)
    return ("…" if lo else "") + " ".join(f"<mark>{esc(w)}</mark>" if hit[lo + k] else esc(w)
                                          for k, w in enumerate(words[lo:hi])) + ("…" if hi < len(words) else "")


def exact_time(master, row, off):
    """The start of the off-th spoken word of the row's speaker from the row's start (the row's start if none)."""
    _, s, who, _ = row
    W_, sp = master["words"], master["speakers"]
    starts = [w["s"] for w in W_]
    i, k = lower_bound(starts, s - .005), 0
    while i < len(W_) and W_[i]["s"] < s + 120:
        w = W_[i]
        if "x" in w or sp[w["p"]] != who:
            i += 1
            continue
        if k == off:
            return w["s"]
        k += 1
        i += 1
    return s


def elsewhere(eps, gloss, rows, masters):
    rb, rs = {}, {}
    for ri, r in enumerate(rows):
        if r[0] not in rb:
            rb[r[0]], rs[r[0]] = ri, []
        rs[r[0]].append(r[1])
    row_at = lambda n, s: rb[n] + last_at(rs[n], s)
    # Each (episode, guest)'s mentions outside that episode.
    cite = {}
    for b in eps:
        for g in b["guests"]:
            ge = next((x for x in gloss if x["kind"] == "person" and page_norm(x["term"]) == page_norm(g)), None)
            lst = []
            if ge:
                lst = [{"a": a, "s": s, "who": who} for a, s, who in ge["hits"] if a != b["n"] and who != NARRATOR]
            else:
                named = name_matcher(g)
                for ri, r in enumerate(rows):
                    if r[0] != b["n"] and r[2] != NARRATOR and named(r[3]):
                        ws = js_split_ws(r[3])
                        idx = next((k for k, w in enumerate(ws) if named(w) or named(w + " ")), -1)
                        lst.append({"a": r[0], "s": r[1], "who": r[2], "ri": ri, "off": max(0, idx)})
            cite[(b["n"], g)] = lst
    out = {}
    for e in eps:
        if not e["guests"]:
            continue
        by = {}
        for name in e["guests"]:
            for x in cite.get((e["n"], name), []):
                by.setdefault(x["a"], []).append({**x, "name": name})
        groups = sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        res = []
        for a, xs in groups:
            xs = sorted(xs, key=lambda x: x["s"])
            x = xs[0]
            row = rows[x["ri"]] if "ri" in x else rows[row_at(a, x["s"])]
            res.append([a, [[y["s"], y["who"], exact_time(masters[a], rows[y["ri"]], y["off"]) if "ri" in y else y["s"]] for y in xs],
                        cite_snip(row, x["name"])])
        out[e["n"]] = res
    return out

