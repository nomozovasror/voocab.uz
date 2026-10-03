# The frequency lists, and the sense inventory

Two kinds of file here now. The first five are frequency/domain lists from
the New General Service List project — flat, ranked-or-not lists of
headwords — downloaded verbatim and read by simple CSV parsing. The sixth,
Open English Wordnet, is a sense inventory: for each headword, which meanings
it has and what each one is defined as. Nothing here is edited after
download; every quirk in a source file is absorbed by the reader that parses
it, not by hand-fixing the file, so a file in this directory can always be
diffed against what its publisher actually shipped.

## There is a second copy, inside `backend/`

`oewn_senses.jsonl.gz` and the six NGSL-family files the lexicon build reads
(`NGSL_12_stats.csv`, `NAWL_12_lemmatized_for_research.csv`,
`SUP_lemmatized.csv`, `BSL_120_lemmatized_for_research.csv`,
`TSL_12_lemmatized_for_research.csv`, `MOEL_terms.csv`) are also vendored,
byte for byte, at `backend/app/data/wordlists/` -- and so are the three
ranked stats files the word-lists build (`app.services.word_lists_build`)
reads for its teaching order: `BSL_120_stats.csv`, `TSL_12_stats.csv`,
`NAWL_12_stats.csv`, and `NGSL_SFI_31K.csv` (extracted from the 31K
workbook, below -- which, like the raw OEWN release, is not vendored at
all). This directory stays the
canonical one — provenance, licence and how each file was produced are
documented here and only here, and `extract_oewn.py`/`extract_moel.py`
still write their output here — but `docker-compose.yml` bind-mounts only
`backend/` into the `backend` and `worker` containers, and `backend/
Dockerfile`'s `COPY . .` only ever sees `backend/` too, so nothing outside
it exists inside either the dev container or a built image.

`app.services.lexicon.WORDLISTS` (imported by `scripts/build_lexicon.py`,
`scripts/enrich_lexicon.py`, `app.services.lexicon_enrich`, and `app.worker`'s
lexicon loop) points at the `backend/` copy; `seed/vocabulary.py`'s own
reading-pipeline `Lists`, which runs on the host in the seed venv rather than
in either container, keeps reading the copy in THIS directory. Re-vendoring
either list (a new NGSL release, a newer OEWN tag) means updating both
copies — there is no symlink between them, because `backend/` has to stay a
buildable, self-contained Docker context on its own.

## The NGSL family

Six files, all from the same project (Browne, Culligan & Phillips), same
corpus methodology, same licence. `NGSL_12_*` and `NAWL_12_*` and `SUP_*`
were downloaded on 2026-09-20; `BSL_120_*`, `TSL_12_*` and the MOEL
spreadsheet on 2026-09-27, for the lexicon build (`brief-lexicon.md`).

| File | Rows | Shape |
|---|---|---|
| `NGSL_12_stats.csv` | 2 809 | `Lemma, SFI Rank, SFI, Adjusted Frequency per Million` |
| `NGSL_12_lemmatized_for_research.csv` | 2 809 | `lemma, form, form, …` after six comment lines |
| `NAWL_12_lemmatized_for_research.csv` | 959 | `lemma, form, form, …` |
| `NAWL_12_stats.csv` | 957 | `Word, Rank, Band, SFI, U` (academic, ranked) -- see below |
| `SUP_lemmatized.csv` | 52 | `lemma, form` — weekdays, months, numbers |
| `BSL_120_stats.csv` | 1 744 | `Word, BSL Rank, Band, SFI, U, …` (business) |
| `BSL_120_lemmatized_for_research.csv` | 1 744 | `lemma, form, form, …` |
| `TSL_12_stats.csv` | 1 250 | `Word, TSL Rank, SFI, U` (TOEIC) |
| `TSL_12_lemmatized_for_research.csv` | 1 250 | `lemma, form, form, …` |
| `MOEL_Oral-English-Medical-Corpus.xlsx` | 657 | one column, terms and short phrases (medical) |
| `MOEL_terms.csv` | 657 | the same 657, extracted — see below |
| `NGSL_SFI_31K.csv` | 31 240 | `lemma, sfi, raw_freq_rank, wordlist`, extracted from the project's 31K workbook (not vendored) -- see below |

