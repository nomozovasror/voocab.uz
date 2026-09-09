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

**How dark is dark is asked of the page, not assumed.** The first version
thresholded at a fixed grey and it read one scan's contrast as a law: Cambridge
13's sheets are printed light, only 1.3% of their pixels fall below that line
against Cambridge 11's 6.9%, and their borders are grey rather than black. Seven
maps came back "no bordered picture found" on pages that plainly have one. The
threshold is now placed between the page's own paper and its own darkest ink,
which leaves the boxes that already worked exactly where they were.

The page's own edges are excluded first. These scans carry a solid black bar
top and bottom -- an artefact of the copier, wider and darker than any rule on
the page -- and they are the outermost horizontal runs on every sheet.

**Some maps have no border at all.** Cambridge 12, 15 and 18 print theirs as
bare line art on open paper, and there is no box to find because none was
drawn. Those are found the other way round -- not by the frame around the ink
but by the ink itself. A page of this book is body text at a very regular
pitch: a line stands about 1.1% of the sheet tall with 1.5% to 3% of white
between it and the next. A figure is one unbroken mass 27% to 33% tall, and the
pieces around it that belong to it -- its title, the road name along its foot --
sit within 0.6% of it, half the distance to the nearest line of prose. So the
tallest run of inked rows is taken and then grown through gaps too small to be
a line break. That separates the figure from the numbered questions under it
without knowing anything about either.

This is the fallback, not the rule: where a border exists it is the better
evidence, because it is where the book itself says the picture ends.

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
#: Where to put the ink/paper line, as a fraction of the distance from the
#: page's paper down to its darkest ink. 0.40 is comfortably below the greys a
#: light scan prints a border in, and comfortably above the anti-aliased fringe
#: of body text -- which must NOT count, or every line of prose becomes a rule.
INK_LEVEL = 0.40
#: Paper is what most of the sheet is; ink is the darkest of it. Both read off
#: percentiles rather than min/max, so one speck of copier grit sets nothing.
PAPER_PCT, INK_PCT = 90, 0.3
#: For the borderless search. A row counts as inked at all above ROW_ANY, and
#: a column within the found band above COLUMN_ANY -- both far below the
#: thresholds a *rule* has to clear. Runs closer together than MERGE_GAP are one
#: figure: measured, a line break is never under 1.2% of the page and a figure's
#: own parts are never over 0.6%, so 0.8% sits in the middle of a real gap.
ROW_ANY, COLUMN_ANY, MERGE_GAP = 0.005, 0.02, 0.008
#: The same idea sideways, and it has to be far looser: a figure really does
#: have 5% of white inside it between a compass rose and the box beside it,
#: where the binding shadow down one edge of a scan stands 15% clear of
#: anything real. Without this the crop stretches to the sheet's edge to take
#: in a grey line the copier left.
COLUMN_GAP = 0.08


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


def grow(spans: list[tuple[int, int]], gap: float) -> tuple[int, int]:
    """The longest span, extended over every neighbour within `gap` of it."""
    core = max(range(len(spans)), key=lambda i: spans[i][1] - spans[i][0])
    start, end = spans[core]
    for a, b in reversed(spans[:core]):
        if start - b > gap:
            break
        start = a
    for a, b in spans[core + 1:]:
        if a - end > gap:
            break
        end = b
    return start, end


def ink(page: pymupdf.Page) -> np.ndarray:
    """Which pixels of the page are ink, decided against the page's own paper."""
    pix = page.get_pixmap(dpi=110)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = img[:, :, :3].mean(axis=2)
    paper = np.percentile(grey, PAPER_PCT)
    darkest = np.percentile(grey, INK_PCT)
    return grey < paper - INK_LEVEL * (paper - darkest)


def find_block(page: pymupdf.Page) -> tuple[float, float, float, float] | None:
    """The biggest mass of ink on the page, for figures printed without a box."""
    dark = ink(page)
    height, width = dark.shape
    bands = [(a, b) for a, b in runs(dark.mean(axis=1) > ROW_ANY)
             if EDGE * height < a and b < (1 - EDGE) * height]
    if not bands:
        return None

    top, bottom = grow(bands, MERGE_GAP * height)

    columns = runs(dark[top:bottom].mean(axis=0) > COLUMN_ANY)
    if not columns:
        return None
    left, right = grow(columns, COLUMN_GAP * width)
    box = (left / width, top / height, right / width, bottom / height)
    if box[2] - box[0] < MIN_WIDTH or box[3] - box[1] < MIN_HEIGHT:
        return None
    return box


def find_box(page: pymupdf.Page) -> tuple[float, float, float, float] | None:
    """The picture's box on this page, as fractions of it, or None."""
    dark = ink(page)
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
        # A drawn border first, on the earliest page that has one. Only if no
        # page does is the ink itself asked, and then across every page, taking
        # the tallest mass -- the map's own sheet beats the one holding the
        # question list, which has nothing on it but prose.
        hit = next(((i, box, "border") for i in pages
                    if (box := find_box(doc[i])) is not None), None)
        if hit is None:
            blocks = [(i, box) for i in pages if (box := find_block(doc[i])) is not None]
            if blocks:
                i, box = max(blocks, key=lambda pair: pair[1][3] - pair[1][1])
                hit = (i, box, "ink")

        if hit is None:
            print(f"  group {group_index}: no picture found on pages {pages}",
                  file=sys.stderr)
            continue

        page_index, box, how = hit
        page = doc[page_index]
        rect = pymupdf.Rect(box[0] * page.rect.width, box[1] * page.rect.height,
                            box[2] * page.rect.width, box[3] * page.rect.height)
        # The border is part of the picture and is kept; a borderless figure is
        # cut exactly at its outermost ink, so it gets a little air instead.
        if how == "ink":
            rect += pymupdf.Rect(-MARGIN_PX, -MARGIN_PX, MARGIN_PX, MARGIN_PX)
        out = work / f"image-group{group_index}.png"
        pixmap = page.get_pixmap(dpi=DPI, clip=rect)
        pixmap.save(out)
        print(f"  group {group_index}: page {page_index}, {how} box "
              f"{box[0]:.2f},{box[1]:.2f}-{box[2]:.2f},{box[3]:.2f} -> "
              f"{out.name} ({pixmap.width}x{pixmap.height})")
        payload["groups"][group_index]["picture"] = {
            "path": out.name, "page_index": page_index,
            "box": [round(v, 4) for v in box],
            "width": pixmap.width, "height": pixmap.height}
        found += 1

    doc.close()
    built.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if found == len(wants) else 1


if __name__ == "__main__":
    sys.exit(main())
