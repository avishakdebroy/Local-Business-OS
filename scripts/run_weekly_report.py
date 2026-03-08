from app.db import init_db
from app.services.reporting import run_weekly_report
from app.services.storage import ensure_app_dirs


def main() -> None:
    ensure_app_dirs()
    init_db()
    out = run_weekly_report()
    print(out)


if __name__ == "__main__":
    main()
