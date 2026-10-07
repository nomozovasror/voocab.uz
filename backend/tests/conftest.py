"""Suite-wide guard: the worker's CALD hook (`app.services.lexicon_cald
.map_new_lexemes`, behind `settings.cald_map_new_lexemes`) is OFF for every
test. Several tests drive `app.worker._lexicon_enrich_once` on real lexemes;
with the hook on they would load the private CALD index on a developer's
machine, call the real Gemini API and append to the private decision log.
The hook's own tests turn it on for themselves, against a temporary
directory and a fake model.

Set before anything imports `app.core.config` (pytest imports this file
first), and as an environment variable because real env vars win over
`.env` in pydantic-settings.
"""

import os

os.environ["CALD_MAP_NEW_LEXEMES"] = "false"
