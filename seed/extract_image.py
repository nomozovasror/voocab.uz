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


#: An image covering this much of the sheet IS the sheet. Every scan in this
#: corpus is one such image; a figure placed on top of one is smaller.
WHOLE_PAGE = 0.9


def overlaid(page: pymupdf.Page) -> tuple[float, float, float, float] | None:
    """The union of the images placed ON the page, or None if there are none.

    A scanned sheet is a single full-page image, and the ink rules below are
    the only way to find anything on it. Some pages are a scan with FIGURES
    laid over it -- IELTS Trainer 2's plan is three such images -- and where
    the typesetter placed one, its rectangle says where the figure is far
    better than any measurement of dark pixels.
    """
    boxes = []
    for image in page.get_images(full=True):
        for rect in page.get_image_rects(image[0]):
            area = (rect.width * rect.height) / (page.rect.width * page.rect.height)
            if 0 < area < WHOLE_PAGE:
                boxes.append((rect.x0 / page.rect.width, rect.y0 / page.rect.height,
                              rect.x1 / page.rect.width, rect.y1 / page.rect.height))
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


#: A text block of this many words or more is prose somebody reads, not a
#: label printed on a figure. "Main entrance", "Ellerslie Rd" and "Car Park"
#: are two; the shortest instruction on these pages is eight.
LABEL_WORDS = 6
#: How far outside the box a label may sit and still belong to it, as a
#: fraction of the page. A hair over a line of type: the map's own labels
#: touch its edge, and the prose around it is a paragraph away.
NEAR = 0.02


#: A column this much of which is ink is a drawn rule, not a run of letters.
#: The rule dividing Trainer's Test 5 Part 3 covers 88% of its band; the
#: densest column of the text beside it covers under a third.
RULE_INK = 0.7
#: How much taller one side's mass has to be than the other's before the rule
#: between them is taken as the edge of a figure. Twice, and at least this
#: much of the band: four lines of a question list stand 8% tall and the
#: diagram beside them 73%, so the margin is wide and the test does not have
#: to be fine.
FIGURE_MASS = 0.4


def tallest_run(part: np.ndarray) -> float:
    """The tallest unbroken run of inked rows, as a fraction of the height."""
    best = run = 0
    for inked in part.mean(axis=1) > 0.01:
        run = run + 1 if inked else 0
        best = max(best, run)
    return best / max(1, part.shape[0])


def split_at_rule(page: pymupdf.Page,
                  box: tuple[float, float, float, float],
                  ) -> tuple[float, float, float, float]:
    """The side of a drawn rule that holds the figure.

    The ink rule takes the tallest mass of dark ROWS, which on a page laid out
    two columns wide is both columns: IELTS Trainer's Test 5 Part 3 prints the
    questions down the left and the diagram down the right, and the cut held
    the questions as well.

    Where a book sets two columns it draws a line between them, and a drawn
    line is a column that is almost entirely ink -- 88% of the band here,
    against under a third for the densest column of type beside it. Which side
    is the figure is then the same question this module already answers
    vertically: type is a stack of short runs with white between them, a
    figure is one unbroken mass. Four lines of question list stand 8% of the
    band tall; the diagram beside them stands 73%.

    Nothing happens without a rule, without a clear winner, or on the many
    pages whose figure has a page-wide box of its own -- every Cambridge
    sheet.
    """
    dark = ink(page)
    height, width = dark.shape
    x0, y0, x1, y1 = box
    top, bottom = int(y0 * height), int(y1 * height)
    left, right = int(x0 * width), int(x1 * width)
    band = dark[top:bottom, left:right]
    if band.size == 0 or band.shape[0] < 2:
        return box

    cover = band.mean(axis=0)
    # Not at the edges: the figure's own frame is a rule too, and cutting at
    # it would keep nothing.
    inside = int(0.1 * band.shape[1])
    best: tuple[float, tuple[float, float, float, float]] | None = None
    for column in range(inside, band.shape[1] - inside):
        if cover[column] < RULE_INK:
            continue
        before, after = tallest_run(band[:, :column]), tallest_run(band[:, column:])
        keep, other = max(before, after), min(before, after)
        if keep < FIGURE_MASS or keep < 2 * other:
            continue
        at = (left + column) / width
        side = (at, y0, x1, y1) if after > before else (x0, y0, at, y1)
        if best is None or keep - other > best[0]:
            best = (keep - other, side)
    if best is None:
        return box

    # The band was measured across BOTH columns, so it stops where the widest
    # of them stops -- and the figure's own frame can run lower than the list
    # beside it. Trainer's Test 5 Part 3 lost the "H" off the bottom of its
    # diagram that way. Re-measured down the kept side, joining runs closer
    # together than a line break, which is the same rule `find_block` uses to
    # tell a figure's parts from the prose under it.
    at0, _, at1, _ = best[1]
    column = dark[:, int(at0 * width):int(at1 * width)]
    # NOT filtered by EDGE, unlike everywhere else. That margin exists to drop
    # the copier's black bar along the top and bottom of a scan, and it also
    # threw away the last two rows of this diagram's frame -- which sit at 93%
    # and 95% of the sheet, inside the margin. The bar is a thin run of its
    # own and is never the longest, so `grow` will not start from it; what
    # keeps it out is the gap, which is a fifth of the page here.
    bands = runs(column.mean(axis=1) > ROW_ANY)
    if not bands:
        return best[1]
    top, bottom = grow(bands, MERGE_GAP * height)
    return (at0, min(y0, top / height),
            at1, min(1 - EDGE / 3, max(y1, bottom / height)))


