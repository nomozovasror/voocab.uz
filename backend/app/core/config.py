from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable via environment variables or a .env file.

    ``DATABASE_URL`` must use the async ``postgresql+asyncpg`` driver so both the
    app and Alembic share one connection string. The default targets the
    docker-compose ``db`` service (user/pass ``postgres``, database ``app``); set
    the env var to point elsewhere for local runs outside Docker.

    The auth settings default to empty/dev values so the app and Alembic import
    cleanly without them; the Telegram endpoints fail loudly if the required
    ones are missing. Real secrets live in the environment (see .env.example).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/app"

    # --- Telegram OIDC (values from @BotFather) ---
    # Client ID (bot id) and client secret (bot token) issued by BotFather when
    # you register your Allowed URLs. Sent to the /token endpoint via HTTP Basic.
    telegram_bot_id: str = ""
    telegram_bot_token: str = ""
    # Must exactly match a redirect URI registered with BotFather.
    telegram_redirect_uri: str = "http://localhost:5173/api/auth/telegram/callback"

    # --- Our own session layer ---
    # HS256 signing key for our access/refresh cookies and the short-lived OIDC
    # transaction cookie. MUST be overridden in production.
    session_secret: str = "dev-insecure-session-secret-change-me"
    # Set true in production so cookies are only sent over HTTPS.
    cookie_secure: bool = False
    # Cookie Domain attribute. In production the frontend (voocab.uz) and API
    # (api.voocab.uz) live on different subdomains, so session cookies must be
    # scoped to the parent domain, e.g. ".voocab.uz". Empty = host-only cookie
    # (correct for single-host local dev).
    cookie_domain: str = ""
    # Where the callback sends the browser after a successful login.
    frontend_url: str = "http://localhost:5173"

    # --- Dev only: passwordless local login ---
    # Enables POST /api/auth/dev-login (a test-user session without Telegram) so
    # local dev needs no tunnel. NEVER set this in production — it's additionally
    # refused whenever cookie_secure is true (i.e. any HTTPS/prod config).
    dev_login_enabled: bool = False

    # --- CORS ---
    # Origins allowed to call the API with credentials. Accepts a comma-separated
    # string in the env (e.g. "https://voocab.uz,https://www.voocab.uz").
    # NoDecode stops pydantic-settings from JSON-parsing the env value so our
    # validator can split it.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # --- Cloudflare R2 (audio storage + DB backups; S3-compatible) ---
    r2_bucket: str = ""
    r2_endpoint: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    # Public base URL that fronts the R2 bucket (r2.dev or a custom domain like
    # https://media.voocab.uz). Stored audio URLs are built as
    # ``{r2_public_base_url}/{key}``. Required for uploads when R2 is used.
    r2_public_base_url: str = ""

    # --- Groq (ASR: audio transcription) ---
    # Bearer token for https://api.groq.com/openai/v1/audio/transcriptions.
    # Never hardcoded; read from env (GROQ_API_KEY). Empty in dev until a real
    # key is provisioned — callers/tests must treat that as "not configured".
    groq_api_key: str = ""
    # httpx timeout (seconds) for the transcription request. Env-overridable
    # since larger clips may need more headroom than the default.
    groq_timeout_s: float = 120.0

    # --- Gemini (dictionary: the second provider) ---
    # Bearer token for Google's OpenAI-compatible chat endpoint (GEMINI_API_KEY).
    # Used only by `app.services.dictionary`, and only when Groq has not
    # answered — see the chain in `providers()` for why one API is not enough
    # to stand behind "any word a learner selects is answered".
    gemini_api_key: str = ""

    # --- ASR worker (Faza 4: Postgres-backed transcription queue) ---
    # Retryable failures (network timeout, 408/429/500/502/503/504) retry up
    # to this many attempts before the blob is marked `failed`.
    asr_max_attempts: int = 3
    # How long the worker sleeps between claim attempts when the queue is empty.
    asr_poll_interval_s: float = 2.0
    # Exponential backoff base (seconds) after a retryable failure: sleep is
    # asr_backoff_base_s * 2 ** (attempts - 1).
    asr_backoff_base_s: float = 2.0

    # --- Difficulty projection (app/services/difficulty.py) ---
    # How often the worker recomputes every material's difficulty tally into
    # material_difficulty. Fifteen minutes because a band is an average over
    # hundreds of answers and does not move in less; the only visible lag is a
    # material crossing MIN_ANSWERS for the first time, which keeps saying
    # "New" until the next pass. Set to 0 to turn the refresher off entirely
    # (a second worker instance that shouldn't duplicate the work, or a test).
    difficulty_refresh_interval_s: float = 900.0

    # --- Lexicon enrichment (Faza P3: app/worker.py's continuous version of
    # scripts/enrich_lexicon.py) ---
    # How often the worker looks for lexemes still `enriched_at IS NULL` --
    # a brand-new find-or-create Lexeme (`app.services.lexicon.link_row`),
    # or one an earlier pass failed on. Short relative to the difficulty
    # refresh: a word a reader just looked up is worth finishing within
    # minutes, not a quarter of an hour, and an empty pass costs one query.
    # 0 disables it (a second worker instance, or a test).
    lexicon_enrich_interval_s: float = 60.0
    # Lexemes per pass, matching `scripts/enrich_lexicon.py --unit`'s own
    # default: small enough that one pass's Gemini cost and latency stay
    # predictable, large enough that a seed import's whole batch of new
    # words does not take all day to catch up.
    lexicon_enrich_batch_size: int = 10
    # --- CALD definitions (app/services/lexicon_cald.py) ---
    # After each enrichment pass the worker maps the lexemes it just
    # finished to the Cambridge dictionary -- map, translate v2, compare,
    # apply, as the full run did -- when the private CALD index is on this
    # machine (app/data/private/cald/, never committed); without it the hook
    # logs once and does nothing. False turns it off: the test suite does
    # (tests/conftest.py), because it must never reach the real API or the
    # private decision log.
    # ON by default (the owner agreed: a lexeme that arrives after the full
    # run is mapped automatically); the switch is explicit so a deployment
    # can turn the hook AND its retry sweep off.
    cald_map_new_lexemes: bool = True
    # What keeps the hook from costing more than it is worth. A hard failure
    # (HTTP 402/401/403, or a 429 that outlasts the client's own retries)
    # stops the pass at once and pauses the hook: the first pause lasts
    # `cald_hook_cooldown_s`, each further failure in a row doubles it, up to
    # `cald_hook_cooldown_max_s` (6 h). One log line on entering the pause and
    # one on leaving it.
    cald_hook_cooldown_s: float = 300.0
    cald_hook_cooldown_max_s: float = 21600.0
    # Wall-clock limit of one hook (or sweep) call, seconds; 0 = none. A call
    # that overruns is cancelled and counts as a failure (the cooldown).
    cald_hook_timeout_s: float = 300.0
    # Spend caps in USD, from the client's own token counts (pass) and
    # `usage.jsonl`'s `worker` records (day, UTC); 0 = no cap. The pass stops
    # before the request that would cross the cap, with a log line.
    cald_hook_pass_budget_usd: float = 0.50
    cald_hook_daily_budget_usd: float = 3.00
    # The retry sweep, run from the enrichment loop: senses of CALD-matched
    # lexemes whose questions are recorded as unanswered, or were never asked
    # (a word-list build writes senses into lexemes enrichment had finished).
    # At most one sweep per `cald_sweep_interval_s` (0 = off), `..._batch`
    # lexemes each, and a lexeme is tried at most `..._max_tries` times per
    # worker process. Same cooldown, caps and timeout as the hook.
    cald_sweep_interval_s: float = 1800.0
    cald_sweep_batch: int = 25
    cald_sweep_max_tries: int = 3
    # The CALD source directory (the one `scripts/cald.py index --source`
    # read: `data/entries.json`, `media/audio/*.mp3`). With it, the hook also
    # attaches the human recordings of the senses it finished
    # (`app.services.word_recordings.attach_for_lexemes`); empty = no
    # recordings for new senses (ONE log line), they are spoken by the
    # synthetic voice. Never inside the repository.
    #
    # In the worker container this is wherever the source is mounted
    # read-only (CALD_SOURCE_DIR=/cald); the private index
    # (`app/data/private/cald/`) must be there too. Without both, nothing.
    cald_source_dir: str = ""
    # Processes the recordings sweep decodes with (the sweep can find thousands
    # of files the first time it runs); 1 = threads in the worker's own process.
    cald_recordings_workers: int = 2

    # --- Text to speech (vocabulary stage 3: app/worker.py's render loop;
    # app/services/tts.py) ---
    # How long the render loop sleeps when `audio_renders` has nothing pending.
    # Short: a learner may be waiting on the word they just asked to hear, and
    # an empty pass is one query. 0 disables the loop (an API-only worker, a
    # test); the loop also disables itself, with one log line, where kokoro is
    # not installed.
    tts_poll_interval_s: float = 2.0
    # A render that fails is retried until this many attempts, then `failed`
    # (and left for `tts.requeue_failed`).
    tts_max_attempts: int = 3
    # Sleep after a failed render: base * 2 ** (consecutive failures - 1),
    # capped at a minute, so a broken model cannot spin the loop.
    tts_backoff_base_s: float = 5.0
    # A render that failed for a REASON OF ITS OWN is not claimable again for
    # base * 2 ** (attempts - 1) seconds (capped at an hour): a systemic fault
    # then walks the queue once per back-off instead of burning every row's
    # attempts in seconds.
    tts_retry_backoff_s: float = 60.0
    # Infrastructure faults (storage down, the model failed to load) do not
    # count as attempts; the row waits this long and is tried again.
    tts_infra_backoff_s: float = 60.0
    # A `processing` render not touched for this long was left by a dead
    # worker: back to `pending`. Age, not "everything processing", so one
    # worker's recovery never takes a row another is making right now.
    tts_stale_after_s: float = 900.0
    # `failed` renders are put back to `pending` (attempts reset) after this
    # many hours, so a fault that has since been fixed heals without anyone
    # running `requeue_failed`. 0 disables it.
    tts_failed_requeue_h: float = 6.0

    # --- Local media (dev fallback when R2 isn't configured) ---
    # Uploads land here and are served at ``media_url_prefix``. Relative to the
    # backend working directory.
    media_root: str = "media"
    media_url_prefix: str = "/media"

    @property
    def use_r2(self) -> bool:
        """Use R2 when it's fully configured; otherwise fall back to local disk."""
        return bool(
            self.r2_bucket
            and self.r2_endpoint
            and self.aws_access_key_id
            and self.aws_secret_access_key
        )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Allow the env var to be a comma-separated list rather than JSON."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
