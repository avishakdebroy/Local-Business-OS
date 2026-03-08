from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    app_data_dir: Path
    app_db_path: Path
    app_timezone: str

    llm_enabled: bool
    llm_base_url: str
    llm_model: str

    ocr_lang: str

    scheduler_enabled: bool
    report_day: str
    report_hour: int
    report_minute: int
    report_email_to: str

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_use_tls: bool

    rclone_remote: str
    rclone_path: str


settings = Settings(
    app_data_dir=Path(os.getenv("APP_DATA_DIR", "./data")),
    app_db_path=Path(os.getenv("APP_DB_PATH", "./data/shop.db")),
    app_timezone=os.getenv("APP_TIMEZONE", "Asia/Dhaka"),
    llm_enabled=_as_bool(os.getenv("LLM_ENABLED"), True),
    llm_base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434"),
    llm_model=os.getenv("LLM_MODEL", "qwen2.5:7b-instruct"),
    ocr_lang=os.getenv("OCR_LANG", "eng+ben"),
    scheduler_enabled=_as_bool(os.getenv("SCHEDULER_ENABLED"), True),
    report_day=os.getenv("REPORT_DAY", "sun"),
    report_hour=int(os.getenv("REPORT_HOUR", "20")),
    report_minute=int(os.getenv("REPORT_MINUTE", "0")),
    report_email_to=os.getenv("REPORT_EMAIL_TO", ""),
    smtp_host=os.getenv("SMTP_HOST", ""),
    smtp_port=int(os.getenv("SMTP_PORT", "587")),
    smtp_user=os.getenv("SMTP_USER", ""),
    smtp_password=os.getenv("SMTP_PASSWORD", ""),
    smtp_from=os.getenv("SMTP_FROM", ""),
    smtp_use_tls=_as_bool(os.getenv("SMTP_USE_TLS"), True),
    rclone_remote=os.getenv("RCLONE_REMOTE", ""),
    rclone_path=os.getenv("RCLONE_PATH", "shop-backups"),
)