def grown_to_labels(page: pymupdf.Page,
                    box: tuple[float, float, float, float],
                    ) -> tuple[float, float, float, float]:
    """The box, opened out to hold the figure's own labels.

    A placed image is the drawing; the words printed over and around it are
    the page's text, and they are part of the picture as much as the lines
    are. IELTS Trainer 2's plan is captioned "Main entrance" along its top
    edge, just above where the image begins, and the intersection cut the
    caption in half.

    Only SHORT blocks, and only ones already touching the box or within a
    line of it -- which is every label a figure carries and none of the prose
    around it, since prose is both long and a paragraph away. Never shrinks:
    a label outside the box widens it, and a box with no labels near it comes
    back as it went in.
    """
    width, height = page.rect.width, page.rect.height
    x0, y0, x1, y1 = box
    for block in page.get_text("blocks"):
        if len(str(block[4]).split()) >= LABEL_WORDS:
            continue
        bx0, by0 = block[0] / width, block[1] / height
        bx1, by1 = block[2] / width, block[3] / height
        # Touching the box, or a line away from one of its edges, and lined
        # up with it on the other axis.
        across = bx0 < x1 + NEAR and bx1 > x0 - NEAR
        down = by0 < y1 + NEAR and by1 > y0 - NEAR
        if not (across and down):
            continue
        x0, y0 = min(x0, max(0.0, bx0)), min(y0, max(0.0, by0))
        x1, y1 = max(x1, min(1.0, bx1)), max(y1, min(1.0, by1))
    return (x0, y0, x1, y1)


def trim_to_picture(page: pymupdf.Page,
                    box: tuple[float, float, float, float],
                    ) -> tuple[float, float, float, float]:
    """The part of the ink box that a placed figure agrees with.

    The ink rule finds the tallest unbroken mass of dark rows, which is the
    whole answer on a page laid out one column wide -- every Cambridge sheet.
    IELTS Trainer 2 sets two columns and puts an Action plan, two tip boxes
    and the list of questions in the same band as the plan, so the mass is the
    page: the cut for its Test 1 Part 2 was 88% of the sheet with the map
    about half way across it.

    Where the page carries placed images, the INTERSECTION of the two is the
    picture. Neither alone is enough -- one page's overlays cover the whole
    sheet and another's run off the edge of it, and on both the ink box is the
    better answer -- but the part they agree on has never been wrong.
    """
    placed = overlaid(page)
    if placed is None:
        return box
    together = (max(box[0], placed[0]), max(box[1], placed[1]),
                min(box[2], placed[2]), min(box[3], placed[3]))
    if together[2] - together[0] <= 0 or together[3] - together[1] <= 0:
        return box
    # A sliver is two pieces of evidence disagreeing, not agreeing.
    if ((together[2] - together[0]) < (box[2] - box[0]) / 5
            or (together[3] - together[1]) < (box[3] - box[1]) / 5):
        return box
    # Opened back out to the figure's own captions, but never past the ink
    # box: that is the outer bound both pieces of evidence already agreed on.
    grown = grown_to_labels(page, together)
    return (max(box[0], grown[0]), max(box[1], grown[1]),
            min(box[2], grown[2]), min(box[3], grown[3]))


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
    ap.add_argument("section_id", help="a section (cam11-t1-s2) or a passage "
                                       "(cam11-t1-p2)")
    args = ap.parse_args()

    # A reading passage is answered on a picture exactly as a listening part
    # is -- Cambridge 11's Falkirk Wheel is a diagram with seven blanks drawn
    # on it -- and everything below this line is about a page rather than
    # about a paper. So the only difference is which table says which pages,
    # and the id says which table to ask.
    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    passage = "-p" in args.section_id
    row = conn.execute(
        ("SELECT p.*, d.rel_path pdf FROM passage p "
         "JOIN document d ON d.id = p.document_id WHERE p.id = ?") if passage else
        ("SELECT s.*, d.rel_path pdf FROM section s "
         "JOIN document d ON d.id = s.document_id WHERE s.id = ?"),
        (args.section_id,)).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"{args.section_id} is not in the catalogue")
    if passage:
        # The passage's own sheets, NOT all of them. `passage.pages` is the
        # text and the questions together, and the ink-mass fallback --
        # written for a figure standing alone on a page of prose -- takes the
        # tallest unbroken mass it can find. On a page of a reading passage
        # that mass is the passage: Cambridge 11's Falkirk Wheel came back as
        # two columns of body text, which is a picture nobody can label.
        from read_passage_questions import question_pages
        row = dict(row)
        row["question_pages"] = json.dumps(question_pages(row))

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
        # In this order, and each step's output is the next one's input.
        # `trim_to_picture` narrows to a placed figure and is already bounded
        # by the ink box; `split_at_rule` then cuts a two-column page at the
        # line between its columns, and is the one step allowed to reach
        # BELOW the ink box -- that box was measured across both columns, so
        # it stops where the wider of them stops.
        narrowed = split_at_rule(page, trim_to_picture(page, box))
        if narrowed != box:
            print(f"  group {group_index}: narrowed to the figure the page places "
                  f"-> {narrowed[0]:.2f},{narrowed[1]:.2f}-"
                  f"{narrowed[2]:.2f},{narrowed[3]:.2f}")
            box = narrowed
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
