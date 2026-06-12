from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация бота из .env."""

    bot_token: str
    admin_id: int = 0  # Telegram ID владельца; 0 = админ-команды выключены
    database_url: str = (
        "postgresql+asyncpg://nedolivsk:nedolivsk@localhost:5432/nedolivsk"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("database_url")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        """Railway/Render выдают postgres:// — приводим к asyncpg-драйверу."""
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

