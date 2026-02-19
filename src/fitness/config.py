from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    garmin_email: str = ""
    garmin_password: str = ""
    telegram_bot_token: str = ""
    telegram_allowed_user_id: Optional[int] = None
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    database_url: str = "sqlite:///./fitness.db"
    max_hr: int = 185
    garmin_sync_hour: int = 3
    user_id: int = 1  # single-user MVP; multi-user: swap for JWT claim

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
