"""The বাকি খাতা screens: who owes money, and each customer's page."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from lbos.api.deps import get_conn, get_settings
from lbos.api.forms import _paisa  # noqa: PLC2701 - same edge-parsing rules apply here
from lbos.api.routers.common import context
from lbos.api.templating import redirect, templates
from lbos.domain.errors import NotFoundError, ValidationError
from lbos.domain.periods import iso, local_today
from lbos.ledger import credit
from lbos.ledger import repositories as repo
from lbos.settings import Settings

router = APIRouter(tags=["khata"])


@router.get("/khata", response_class=HTMLResponse)
def khata(
    request: Request,
    q: str = "",
    show: str = "owing",
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    customers = repo.customers_with_balance(
        conn, only_owing=(show != "all"), search=q.strip() or None
    )
    return templates.TemplateResponse(
        request, "khata.html",
        context(
            request, conn, "khata",
            customers=customers,
            totals=repo.credit_totals(conn),
            q=q,
            show=show,
            today=iso(local_today(settings.timezone)),
        ),
    )


@router.post("/khata/new")
def new_customer(
    name: str = Form(...),
    phone: str = Form(""),
    note: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        customer_id = credit.add_customer(
            conn, name=name, phone=phone.strip() or None, note=note.strip() or None
        )
    except ValidationError as exc:
        return redirect("/khata", str(exc), "error")
    return redirect(f"/khata/{customer_id}", f"{name.strip()} added.", "ok")


@router.get("/khata/{customer_id}", response_class=HTMLResponse)
def customer_page(
    customer_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    try:
        data = credit.statement(conn, customer_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    return templates.TemplateResponse(
        request, "khata_customer.html",
        context(
            request, conn, "khata",
            customer=data["customer"],
            entries=data["entries"],
            today=iso(local_today(settings.timezone)),
            kind_labels=credit.KIND_LABELS,
        ),
    )


@router.post("/khata/{customer_id}/entry")
async def add_entry(
    customer_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    form = await request.form()
    kind = str(form.get("kind") or "").strip()
    try:
        amount = _paisa(form, "amount", "Amount", required=True)
        result = credit.record(
            conn,
            customer_id=customer_id,
            kind=kind,
            amount_paisa=amount,
            entry_date=str(form.get("entry_date") or ""),
            note=str(form.get("note") or "").strip() or None,
        )
    except ValidationError as exc:
        return redirect(f"/khata/{customer_id}", str(exc), "error")
    except NotFoundError as exc:
        return redirect("/khata", str(exc), "error")
    return redirect(f"/khata/{customer_id}", result.message, "ok")


@router.post("/khata/{customer_id}/entry/{entry_id}/void")
def void_entry(
    customer_id: int,
    entry_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        credit.void_entry(conn, entry_id, "Removed by the operator.")
    except NotFoundError as exc:
        return redirect(f"/khata/{customer_id}", str(exc), "error")
    return redirect(f"/khata/{customer_id}", "Entry removed. The balance is updated.", "warn")
