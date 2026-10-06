# Text-to-speech data

Everything here is what `app/services/pronunciation.py` and
`app/services/heteronym_decisions.py` read. The API image needs no misaki
because of this directory.

## `misaki_gb_pos_entries.json` -- vendored, do not edit

The 788 part-of-speech-keyed entries (the ones whose value is an object like
`{"DEFAULT": ..., "VERB": ...}`) of **misaki's British gold lexicon**,
`misaki/data/gb_gold.json`, from the `misaki` 0.9.4 wheel
(<https://github.com/hexgrad/misaki>, by hexgrad). misaki is **Apache-2.0**
(its `LICENSE` ships in the wheel); this file is a verbatim extract of its
data, so it carries the same licence and the credit is on the public
"Data sources and licences" page (`app/services/lexicon_licences.py`).

Values are **misaki phonemes, not IPA**: `A` /eɪ/, `I` /aɪ/, `Q` /əʊ/,
`W` /aʊ/, `Y` /ɔɪ/, `ɹ` r, `ː` long, `ˈ` primary stress. A `null` value means
"no override for this tag"; the key `"None"` is misaki's untagged variant (for
function words it is only a stress difference, which is why those are not
heteronyms).

To refresh: take `gb_gold.json` from a newer misaki wheel and keep the
dict-valued entries. Re-run `scripts/decide_heteronyms.py decide`: a changed
candidate set makes old decisions "stale" (reported by `apply`, never
written).

## `misaki_us_pos_entries.json` -- vendored, do not edit

The same extract from misaki's **American** gold lexicon,
`misaki/data/us_gold.json` (0.9.4, **Apache-2.0**, the same credit as above):
the 790 dict-valued (part-of-speech-keyed) entries. Its alphabet differs from
the British one: `O` (/oʊ/) where British has `Q`, no `ː`, and `æ ɾ ᵻ ʔ`.
`tests/test_heteronyms.py` checks each table against its own alphabet. Refresh
the same way as the British file.

## `heteronym_extras.json` -- hand-written

Words that differ WITHIN one part of speech, which a POS-keyed table cannot
hold: `lead` (the metal), `row` (the quarrel), `does` (the deer), `sewer`,
`lower`, `slough`, `polish` -- plus plain-English **notes** on the variants
misaki already has (`bow`, `tear`, `wound`, `close`, `minute`, `bass`, `sow`,
`dove`). The notes are what the model reads when it chooses; a string like
`klˈQs` means nothing to it without one. Entries use misaki phonemes. An item is `{"ps": <British>, "us":
<American>, "note": ...}`: `ps` is checked against the British alphabet and
`us` against the American one (`tests/test_heteronyms.py`); no `us` means the
same string serves both, `"us": null` leaves it out of the American set, and an
item with no `ps` is American-only (`slough` /sluː/).

## `heteronym_decisions.jsonl` -- the replayable log

One line per decided sense, appended by `scripts/decide_heteronyms.py decide`,
committed. Keyed by lemma + part of speech + OEWN synset (or the definition,
for a sense with none) -- never a database id -- so it replays onto any
database: `scripts/decide_heteronyms.py apply --confirm-db <db>` writes
`lexeme_senses.pronunciation` from it with no model call. A later line for the
same sense wins. Produced with `gemini-3.8-flash`, one request per lemma.

`heteronym_decisions_us.jsonl` is the same log for the American voice
(`--accent american`; `apply` writes `lexeme_senses.pronunciation_us`), in the
American alphabet.
