"""Settings, read from environment variables only.

DB_NAME, DB_USER and DB_PASSWORD have no defaults: a missing value is an error, never a guess.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

REPO_ROOT = Path(__file__).resolve().parents[2]

# CelesTrak asks clients not to re-download the same data more often than every 2 hours.
CELESTRAK_MIN_REFRESH_HOURS = 2.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    db_name: str = Field(min_length=1)
    db_user: str = Field(min_length=1)
    db_password: SecretStr
    db_host: str = "localhost"
    db_port: int = 3306

    config_dir: Path = REPO_ROOT / "config"
    orbital_refresh_hours: float = Field(12.0, ge=CELESTRAK_MIN_REFRESH_HOURS)
    pass_window_hours: float = Field(48.0, gt=0, le=24 * 14)

    @property
    def database_url(self) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
