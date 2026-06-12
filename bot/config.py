from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация бота из .env."""

    bot_token: str
    database_url: str = (
        "postgresql+asyncpg://nedolivsk:nedolivsk@localhost:5432/nedolivsk"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encod