"""Pull the Medical Oral English List's one column out of its spreadsheet.

MOEL ships as a single-column `.xlsx` -- no rank, no stats file, unlike the
other four lists -- because the project publishes it as a flat list rather
than a frequency-ranked one (see `seed/wordlists/README.md`). Reading it
needs no spreadsheet library: `.xlsx` is a zip of XML, the one sheet has a
single populated column, and stdlib's `zipfile` plus `xml.etree` is a smaller
dependency than adding `openpyxl` to the backend for one 27 KB file read
exactly once.

Usage, from the repo root::

    python3 seed/wordlists/extract_moel.py

Reads the vendored `.xlsx` and writes `MOEL_terms.csv` (one term or phrase a
line, lower-cased, non-breaking spaces and trailing whitespace stripped) next
to it, in the same directory this file lives in -- no arguments, because
there is exactly one input and it is already vendored.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "MOEL_Oral-English-Medical-Corpus.xlsx"
OUTPUT = HERE / "MOEL_terms.csv"

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def extract(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        # A shared string can hold several `<r>` (rich-text run) children
        # instead of one bare `<t>` where the workbook ever applied mixed
        # formatting to one cell; concatenating every `<t>` under the `<si>`
        # is what makes that case read the same as the plain one.
        shared = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                  for si in shared_root.findall("m:si", NS)]

        sheet_root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        terms: list[str] = []
        for cell in sheet_root.findall(".//m:c", NS):
            value = cell.find("m:v", NS)
            if value is None:
                continue
            text = shared[int(value.text)] if cell.get("t") == "s" else (value.text or "")
            # `\xa0` (non-breaking space) terminates every entry in this
            # workbook, a Squarespace export artefact rather than anything
            # about the words -- left in would make `x-ray ` and `x-ray`
            # count as two different lemmas the moment either travelled
            # through a plain equality check.
            term = text.replace("\xa0", " ").strip().lower()
            if term:
                terms.append(term)
    return terms


def main() -> None:
    terms = extract(SOURCE)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        for term in terms:
            fh.write(term + "\n")
    print(f"{len(terms)} terms -> {OUTPUT}")


if __name__ == "__main__":
    main()
