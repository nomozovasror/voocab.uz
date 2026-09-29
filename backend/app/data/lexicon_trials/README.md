# Lexicon translation trials

A durable copy of every re-translation trial `scripts/lexicon_cleanup.py
retranslate` has run against the live lexicon, kept here as the way back --
`LexemeSense.meaning_uz_prev`/`meaning_uz_alt_prev` hold the PRE-trial pair
only until `retranslate --decide` runs, and are cleared to `""` the moment
it does (whichever way the decision went). Once that happens, this file is
the only place the old pair still exists at all.

## `retranslate-2026-09-29.json`

94 senses the judge called `judge_different` after the first translation
pass. One object per `LexemeSense.id`:

```json
{
  "<sense id>": {
    "lemma": "cheese", "pos": "n",
    "definition": "a solid food prepared from the pressed curd of milk",
    "old_uz": "pishloq", "old_alt": "pishloq, sir", "old_verdict": "same",
    "new_uz": "pishloq, sir", "new_alt": "pishloq", "new_verdict": "same"
  }
}
```

`old_uz`/`old_alt` are the pair the sense carried BEFORE this trial;
`new_uz`/`new_alt` are what the fixed prompt produced; `old_verdict`/
`new_verdict` are `app.services.lexicon_enrich.judge_twice`'s own call
(`same`/`different`/`unsure`/`null` for no answer) on each pair, judged in
the SAME run so the two are comparable. `definition` is the sense's English
gloss at the time of the trial, kept so a reviewer reading this file cold
does not have to look the sense up to know what was being translated.

**The decision, for the record.** The `different` share fell from 33.0%
(old pairs) to 10.6% (new pairs) -- a 67.7% relative drop, past
`scripts/lexicon_cleanup.KEEP_THRESHOLD` (30%) -- so the new pairs were
KEPT. Every sense in this file currently carries its `new_uz`/`new_alt`
pair, not its `old_uz`/`old_alt` one.

## Restoring a pair this trial changed

```bash
uv run python -m scripts.lexicon_cleanup restore-retranslation \
    --file app/data/lexicon_trials/retranslate-2026-09-29.json           # every sense
uv run python -m scripts.lexicon_cleanup restore-retranslation \
    --file app/data/lexicon_trials/retranslate-2026-09-29.json \
    --sense 00a8ca15-d226-494d-be39-b540aeeeedcb                          # one sense
```

Puts `meaning_uz`/`meaning_uz_alt` back to `old_uz`/`old_alt` and restores
the `judge_different`/`judge_unsure` review flag from `old_verdict` --
nothing else about the sense (its CEFR, its OEWN match, its rank) is
touched. A sense id not in this file, or a sense since deleted, is reported
and skipped rather than failing the whole run.
