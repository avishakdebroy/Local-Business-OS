"""The laptop side of phone pairing: show a QR code, manage paired phones."""

from __future__ import annotations

import io
import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from lbos.api.deps import get_conn, get_settings
from lbos.api.routers.common import context
from lbos.api.templating import redirect, templates
from lbos.phone import network, pairing
from lbos.settings import Settings

router = APIRouter(tags=["link"])


def qr_svg(url: str) -> str:
    """An inline SVG QR code. SVG keeps it crisp and avoids a PNG round-trip."""
    try:
        import qrcode
        import qrcode.image.svg

        image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        buffer = io.BytesIO()
        image.save(buffer)
        return buffer.getvalue().decode("utf-8")
    except Exception:
        return ""


@router.get("/link", response_class=HTMLResponse)
def link_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    address = network.lan_address()
    code = pairing.new_code(conn) if (settings.phone_link_enabled and address) else None
    url = f"http://{address}:{settings.port}/phone/pair?code={code}" if code else None

    return templates.TemplateResponse(
        request, "link.html",
        context(
            request, conn, "link",
            enabled=settings.phone_link_enabled,
            address=address,
            port=settings.port,
            code=code,
            url=url,
            qr=qr_svg(url) if url else "",
            devices=pairing.devices(conn),
            ttl_minutes=pairing.CODE_TTL_MINUTES,
        ),
    )


@router.post("/link/revoke/{device_id}")
def revoke(device_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    pairing.revoke(conn, device_id)
    return redirect("/link", "That phone has been unlinked.", "warn")


@router.post("/link/revoke-all")
def revoke_all(conn: sqlite3.Connection = Depends(get_conn)):
    count = pairing.revoke_all(conn)
    return redirect("/link", f"{count} phone(s) unlinked.", "warn")
