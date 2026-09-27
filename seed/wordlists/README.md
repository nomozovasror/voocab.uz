# The frequency lists, and the sense inventory

Two kinds of file here now. The first five are frequency/domain lists from
the New General Service List project — flat, ranked-or-not lists of
headwords — downloaded verbatim and read by simple CSV parsing. The sixth,
Open English Wordnet, is a sense inventory: for each headword, which meanings
it has and what each one is defined as. Nothing here is edited after
download; every quirk in a source file is absorbed by the reader that parses
it, not by hand-fixing the file, so a file in this directory can always be
diffed against what its publisher actually shipped.

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
| `SUP_lemmatized.csv` | 52 | `lemma, form` — weekdays, months, numbers |
| `BSL_120_stats.csv` | 1 744 | `Word, BSL Rank, Band, SFI, U, …` (business) |
| `BSL_120_lemmatized_for_research.csv` | 1 744 | `lemma, form, form, …` |
| `TSL_12_stats.csv` | 1 250 | `Word, TSL Rank, SFI, U` (TOEIC) |
| `TSL_12_lemmatized_for_research.csv` | 1 250 | `lemma, form, form, …` |
| `MOEL_Oral-English-Medical-Corpus.xlsx` | 657 | one column, terms and short phrases (medical) |
| `MOEL_terms.csv` | 657 | the same 657, extracted — see below |

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

    python3 seed/wordlists/extract_oewn.py /path/to/english-wordnet-2025.xml

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
