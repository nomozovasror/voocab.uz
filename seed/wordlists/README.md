# The frequency lists

Four files, downloaded verbatim from the New General Service List project on
2026-09-20 and not edited since. Their quirks — CRLF endings, a byte-order
mark on one, Latin-1 bytes on another, comment lines above the data — are
left in place and handled by the reader in `seed/vocabulary.py`, for the same
reason the rest of this pipeline leaves upstream oddities alone: a file that
has been quietly cleaned is a file nobody can check against its source.

| File | Rows | Shape |
|---|---|---|
| `NGSL_12_stats.csv` | 2 809 | `Lemma, SFI Rank, SFI, Adjusted Frequency per Million` |
| `NGSL_12_lemmatized_for_research.csv` | 2 809 | `lemma, form, form, …` after six comment lines |
| `NAWL_12_lemmatized_for_research.csv` | 959 | `lemma, form, form, …` |
| `SUP_lemmatized.csv` | 52 | `lemma, form` — weekdays, months, numbers |

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

## Licence

The New General Service List and the New Academic Word List by Browne, C.,
Culligan, B. and Phillips, J. are licensed under a Creative Commons
Attribution-ShareAlike 4.0 International licence.

> Browne, C., Culligan, B., & Phillips, J. (2013). The New General Service
> List. https://www.newgeneralservicelist.com
>
> Browne, C., Culligan, B., & Phillips, J. (2013). The New Academic Word List.
> https://www.newgeneralservicelist.com

Attribution is a condition of use, not a courtesy: anything this project
redistributes that contains these lists carries the same licence. What the
pipeline emits — a passage's glossed vocabulary — is not a redistribution of
the lists, because membership of a list is not the list. The files themselves,
vendored here, are.
