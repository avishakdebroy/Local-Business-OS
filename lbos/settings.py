"""Application configuration.

Settings are read once from the environment and ``.env``, then handed around
explicitly. Nothing imports a module-level singleton, so tests can build a
Settings pointed at a temporary directory without touching os.environ.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LBOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Storage ---
    data_dir: Path = Path("./data")

    # --- Locale ---
    timezone: str = "Asia/Dhaka"
    currency: str = "BDT"

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 8000

    # --- Phone link ---
    # Off by default. When on, the server also listens on the local network so
    # the shopkeeper's phone can reach it; remote clients are confined to the
    # /phone pages and must present a paired-device token.
    phone_link_enabled: bool = False

    # --- OCR ---
    ocr_enabled: bool = True
    ocr_lang: str = "ben+eng"
    tesseract_cmd: str = ""

    # --- Optional local LLM assist (off by default: the app is useful without it) ---
    llm_enabled: bool = False
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_timeout_seconds: int = 60

    # --- Review policy ---
    auto_post_threshold: float = Field(default=0.85, ge=0.0, le=1.0)

    # --- Scheduler ---
    scheduler_enabled: bool = True
    report_day: str = "sun"
    report_hour: int = Field(default=20, ge=0, le=23)
    report_minute: int = Field(default=0, ge=0, le=59)
    backup_hour: int = Field(default=3, ge=0, le=23)
    backup_minute: int = Field(default=0, ge=0, le=59)
    backup_keep: int = Field(default=14, ge=1)

    # --- Email (optional) ---
    report_email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # --- Offsite copy (optional) ---
    rclone_remote: str = ""
    rclone_path: str = "lbos-backups"

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    # --- Derived paths ---
    @property
    def bind_host(self) -> str:
        """Listening address. Loopback unless the phone link is switched on."""
        return "0.0.0.0" if self.phone_link_enabled else self.host  # noqa: S104

    @property
    def db_path(self) -> Path:
        return self.data_dir / "shop.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.uploads_dir,
            self.reports_dir,
            self.backups_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.report_email_to)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
