"""Compact the Open English Wordnet release into one small file P2 can load.

The GWA XML release (``english-wordnet-2025.xml``, WN-LMF 1.3) is 89 MB
uncompressed and carries a great deal this project has no use for --
`SenseRelation`/`SynsetRelation` graphs, `Pronunciation`, `Example` sentences
inside every synset, ILI cross-references to the interlingual index. What the
lexicon build actually needs is three things per headword: which synsets it
has, in WHAT ORDER, and what each one is defined as. This script reads the
release once and writes exactly that, as line-delimited JSON, gzipped.

## Why the order survives and nothing else does

WN-LMF lists a `LexicalEntry`'s `<Sense>` children in the same order as
Princeton WordNet's own sense numbering -- sense 1 first, the commonest --
and OEWN inherited that ordering rather than re-deriving it. `brief-lexicon.md`
§5 leans on exactly this fact ("WordNet ma'nolarni allaqachon chastota
tartibida beradi"): the top 1-2 senses P2 attaches to a Lexeme are simply the
first 1-2 lines this script writes for that (lemma, pos), no frequency
computation of our own required. That ordering is the one piece of
information that cannot be recovered after the fact if it were thrown away,
so `rank` is written explicitly rather than left as list position for a
reader to infer.

## Why this runs offline, once, against a file nobody commits

The raw release is fetched by hand (see `seed/wordlists/README.md` for the
exact URL and version) and never checked in -- 89 MB of a third party's data,
reproducible at will from a pinned tag, is exactly what `Materials/` and
`seed/work/` already exist to keep out of git. What IS committed is this
script and its output, `oewn_senses.jsonl.gz` (a few megabytes), which is the
"compact extracted form" the brief allows for when the raw release is huge.

Usage, from the repo root::

    python3 seed/wordlists/extract_oewn.py /path/to/english-wordnet-2025.xml

Idempotent and side-effect-free beyond writing the one output file: re-running
it against the same input reproduces the same output byte for byte (the XML
is read in document order and nothing here sorts or hashes into a set).
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

#: WN-LMF's single-letter codes, mapped onto this project's own `pos`
#: vocabulary (see `app/models/vocabulary.py`). ``s`` -- "adjective
#: satellite", WordNet's term for an adjective defined by its closeness to a
#: head adjective rather than given its own top-level cluster -- reads to a
#: user exactly like ``a`` and is folded into ``adj`` for that reason; nothing
#: downstream of this file ever needs to know the two were structured
#: differently upstream.
POS_MAP: dict[str, str] = {
    "n": "n",
    "v": "v",
    "a": "adj",
    "s": "adj",
    "r": "adv",
}

OUTPUT_NAME = "oewn_senses.jsonl.gz"


def extract(xml_path: Path) -> list[dict]:
    """One record per ``LexicalEntry``, its senses in file order.

    ``iterparse`` rather than a full ``parse``, because building a DOM for an
    89 MB file just to walk it once and throw it away doubles the memory for
    no benefit -- each ``LexicalEntry`` is `.clear()`-ed the moment it has
    been read.

    Definitions are read from the matching ``Synset`` elsewhere in the same
    document, which WN-LMF requires be present but does not require come
    before the entries that reference it -- true of this release, where
    `Synset` elements are all listed after every `LexicalEntry` -- so the
    synsets are read in a first pass and the entries in a second, rather than
    trying to resolve a forward reference while streaming.
    """
    definitions: dict[str, str] = {}
    for _, elem in ET.iterparse(xml_path, events=("end",)):
        if elem.tag == "Synset":
            synset_id = elem.get("id", "")
            defn_elem = elem.find("Definition")
            definitions[synset_id] = (defn_elem.text or "").strip() if defn_elem is not None else ""
            elem.clear()

    records: list[dict] = []
    for _, elem in ET.iterparse(xml_path, events=("end",)):
        if elem.tag != "LexicalEntry":
            continue
        lemma_elem = elem.find("Lemma")
        if lemma_elem is None:
            elem.clear()
            continue
        written_form = lemma_elem.get("writtenForm", "")
        raw_pos = lemma_elem.get("partOfSpeech", "")
        pos = POS_MAP.get(raw_pos)
        if pos is None or not written_form:
            elem.clear()
            continue

        senses = []
        for rank, sense_elem in enumerate(elem.findall("Sense"), start=1):
            synset_id = sense_elem.get("synset", "")
            senses.append({
                "synset": synset_id,
                "rank": rank,
                "definition": definitions.get(synset_id, ""),
            })
        if senses:
            records.append({
                "lemma": written_form.lower(),
                "pos": pos,
                # A written form containing a space is OEWN's own multi-word
                # entry -- "give rise to", "'tween decks" -- the same
                # signal `is_phrase` uses on this project's own lemmas.
                "is_phrase": " " in written_form,
                "senses": senses,
            })
        elem.clear()
    return records


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} /path/to/english-wordnet-2025.xml", file=sys.stderr)
        raise SystemExit(2)
    xml_path = Path(sys.argv[1])
    records = extract(xml_path)
    out_path = Path(__file__).resolve().parent / OUTPUT_NAME
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False))
            fh.write("\n")
    total_senses = sum(len(r["senses"]) for r in records)
    print(f"{len(records)} lexical entries, {total_senses} senses -> {out_path}")


if __name__ == "__main__":
    main()
