from app.db import init_db
from app.services.backup import run_backup
from app.services.storage import ensure_app_dirs


def main() -> None:
    ensure_app_dirs()
    init_db()
    out = run_backup()
    print(out)


if __name__ == "__main__":
    main()
