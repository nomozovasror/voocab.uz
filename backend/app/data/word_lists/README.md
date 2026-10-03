# Word list build decisions

`decisions.jsonl` is the log of every model answer the word-list build
(`scripts/build_word_lists.py`, `app/services/word_lists_build.py`) has used.
It is committed on purpose: the answers cost money and are not reproducible,
so the log, not the model, is the record of why each list entry points at the
sense it does.

Two kinds of line, one JSON object each:

- `"kind": "choice"` -- which sense a list means by a lemma (`list`, `lemma`,
  `decision`, `model`, `at`). For the domain lists `model` is the chooser
  model; for Core it says how the sense was decided: `semcor-top` (OEWN's
  most-tagged synset across parts of speech), a model name (the model picked
  among each part of speech's top sense where SemCor tied), a model name
  with `:all-senses` (it declined those, and chose from every OEWN sense plus
  ours, or wrote a definition), `tie-order` (it declined both menus, so
  `POS_PRIORITY` order), or `rank1-fallback` (OEWN lacks the lemma: the
  primary lexeme's rank-1 sense).
  `decision.sense_id` is a lexicon id from the dev database the log was made
  on; a database without that sense falls back to the `synset` / `definition`.
- `"kind": "sense"` -- the CEFR grade, Uzbek translations and judge verdict for
  a sense the build had to create.

The script reads this file by default (`--decisions` overrides it) and appends
new answers to it. Commit the file after any run that used the model.

## Replay without the model

From `backend/`, against a database you name explicitly:

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/<db> \
    uv run python -m scripts.build_word_lists --confirm-db <db> --no-model

Every entry the log can answer is resolved identically; entries it cannot
answer stay unresolved and are listed in the report.

## Reselect a list

`--reselect business` ignores the log for that list and asks the model again
(needs `GEMINI_API_KEY`; do not combine with `--no-model`). The new answers are
appended after the old ones, and the later line for a lemma wins on the next
replay. Review the report, then commit the grown log.
