"""Smaller copies of the episode artwork, for the places that show it small (pages pick one with srcset).

Run:  python scripts/make_thumbs.py          (after fetch_art.py; quick, safe to re-run)
Output: site/assets/ep/sm/<NN>.jpg (160 x 90) and site/assets/ep/md/<NN>.jpg (320 x 180), from site/assets/ep/<NN>.jpg
(640 x 360). A source of another shape is cropped to 16:9 around its centre, not stretched. Only images that are
missing or older than their source are written.
"""
import argparse

from PIL import Image, ImageOps

from common import ROOT, rel

ART = ROOT / "site" / "assets" / "ep"
SIZES = {"sm": (160, 90), "md": (320, 180)}


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    made = 0
    for src in sorted(ART.glob("*.jpg")):
        im = None
        for name, size in SIZES.items():
            out = ART / name / src.name
            if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
                continue
            out.parent.mkdir(exist_ok=True)
            im = im or Image.open(src).convert("RGB")
            ImageOps.fit(im, size, Image.LANCZOS).save(out, "JPEG", quality=84, optimize=True, progressive=True)
            made += 1
    print(f"{made} thumbnails written to {rel(ART)}/sm and /md")


if __name__ == "__main__":
    main()
