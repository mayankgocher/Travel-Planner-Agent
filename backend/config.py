"""Load server-side configuration explicitly, not at module import time."""
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8-sig",
        extra="ignore", hide_input_in_errors=True,
    )
    # Exclude secrets even from model_dump(); only provider clients will unwrap.
    groq_api_key: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    serpapi_api_key: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    railradar_api_key: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    groq_model: str = "openai/gpt-oss-120b"
    backend_url: str = "http://127.0.0.1:8000"
    app_timezone: str = "Asia/Kolkata"
    data_dir: Path = Path("data")

    def require_provider_key(self, provider: str) -> str:
        """Called only when an explicitly requested live operation needs a key."""
        keys = {"groq": self.groq_api_key, "serpapi": self.serpapi_api_key,
                "railradar": self.railradar_api_key}
        if provider not in keys:
            raise ValueError("Unknown provider")
        value = keys[provider].get_secret_value().strip()
        if not value:
            raise ValueError(f"Add {provider.upper()}_API_KEY to the local .env")
        return value

    @property
    def data_path(self) -> Path:
        return self.data_dir if self.data_dir.is_absolute() else PROJECT_ROOT / self.data_dir