BSL and TSL ship in exactly the NGSL/NAWL shape (a ranked stats file plus a
"lemmatized for research" file of every inflected form) and are read by the
same kind of parser — see `Lists` in `seed/lexicon.py`, which is `seed/
vocabulary.py`'s `Lists` for the reading pipeline's two lists, extended to
all five now that the lexicon build needs the other three as well. Their
quirks are the same family's quirks: CRLF endings, a run of `##` comment
lines before the data, tab characters inside those comments (ignored — only
data rows are read, and a `##` line is dropped whole), and one of the two
`utf-8`-clean while the other needs Latin-1 (TSL, like NAWL before it).

## Why the research lemmatisation rather than the teaching one

Both files exist and differ by a few hundred over-generated forms:
`accentings`, `activatings`, plurals of gerunds nobody writes. The teaching
list drops them because a flashcard for `activatings` is a bad flashcard.

This is not making flashcards. It is asking, of a word standing in a passage,
whether the reader has met it before — and there the over-generated forms cost
nothing and the missing ones cost something real. A form absent from the map
falls through to the rule-based stripper in `vocabulary.py`, and every form
present is one the stripper does not have to guess at.

`SUP_lemmatized.csv` is here because the NGSL leaves weekdays, months and
numbers out of its ranked list: they are part of the list and simply have no
frequency. Without this file `Tuesday` and `seventeen` read as off-list rare
words, which is the opposite of true.

## MOEL is a flat list, not a ranked one

