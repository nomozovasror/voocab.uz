from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Where the callback sends the browser after a successful login.
    frontend_url: str = "http://localhost:5173"


settings = Settings()
