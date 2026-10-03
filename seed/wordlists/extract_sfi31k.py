"""Pull the NGSL project's 31K-lemma frequency table out of its spreadsheet.

`NGSLwithSFI-31K.xlsx` ("NGSL with SFI (31K)") is the NGSL project's own
frequency data for every lemma of its corpus -- 31 240 rows, not only the
2 809 NGSL words -- one sheet (`SFI adj`) with the columns `Lemma, Wordlist,
WL_SFI_Rank, SFI, U, D, F, RawFreq_Rank, Coverage, Cumulative Coverage`. The
word-lists build orders an unranked list (MOEL) by it (see
`backend/app/services/word_lists_build.py`), so it needs one number per
lemma and nothing else; a 3.6 MB workbook is not something the backend
should parse, so this script writes the four useful columns once, in the
workbook's own row order, as `NGSL_SFI_31K.csv`:

    lemma,sfi,raw_freq_rank,wordlist

`lemma` is lower-cased and stripped (the workbook's one capital is `I`);
`sfi` and `raw_freq_rank` are copied as the workbook stores them;
`wordlist` is the workbook's own label (`1 - NGSL`, `2 - Sup`, `3 - NAWL`,
or empty for a lemma on none of them). Nothing is dropped or merged: the
one lemma listed twice (`criteria`) stays twice, and the reader keeps the
higher SFI. Standard library only (`zipfile` + `xml.etree`), the same way
`extract_moel.py` reads MOEL's workbook.

The workbook itself is not vendored (see `README.md`): download it, check
its SHA-256, and point this script at it. From the repo root::

    curl -L -o /tmp/NGSLwithSFI-31K.xlsx \
        https://www.newgeneralservicelist.com/s/NGSLwithSFI-31K.xlsx
    shasum -a 256 /tmp/NGSLwithSFI-31K.xlsx   # 6d0da411...6afe6bf3
    python3 seed/wordlists/extract_sfi31k.py /tmp/NGSLwithSFI-31K.xlsx

then copy `NGSL_SFI_31K.csv` to `backend/app/data/wordlists/`.
"""

from __future__ import annotations

import csv
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "NGSL_SFI_31K.csv"

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
COLUMN = re.compile(r"[A-Z]+")


def extract(path: Path) -> list[tuple[str, str, str, str]]:
    with zipfile.ZipFile(path) as archive:
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                  for si in shared_root.findall("m:si", NS)]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[tuple[str, str, str, str]] = []
    header: dict[str, str] | None = None
    for row in sheet.findall(".//m:sheetData/m:row", NS):
        cells: dict[str, str] = {}
        for cell in row.findall("m:c", NS):
            value = cell.find("m:v", NS)
            if value is None:
                continue
            text = shared[int(value.text)] if cell.get("t") == "s" else (value.text or "")
            cells[COLUMN.match(cell.get("r")).group(0)] = text
        if header is None:
            header = {name: col for col, name in cells.items()}
            continue
        lemma = cells.get(header["Lemma"], "").strip().lower()
        if not lemma:
            continue  # the formatted-but-empty rows below the data
        rows.append((lemma, cells.get(header["SFI"], ""),
                     cells.get(header["RawFreq_Rank"], ""), cells.get(header["Wordlist"], "")))
    return rows


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: extract_sfi31k.py /path/to/NGSLwithSFI-31K.xlsx")
    rows = extract(Path(sys.argv[1]))
    with OUTPUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(("lemma", "sfi", "raw_freq_rank", "wordlist"))
        writer.writerows(rows)
    print(f"{len(rows)} lemmas -> {OUTPUT}")


if __name__ == "__main__":
    main()