Unlike the other four, MOEL ships with no rank and no stats file — the
project publishes it as one column of 657 terms and short phrases (`x-ray`,
`acquired immune deficiency syndrome (aids)`), because a medical
patient-communication vocabulary is not being claimed to have a frequency
order, only membership. It arrives as a `.xlsx` (Squarespace's own export),
read by `extract_moel.py` with the standard library's own `zipfile` +
`xml.etree` — no spreadsheet dependency for one 27 KB file read exactly
once — into `MOEL_terms.csv`, lower-cased with the workbook's trailing
non-breaking spaces stripped. `seed/lexicon.py` reads the CSV, never the
spreadsheet.

MOEL was checked for any frequency or rank column before the word-lists
build ordered it (2026-10-03): the workbook has one sheet, one populated
column (`A1:A657`, 1 863 rows formatted, the rest empty), the terms in
alphabetical order and nothing else -- no rank, band or count anywhere, and
`appetite` listed twice (656 distinct terms). The build therefore orders
Medical English by its chain (SemCor count, then NGSL rank, then the chosen
sense's CEFR -- never alphabetically); see `app.services.word_lists_build`.

## `NAWL_12_stats.csv` -- the NAWL's own frequency ranks

Downloaded 2026-10-03 from
`https://www.newgeneralservicelist.com/s/NAWL_12_stats.csv` (the site's
`/s/` link, which redirects to the Squarespace asset
`static1.squarespace.com/static/64336926d7c6bb38965fdf3b/t/644e0cc3e22fd95fbef5d060/1682836675261/NAWL_1.2_stats.csv`),
verbatim: UTF-8 with a BOM, CRLF, a `Word, Rank, Band, SFI, U` header and
957 rows, ranks 1-957. SHA-256
`4c99a9512730496fb19b7fbdd69831a1333ac3dd5f10cafb71487dd03c8f41f0`.

The NAWL page itself says "NAWL frequency data is included only in the
'NAWL 1.2 with basic statistics file'" and links that title to a glossary
page on `linguaeruditio.com` (which refuses non-browser requests); the CSV
above is the same project's own stats file under the naming its siblings
use (`NGSL_12_stats.csv`, `BSL_120_stats.csv`), served from the same site.
Its 957 words are the NAWL 1.2 as published ("a 957 word list"); the
lemmatised file above has 959 because it also carries `criteria`, `founds`
and `headquarter` as headwords where the stats file has `headquarters` --
the word-lists build takes the stats file as the list. Same authors, same
CC BY-SA 4.0 licence as the rest of the family (below).

## `NGSLwithSFI-31K.xlsx` -- frequency for an unranked list

MOEL has no rank (above), so the word-lists build orders Medical English by
the NGSL project's own frequency table for its whole corpus, "NGSL with SFI
(31K)". Retrieved 2026-10-03 from
`https://www.newgeneralservicelist.com/s/NGSLwithSFI-31K.xlsx` (the link on
the NGSL page, which redirects to the Squarespace asset
`static1.squarespace.com/static/64336926d7c6bb38965fdf3b/t/643bd96d6b7b75042fe0f43b/1681643894991/NGSL%2Bwith%2BSFI+%2831K%29.xlsx`),
3.6 MB, SHA-256
`6d0da411fb88ee5577d11e72a368c717b9bce088590f6ae34e2d8d148afe6bf3`.

**Why not vendor the workbook itself.** The same rule as the raw OEWN
release (below): a large, third-party, exactly-reproducible file does not
belong in git. What is committed is `extract_sfi31k.py` and its output; to
reproduce it, download the workbook, check the SHA-256 above, and run

    curl -L -o /tmp/NGSLwithSFI-31K.xlsx \
        https://www.newgeneralservicelist.com/s/NGSLwithSFI-31K.xlsx
    shasum -a 256 /tmp/NGSLwithSFI-31K.xlsx
    python3 seed/wordlists/extract_sfi31k.py /tmp/NGSLwithSFI-31K.xlsx

One sheet, `SFI adj`, 31 240 data rows (the rest of `A1:J80830` is
formatted but empty): `Lemma, Wordlist` (`1 - NGSL`, `2 - Sup`, `3 - NAWL`,
or empty for a lemma on none of them), `WL_SFI_Rank` (rank within that
list), `SFI, U, D, F` (the Standard Frequency Index the family's ranks are
made of, and its inputs), `RawFreq_Rank`, `Coverage, Cumulative Coverage`;
rows in raw-frequency order. Single lemmas only -- no phrases -- and one
lemma twice (`criteria`).

`extract_sfi31k.py` (standard library only, like `extract_moel.py`) writes
`NGSL_SFI_31K.csv` -- `lemma` lower-cased, `sfi`, `raw_freq_rank` and
`wordlist` copied as stored, every row in the workbook's order -- and that
CSV, not the workbook, is copied to `backend/app/data/wordlists/`.
Re-running the script on this workbook reproduces it byte for byte
(SHA-256 `ad9a1403e45e4a85c7c82e3a736ac18f3f1184444f0d63429169b0f5dd138609`).
The build reads one SFI per lemma (the higher, for `criteria`) and orders a
MOEL term found there by SFI, highest first (`rank_source = sfi31k`): 460 of
MOEL's 656 terms on the 2026-10-03 run. The other 196 -- 139 phrases, and
single words the table holds only in another form (`antibodies`,
`bleeding`, `vitamins`) -- follow, by the SemCor -> NGSL -> CEFR chain.
Same authors, same CC BY-SA 4.0 licence as the rest of the family (below).

## Licence — all five NGSL-family lists

The New General Service List, New Academic Word List, Business Service
List, TOEIC Service List and Medical Oral English List, all by Browne, C.,
Culligan, B. and Phillips, J., are licensed under a Creative Commons
Attribution-ShareAlike 4.0 International licence.

> Browne, C., Culligan, B., & Phillips, J. The New General Service List /
> New Academic Word List / Business Service List / TOEIC Service List /
> Medical Oral English List. https://www.newgeneralservicelist.com

Attribution is a condition of use, not a courtesy: anything this project
redistributes that contains these lists carries the same licence. What the
pipeline emits — a passage's glossed vocabulary, or a `Lexeme`'s
`frequency_band`/`domain_tags` — is not a redistribution of the lists,
because membership of a list is not the list. The files themselves, vendored
here, are.

---

## Open English Wordnet — the sense inventory

`oewn_senses.jsonl.gz` is a compacted extract of the **2025 edition** of the
[Open English Wordnet](https://github.com/globalwordnet/english-wordnet)
(the edition that ships common vocabulary only — proper nouns moved to a
separate resource, Open English Namenet, in this release, which is exactly
what this project wants: `Lexeme` is not in the business of naming places
and people). Retrieved 2026-09-27 from the GWA XML release asset
(`english-wordnet-2025.xml.gz`, tag `2025-edition`,
https://github.com/globalwordnet/english-wordnet/releases/tag/2025-edition).

**Why not vendor the release itself.** The raw XML is 89 MB uncompressed —
135 969 lexical entries, each carrying sense relations, synset relations and
example sentences this project has no use for. `Materials/` and `seed/work/`
already establish the rule this follows: a large, third-party, exactly-
reproducible file does not belong in git. What is committed instead is
`extract_oewn.py`, which reads the release once and keeps only what P1/P2
need — lemma, pos, and each headword's senses **in the release's own
order** (synset id, rank, definition) — as gzipped line-delimited JSON, 6.1
MB. Re-running the script against the same tagged release reproduces this
file byte for byte; that reproducibility, not the presence of the raw file
in git, is what "vendored" means here.

    python3 seed/wordlists/extract_oewn.py /path/to/english-wordnet-2025.xml \
        /path/to/wn3.1/dict/cntlist.rev

**Why the order is kept.** OEWN inherits Princeton WordNet's own sense
numbering — sense 1 first, the commonest — rather than deriving a frequency
order of its own. `brief-lexicon.md` §5 leans on exactly this: the top 1-2
senses a Lexeme gets in P2 are the first 1-2 entries this file lists for
that (lemma, pos), no frequency computation of this project's own required.

**Shape**, one JSON object a line:

    {"lemma": "bank", "pos": "n", "is_phrase": false,
     "senses": [{"synset": "oewn-09236472-n", "rank": 1,
                 "definition": "sloping land (especially the slope beside a body of water)"},
                ...]}

Two optional fields (added 2026-09-28): `"form"` on a record whose OEWN
written form is capitalised (`"Song"`, `"Monday"`, `"DNA"`) -- the loader
keeps those apart from the lower-case word; and `"count"` on a sense SemCor
ever tagged -- its tag count from **Princeton WordNet 3.1's `cntlist.rev`**
(https://wordnetcode.princeton.edu/wn3.1.dict.tar.gz; WordNet 3.1
Copyright 2011 Princeton University, WordNet licence -- use and
redistribution permitted with the copyright notice), matched through the
Princeton sense key every OEWN sense id is built from. OEWN ships no counts;
they are the only frequency that compares senses ACROSS parts of speech
(a list-only lexeme's pos is chosen by it). Copy the regenerated file to
`backend/app/data/wordlists/` as before.

**Where the rank actually lands, downstream.** This file's own `rank` is
what P2 orders a lexeme's senses BY (`sense_rank`); `LexemeSense.oewn_rank`
persists which rank an `oewn`-sourced sense actually got, so the public
licences page (`app.services.lexicon_licences`) can show Princeton WordNet
3.1 because the data actually used it -- not a permanent hand-written row --
and say plainly that the counts order senses and are never stored as a
definition. See `backend/app/services/CLAUDE.md`'s lexicon section for the
column and the page both.

`pos` is OEWN's own five codes (`n`, `v`, `a`, `s`, `r`) mapped onto this
project's own vocabulary — `a` and `s` ("adjective satellite", WordNet's term
for an adjective clustered under a head adjective rather than given its own
top-level group) both fold to `adj`, `r` to `adv` — because nothing
downstream needs to know the two adjective kinds were structured
differently upstream. There is no OEWN equivalent for this project's `prep`
or `conj`: WordNet does not catalogue closed-class function words, so a
Lexeme with one of those parts of speech will simply have no OEWN coverage,
which P1's own coverage report counts rather than hides.

**Attached in P1, matched in P2.** P1 loads this file and keeps, per
Lexeme, the synsets whose `lemma` matches — nothing here decides which
synset corresponds to which of a Lexeme's provisional senses, or merges two
provisional senses that turn out to name the same synset. That matching
needs a model reading definitions against each other, which is P2's job by
design (`lexicon-spec.md`, D1-D2); P1 only makes the inventory available to
query.

### Licence

The Open English Wordnet is licensed under a Creative Commons Attribution
4.0 International licence (**no** ShareAlike) by the Open English Wordnet
team — <https://github.com/globalwordnet/english-wordnet>. This is the
reason OEWN, rather than Wiktionary (CC BY-SA, share-alike), supplies
`LexemeSense.definition_en`: a copyleft definition would put every sense
built from it under the same obligation, and OEWN's plain attribution
licence does not.
