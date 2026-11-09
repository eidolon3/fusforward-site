"""Transcribe episodes with ElevenLabs scribe_v2 (keyterms, speaker labels, word timestamps).

Run:  python scripts/transcribe.py 16          (or several numbers)
      python scripts/transcribe.py --all       (every episode not transcribed yet)
Needs ELEVENLABS_API_KEY (in .env or the environment) and the audio in audio/ (fetch_feed.py).
Output: out/raw/<NN>.json (the API response, untouched).
The number of speakers is left to the model: setting num_speakers made it merge both hosts with the guest.
Episodes that already have out/raw/<NN>.json are skipped; delete the file to redo one. Each upload costs money
(about $0.27 per audio hour).
"""
import argparse
import sys
import time

import requests

import common
from build_terms import terms_for
from common import AUDIO, ROOT, rel

RAW = ROOT / "out" / "raw"
URL = "https://api.elevenlabs.io/v1/speech-to-text"
UPLOAD_TIMEOUT = 3600   # seconds; an hour-long episode can take minutes to process


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("episodes", nargs="*", type=int, metavar="N", help="episode numbers")
    p.add_argument("--all", action="store_true", help="every episode in data/episodes.json")
    a = p.parse_args()
    if bool(a.episodes) == a.all:
        p.error("give episode numbers, or --all")
    episodes = common.episodes()
    want = {e["n"] for e in episodes} if a.all else set(a.episodes)
    for n in sorted(want - {e["n"] for e in episodes}):
        print(f"WARNING: episode {n} is not in data/episodes.json; skipped")

    todo = []
    for e in episodes:
        if e["n"] in want:
            out = RAW / f"{e['n']:02d}.json"
            if out.exists():
                print(f"ep {e['n']}: {rel(out)} exists; skipped (delete it to redo)")
            else:
                todo.append(e)
    for ep in todo:  # all audio checked before anything is uploaded (and paid for)
        if not (AUDIO / ep["audio_file"]).exists():
            sys.exit(f"{rel(AUDIO / ep['audio_file'])} is missing: run python scripts/fetch_feed.py {ep['n']}")
    if not todo:
        return
    key = common.secret("ELEVENLABS_API_KEY")
    RAW.mkdir(parents=True, exist_ok=True)

    failed = []
    for ep in todo:
        n = ep["n"]
        terms = terms_for(n)
        form = [
            ("model_id", "scribe_v2"),
            ("diarize", "true"),
            ("timestamps_granularity", "word"),
            ("tag_audio_events", "true"),
            ("language_code", "en"),
        ] + [("keyterms", t) for t in terms]
        print(f"ep {n}: uploading {ep['audio_file']} with {len(terms)} keyterms ...", flush=True)
        t0 = time.time()
        try:
            with open(AUDIO / ep["audio_file"], "rb") as fh:
                r = requests.post(URL, headers={"xi-api-key": key}, data=form,
                                  files={"file": (ep["audio_file"], fh, "audio/mpeg")}, timeout=UPLOAD_TIMEOUT)
        except requests.ConnectionError as e:
            sys.exit(f"Could not reach ElevenLabs ({e.__class__.__name__}). Check your internet connection.")
        except requests.Timeout:
            sys.exit(f"ep {n}: ElevenLabs did not answer within {UPLOAD_TIMEOUT // 60} minutes. Try again later.")
        if not r.ok:
            hint = " The API key was refused: check ELEVENLABS_API_KEY in .env." if r.status_code in (401, 403) else ""
            print(f"ep {n}: ElevenLabs answered HTTP {r.status_code}: {r.text[:500]}{hint}")
            failed.append(n)
            continue
        try:
            words = [w for w in r.json()["words"] if w["type"] == "word"]
        except (ValueError, KeyError, TypeError):
            print(f"ep {n}: ElevenLabs' answer has no word list; not saved. It began: {r.text[:300]}")
            failed.append(n)
            continue
        (RAW / f"{n:02d}.json").write_text(r.text, encoding="utf-8")
        print(f"ep {n}: {len(words)} words in {time.time() - t0:.0f}s")
    if failed:
        sys.exit(f"failed: {', '.join(map(str, failed))}")


if __name__ == "__main__":
    main()
