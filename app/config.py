"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """App-wide settings loaded from environment variables."""

    APP_ENV: str = "development"
    FRONTEND_ORIGIN: str = "https://xuebao123321.github.io"
    DATABASE_URL: str = "sqlite+aiosqlite:///./app.db"
    STORAGE_DIR: str = "./storage"

    # Quota defaults (MVP: single user, no auth)
    MAX_VIDEOS_FREE: int = 5
    MAX_VIDEOS_MEMBER: int = 30
    MAX_VIDEOS_VIP: int = 300

    # Feature flags – all disabled by default for MVP 1
    ENABLE_TRANSCRIPTION: bool = False
    OPENAI_API_KEY: str = ""
    ENABLE_VIDEO_DOWNLOAD: bool = False

    # Safety limits
    JOB_TIMEOUT_SECONDS: int = 1800  # 30 minutes
    MAX_FILE_SIZE_MB: int = 500

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
