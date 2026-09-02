"""Command line entry point.

``lbos serve`` runs the app; the other subcommands exist so Windows Task
Scheduler can run a report or a backup without the web server being up.
"""

from __future__ import annotations

import argparse
import sys

from lbos import __version__
from lbos.db.bootstrap import open_db, prepare
from lbos.ops.backup import run_backup
from lbos.reporting.weekly import run_weekly_report
from lbos.settings import get_settings


def _force_utf8_output() -> None:
    """Print Bengali safely on a Windows console.

    cmd.exe defaults to a legacy code page (437/1252), and the weekly report is
    bilingual, so an unconfigured console raises UnicodeEncodeError partway
    through printing it. The .bat launchers also switch the console to UTF-8;
    this covers the case where the CLI is run some other way.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - platform dependent
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(prog="lbos", description="Local Business OS")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the web application")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    sub.add_parser("migrate", help="create or update the database, then exit")
    sub.add_parser("report", help="generate the weekly report now")

    backup = sub.add_parser("backup", help="make a backup now")
    backup.add_argument("--full", action="store_true", help="include uploaded files")

    args = parser.parse_args(argv)
    settings = get_settings()
    command = args.command or "serve"

    if command == "migrate":
        applied = prepare(settings)
        print(f"Database ready at {settings.db_path} ({len(applied)} migration(s) applied).")
        return 0

    if command == "report":
        prepare(settings)
        conn = open_db(settings)
        try:
            result = run_weekly_report(conn, settings)
        finally:
            conn.close()
        print(result["text"])
        print(f"\nEmail: {result['delivery_status']} - {result['delivery_detail']}")
        return 0

    if command == "backup":
        prepare(settings)
        result = run_backup(settings, include_uploads=args.full)
        print(result.as_dict())
        return 0 if result.status == "ok" else 1

    import uvicorn

    prepare(settings)
    uvicorn.run(
        "lbos.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
