"""Cut the picture a labelling task is answered on out of its page.

    seed/.venv/bin/python seed/extract_image.py cam11-t1-s2

A map- or diagram-labelling group cannot be published without the picture the
letters sit on -- `publish_blockers()` says so in as many words -- and the
picture is the one thing on the page a vision model cannot hand back. It reads
text; this has to produce bytes.

**Found by its border, not by asking.** The picture is printed inside a drawn
box, and a scanned page renders that box as long runs of dark pixels: two
horizontal rules spanning most of the width and two vertical ones spanning most
of the height. On Cambridge 11's Test 1 map they land at 20% and 79% of the
page down, 7% and 75% across, which is the box to the pixel. A bounding box
asked of a model would be a guess in the same place.

The page's own edges are excluded first. These scans carry a solid black bar
top and bottom -- an artefact of the copier, wider and darker than any rule on
the page -- and they are the outermost horizontal runs on every sheet.

`page.get_images()` is no use here: the page IS one image, so extracting it
returns the whole sheet rather than the map.
"""

import argparse
import json
import pathlib
import sqlite3
import sys

import numpy as np
import pymupdf

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
WORK = SEED / "work"

#: How much of the width a row must be dark across to count as a rule. Text
#: lines never come close; a printed border always does.
ROW_INK = 0.40
COLUMN_INK = 0.30
#: The copier's black bars live here. Nothing that matters does.
EDGE = 0.06
#: A box smaller than this is a table cell or an underline, not a picture.
MIN_WIDTH, MIN_HEIGHT = 0.25, 0.15
#: Rendered big enough to read the letters printed on the map.
DPI = 200
#: A little air, so the border itself is not shaved off.
MARGIN_PX = 6


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, start = [], None
    for i, on in enumerate(mask):
        if on and start is None:
            start = i
        elif not on and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def find_box(page: pymupdf.Page) -> tuple[float, float, float, float] | None:
    """The picture's box on this page, as fractions of it, or None."""
    pix = page.get_pixmap(dpi=110)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    dark = img[:, :, :3].mean(axis=2) < 128
    height, width = dark.shape

    rows = [(a, b) for a, b in runs(dark.mean(axis=1) > ROW_INK)
            if EDGE * height < a and b < (1 - EDGE) * height]
    columns = [(a, b) for a, b in runs(dark.mean(axis=0) > COLUMN_INK)
               if EDGE * width < a and b < (1 - EDGE) * width]
    if not rows or not columns:
        return None

    top, bottom = rows[0][0], rows[-1][1]
    left, right = columns[0][0], columns[-1][1]
    box = (left / width, top / height, right / width, bottom / height)
    if box[2] - box[0] < MIN_WIDTH or box[3] - box[1] < MIN_HEIGHT:
        return None
    return box


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT s.*, d.rel_path pdf FROM section s JOIN document d ON d.id = s.document_id "
        "WHERE s.id = ?", (args.section_id,)).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"{args.section_id} is not in the catalogue")

    work = WORK / args.section_id
    built = work / "questions.json"
    if not built.exists():
        raise SystemExit(f"{args.section_id}: run build_questions.py first")
    payload = json.loads(built.read_text())

    wants = [i for i, g in enumerate(payload["groups"])
             if g["type"] in ("map_labelling", "diagram_labelling")]
    if not wants:
        print(f"{args.section_id}: no labelling group, nothing to cut")
        return 0

    pages = json.loads(row["question_pages"] or "[]")
    doc = pymupdf.open(MATERIALS / row["pdf"])
    found = 0
    for group_index in wants:
        picture = None
        for page_index in pages:
            box = find_box(doc[page_index])
            if box is None:
                continue
            page = doc[page_index]
            rect = pymupdf.Rect(box[0] * page.rect.width, box[1] * page.rect.height,
                                box[2] * page.rect.width, box[3] * page.rect.height)
            out = work / f"image-group{group_index}.png"
            pixmap = page.get_pixmap(dpi=DPI, clip=rect)
            pixmap.save(out)
            picture = {"path": out.name, "page_index": page_index,
                       "box": [round(v, 4) for v in box],
                       "width": pixmap.width, "height": pixmap.height}
            print(f"  group {group_index}: page {page_index}, box "
                  f"{box[0]:.2f},{box[1]:.2f}-{box[2]:.2f},{box[3]:.2f} -> "
                  f"{out.name} ({pixmap.width}x{pixmap.height})")
            break
        if picture is None:
            print(f"  group {group_index}: no bordered picture found on pages {pages}",
                  file=sys.stderr)
            continue
        payload["groups"][group_index]["picture"] = picture
        found += 1

    doc.close()
    built.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if found == len(wants) else 1


if __name__ == "__main__":
    sys.exit(main())
