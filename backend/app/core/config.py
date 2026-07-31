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
