"""Add new episodes, start to finish: feed, audio, art, transcript, speakers, site.

Run:  python scripts/add_episode.py            every episode in the feed that has no transcript yet (except those
                                               in data/hidden.json)
      python scripts/add_episode.py 23         just episode 23 (re-runs every step for it, except a
                                               transcription it already has)
      python scripts/add_episode.py 23 --yes   the same, without asking before the paid transcription
      python scripts/add_episode.py --site     only rebuild the site data (after editing fixes or clips)

It runs the other scripts in order and stops at the first problem, with what to do next:
  1. fetch_feed.py        new episodes into data/episodes.json; the audio still needed into audio/
  2. (check)              the guest is in data/guests.json (and data/affiliations.json): the one thing a person
                          must add, because the feed doesn't say who the guest is in a machine-readable way.
                          Then, if an episode needs transcribing: the API key is checked, the audio minutes and
                          the estimated cost are shown, and it asks "Transcribe? [y/N]" (--yes answers yes)
  3. fetch_art.py         the episode's artwork, then make_thumbs.py
  4. transcribe.py        ElevenLabs speech-to-text, the one paid step (about $0.27 per audio hour)
  5. name_speakers.py     the hosts by their saved voiceprints, everyone else as the guest
  6. build_episode.py     the transcript: out/episodes/<NN>.json, plus .md, .vtt and .srt copies
  7. flag.py              words the transcriber was unsure of, for review
  8. the site data        build_site_data.py, build_explainers.py, build_mentions.py, build_quotes.py

The transcript is usable as soon as this finishes. Reviewing it makes it better: see "Reviewing a new episode"
in CLAUDE.md (in Claude Code, just ask "review episode 23").
"""
import argparse
import subprocess
import sys

import common
from common import AUDIO, ROOT, rel

PY = sys.executable
SITE_STEPS = ["build_site_data.py", "build_explainers.py", "build_mentions.py", "build_quotes.py"]
# ElevenLabs, late 2026: scribe_v2 $0.22 per audio hour, plus $0.05 for key terms.
USD_PER_HOUR = 0.27


def run(script, *args):
    """Run scripts/<script>; stop everything if it fails."""
    print(f"\n$ python scripts/{script} {' '.join(map(str, args))}".rstrip(), flush=True)
    r = subprocess.run([PY, str(ROOT / "scripts" / script), *map(str, args)], cwd=ROOT)
    if r.returncode:
        sys.exit(f"\n{script} failed (exit {r.returncode}). Fix the problem above, then run add_episode.py again "
                 "(an episode already transcribed is not transcribed, or paid for, again).")


def has_transcript(n):
    return (ROOT / "out" / "episodes" / f"{n:02d}.json").exists()


def needs_transcribing(n):
    return not (ROOT / "out" / "raw" / f"{n:02d}.json").exists()


def check_guest(ep, guests):
    """The guest list must name this episode; [] means the hosts alone."""
    if str(ep["n"]) in guests:
        return
    sys.exit(f"""
Episode {ep['n']} ("{ep['title']}") is not in data/guests.json yet. Add one line and run this again:
    "{ep['n']}": ["First Last"]         (the guest's name as it should appear; ["A", "B"] for two guests)
    "{ep['n']}": []                     (Charles and Keith on their own)
and, for a guest, their affiliation in data/affiliations.json:
    "{ep['n']}": "University of Somewhere"
Optional but worth it: data/terms/{ep['n']:02d}.txt, the names and jargon this episode uses, one per line,
so the transcriber spells them right (see CLAUDE.md, "Adding an episode").""")


def minutes(duration):
    """The feed's itunes:duration ("1:02:47", "62:47" or seconds) in minutes; None if unreadable."""
    try:
        parts = [float(x) for x in str(duration).split(":")]
    except ValueError:
        return None
    return sum(x * 60 ** k for k, x in enumerate(reversed(parts))) / 60


def confirm_cost(eps, yes):
    """Check the API key, show what transcribing will cost, and ask (unless --yes)."""
    common.secret("ELEVENLABS_API_KEY")   # exits now, clearly, rather than after the art and the checks
    mins = [minutes(e.get("duration")) for e in eps]
    known = sum(m for m in mins if m is not None)
    nums = ", ".join(str(e["n"]) for e in eps)
    note = "" if all(m is not None for m in mins) else " (plus episodes whose length the feed doesn't give)"
    print(f"\nTo transcribe: episode{'s' if len(eps) > 1 else ''} {nums}, {known:.0f} min of audio{note}. "
          f"Estimated cost: ${known / 60 * USD_PER_HOUR:.2f} (about ${USD_PER_HOUR} per audio hour).")
    if yes:
        return
    try:
        answer = input("Transcribe? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        sys.exit("Not transcribed. Run this again when ready (add --yes to skip the question).")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("n", type=int, nargs="*", help="episode numbers (default: every episode without a transcript)")
    p.add_argument("--site", action="store_true", help="only rebuild the site data")
    p.add_argument("--yes", action="store_true", help="transcribe without asking (it costs money)")
    a = p.parse_args()

    if a.site:
        for step in SITE_STEPS:
            run(step)
        print("\nSite data rebuilt. Preview: python site/serve.py, then open http://localhost:8770/web/")
        return

    run("fetch_feed.py", *a.n)   # with numbers, only their audio; else the audio of every untranscribed episode
    eps = {e["n"]: e for e in common.episodes()}
    todo = a.n or [n for n in sorted(eps) if not has_transcript(n) and n not in common.hidden()]
    missing = [n for n in todo if n not in eps]
    if missing:
        sys.exit(f"Not in the feed: {missing}")
    if not todo:
        print("\nEvery episode already has a transcript. Nothing to add.")
        return
    print(f"\nAdding episode{'s' if len(todo) > 1 else ''} {', '.join(map(str, todo))}")

    guests = common.guests()
    for n in todo:
        check_guest(eps[n], guests)
    new = [eps[n] for n in todo if needs_transcribing(n)]
    for ep in new:
        if not (AUDIO / ep["audio_file"]).exists():
            sys.exit(f"{rel(AUDIO / ep['audio_file'])} is missing (the download failed). "
                     f"Run python scripts/fetch_feed.py {ep['n']} again.")
    if new:
        confirm_cost(new, a.yes)
    run("fetch_art.py", *todo)
    run("make_thumbs.py")
    if new:
        run("transcribe.py", *(e["n"] for e in new))
    for n in todo:
        run("name_speakers.py", n)
        run("build_episode.py", n)
        run("flag.py", n)
    for step in SITE_STEPS:
        run(step)

    n = todo[0]
    print(f"""
Done: episode{'s' if len(todo) > 1 else ''} {', '.join(map(str, todo))} {'are' if len(todo) > 1 else 'is'} on the site.
Preview:  python site/serve.py   then open http://localhost:8770/web/
Next (optional, makes the transcript better): review the flagged words and speakers.
  In Claude Code: "review episode {n}"
  By hand: python scripts/show_flags.py {n}, python scripts/report.py {n}, then edit data/fixes/{n:02d}.json
Then rebuild, one command after the other:
  python scripts/build_episode.py {n}
  python scripts/add_episode.py --site""")


if __name__ == "__main__":
    main()
