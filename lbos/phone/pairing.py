"""Pairing a phone, and checking it afterwards.

The threat model is a shop's own Wi-Fi, not the open internet: the risk worth
defending against is a neighbour on the same network poking at the books, not a
determined attacker. So pairing is a short-lived six-digit code exchanged once
for a long random token, the token is stored hashed, and the owner can revoke a
phone from the laptop at any time.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from lbos.db.connection import transaction
from lbos.domain.errors import ValidationError
from lbos.domain.periods import now_utc, now_utc_iso

COOKIE_NAME = "lbos_device"
CODE_TTL_MINUTES = 10
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> str:
    return now_utc_iso()


def new_code(conn: sqlite3.Connection) -> str:
    """Mint a pairing code to show on the laptop screen."""
    code = f"{secrets.randbelow(10**6):06d}"
    expires = (now_utc() + timedelta(minutes=CODE_TTL_MINUTES)).replace(microsecond=0)
    with transaction(conn):
        conn.execute("DELETE FROM pairing_codes WHERE expires_at < ?", (_now(),))
        conn.execute(
            "INSERT OR REPLACE INTO pairing_codes (code, expires_at, created_at) VALUES (?, ?, ?)",
            (code, expires.isoformat().replace("+00:00", "Z"), _now()),
        )
    return code


def redeem(conn: sqlite3.Connection, code: str, device_name: str = "Phone") -> str:
    """Exchange a valid code for a device token. The code cannot be reused."""
    row = conn.execute(
        "SELECT * FROM pairing_codes WHERE code = ? AND used_at IS NULL AND expires_at >= ?",
        ((code or "").strip(), _now()),
    ).fetchone()
    if row is None:
        raise ValidationError(
            "That pairing code is wrong or has expired. "
            "Press “Link my phone” on the computer again for a fresh one."
        )

    token = secrets.token_urlsafe(TOKEN_BYTES)
    with transaction(conn):
        conn.execute("UPDATE pairing_codes SET used_at = ? WHERE code = ?", (_now(), code))
        conn.execute(
            "INSERT INTO paired_devices (name, token_hash, created_at, last_seen_at)"
            " VALUES (?, ?, ?, ?)",
            (device_name.strip()[:60] or "Phone", _hash(token), _now(), _now()),
        )
    return token


def device_for(conn: sqlite3.Connection, token: str | None) -> dict[str, Any] | None:
    """The live device this token belongs to, or None."""
    if not token:
        return None
    row = conn.execute(
        "SELECT * FROM paired_devices WHERE token_hash = ? AND revoked_at IS NULL",
        (_hash(token),),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE paired_devices SET last_seen_at = ? WHERE id = ?", (_now(), row["id"]))
    conn.commit()
    return dict(row)


def devices(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM paired_devices WHERE revoked_at IS NULL ORDER BY id DESC"
        )
    ]


def revoke(conn: sqlite3.Connection, device_id: int) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE paired_devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (_now(), device_id),
        )


def revoke_all(conn: sqlite3.Connection) -> int:
    with transaction(conn):
        cursor = conn.execute(
            "UPDATE paired_devices SET revoked_at = ? WHERE revoked_at IS NULL", (_now(),)
        )
    return cursor.rowcount
