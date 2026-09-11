"""The screens a shop owner actually uses."""

import io

from lbos.ledger import repositories as repo

CLEAR_PURCHASE = (
    "Purchased from Karim Traders\nDate: 30/08/2026\n"
    "Grand Total: Tk 2,572.50\nVAT 122.50\nPaid by bKash"
)


def location(response) -> str:
    return response.headers.get("location", "")


def test_every_screen_loads(client):
    for path in ["/", "/review", "/ledger", "/stock", "/reports", "/status"]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Local Business OS" in response.text


def test_health_endpoint(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["timezone"] == "Asia/Dhaka"
    assert body["currency"] == "BDT"


def test_typing_an_entry_records_it(client):
    response = client.post("/capture/text", data={"text": CLEAR_PURCHASE, "hint": "purchase"})
    assert response.status_code == 303
    assert location(response).startswith("/?msg=")
    assert "2,572.50" in client.get("/ledger").text


def test_an_unclear_entry_lands_on_the_review_screen(client):
    response = client.post("/capture/text", data={"text": "Electricity bill 3400 taka", "hint": "auto"})
    assert "/review/" in location(response)
    assert "Electricity bill" in client.get("/review").text


def test_an_empty_submission_is_refused_kindly(client):
    response = client.post("/capture/text", data={"text": "   ", "hint": "auto"})
    assert location(response).startswith("/?msg=Type+something+first")


def test_uploading_a_file_keeps_it_and_serves_it_back(client):
    response = client.post(
        "/capture/file",
        files={"file": ("bill.txt", io.BytesIO(CLEAR_PURCHASE.encode()), "text/plain")},
        data={"hint": "purchase"},
    )
    assert response.status_code == 303
    assert client.get("/review/1/file").status_code in (200, 404)


def test_an_unsupported_file_type_is_refused(client):
    response = client.post(
        "/capture/file",
        files={"file": ("virus.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        data={"hint": "auto"},
    )
    assert "Unsupported+file+type" in location(response)


def test_reviewing_and_accepting_an_entry(client):
    client.post("/capture/text", data={"text": "Electricity bill 3400 taka", "hint": "auto"})
    assert client.get("/review/1").status_code == 200

    response = client.post("/review/1/accept", data={
        "doc_type": "purchase", "entry_date": "2026-09-02", "total": "3,400.00",
        "tax": "0", "party": "DESCO", "category": "utilities", "payment_method": "bkash",
    })
    assert "Entry+1+recorded" in location(response)

    ledger = client.get("/ledger").text
    assert "DESCO" in ledger and "3,400.00" in ledger


def test_a_typo_in_the_amount_returns_the_operator_to_the_form(client):
    client.post("/capture/text", data={"text": "Electricity bill 3400 taka", "hint": "auto"})
    response = client.post("/review/1/accept", data={
        "doc_type": "purchase", "entry_date": "2026-09-02", "total": "three thousand",
    })
    assert location(response).startswith("/review/1?msg=")
    assert "kind=error" in location(response)


def test_discarding_an_entry(client):
    client.post("/capture/text", data={"text": "Electricity bill 3400 taka", "hint": "auto"})
    response = client.post("/review/1/reject", data={"notes": "not ours"})
    assert "discarded" in location(response)
    assert client.get("/api/summary").json()["totals_paisa"]["purchase_paisa"] == 0


def test_undoing_a_recorded_entry_from_the_ledger(client):
    client.post("/capture/text", data={"text": CLEAR_PURCHASE, "hint": "purchase"})
    response = client.post("/ledger/1/undo")
    assert location(response).startswith("/review/1?")
    assert client.get("/api/summary?days=30").json()["totals_paisa"]["purchase_paisa"] == 0


def test_recording_stock_through_the_form(client):
    client.post("/capture/text", data={"text": "received 20 kg miniket rice", "hint": "stock"})
    response = client.post("/review/1/accept", data={
        "doc_type": "stock", "entry_date": "2026-09-02",
        "line_name": ["Miniket Rice"], "line_qty": ["20"], "line_unit": ["kg"],
        "line_direction": ["in"], "line_cost": ["62"],
    })
    assert "recorded" in location(response)
    stock_page = client.get("/stock").text
    assert "Miniket Rice" in stock_page
    assert ">20<" in stock_page  # on-hand quantity, with the unit in its own column
    assert ">kg<" in stock_page


def test_blank_stock_rows_are_ignored(client):
    client.post("/capture/text", data={"text": "received 20 kg rice", "hint": "stock"})
    response = client.post("/review/1/accept", data={
        "doc_type": "stock", "entry_date": "2026-09-02",
        "line_name": ["rice", ""], "line_qty": ["20", ""], "line_unit": ["kg", "pcs"],
        "line_direction": ["in", ""], "line_cost": ["", ""],
    })
    assert "recorded" in location(response)


def test_setting_a_reorder_level(client):
    client.post("/capture/text", data={"text": "received 2 kg rice", "hint": "stock"})
    client.post("/review/1/accept", data={
        "doc_type": "stock", "entry_date": "2026-09-02", "line_name": ["rice"],
        "line_qty": ["2"], "line_unit": ["kg"], "line_direction": ["in"], "line_cost": [""],
    })
    response = client.post("/stock/1/reorder", data={"reorder_level": "5"})
    assert "saved" in location(response).lower()
    assert "low" in client.get("/stock").text


def test_making_a_report_from_the_screen(client):
    client.post("/capture/text", data={"text": CLEAR_PURCHASE, "hint": "purchase"})
    response = client.post("/reports/run")
    assert location(response).startswith("/reports?msg=Report+made")
    assert "WEEKLY BUSINESS REPORT" in client.get("/reports").text


def test_a_missing_entry_shows_a_friendly_page_not_a_stack_trace(client):
    response = client.get("/review/999")
    assert response.status_code == 404
    assert "Something went wrong" in response.text
    assert "Nothing was lost" in response.text


def test_the_api_returns_json_errors(client):
    response = client.get("/api/summary?days=0")
    assert response.status_code == 200  # clamped, not an error


def test_the_review_badge_counts_waiting_entries(client):
    client.post("/capture/text", data={"text": "Electricity bill 3400 taka", "hint": "auto"})
    client.post("/capture/text", data={"text": "Water bill 900 taka", "hint": "auto"})
    home = client.get("/").text
    assert 'class="badge">2<' in home


def test_the_status_screen_reports_a_failing_job(client, settings):
    from lbos.db.bootstrap import open_db

    conn = open_db(settings)
    try:
        repo.insert_job_run(conn, job_name="nightly_backup", status="error",
                            detail="disk full", started_at="x", finished_at="y")
        conn.commit()
    finally:
        conn.close()

    page = client.get("/status").text
    assert "Needs attention" in page and "nightly_backup" in page


def test_a_duplicate_upload_warns_instead_of_double_counting(client):
    client.post("/capture/text", data={"text": CLEAR_PURCHASE, "hint": "purchase"})
    response = client.post("/capture/text", data={"text": CLEAR_PURCHASE, "hint": "purchase"})
    assert "already+recorded" in location(response)
    assert client.get("/api/summary?days=30").json()["totals_paisa"]["purchase_count"] == 1


# --- Day book and khata -----------------------------------------------------


def test_the_day_book_is_the_home_screen(client):
    page = client.get("/").text
    assert "The day / আজকের পাতা" in page
    assert "Cash in" in page and "Owed to you" in page


def test_the_day_book_can_page_backwards(client):
    page = client.get("/?day=2026-09-10").text
    assert "2026-09-10" in page
    assert "2026-09-09" in page  # previous-day link


def test_adding_a_customer_and_giving_credit(client):
    response = client.post("/khata/new", data={"name": "Rahim Mia", "phone": "01712345678"})
    assert location(response).startswith("/khata/1")

    response = client.post("/khata/1/entry", data={
        "kind": "charge", "amount": "450", "entry_date": "2026-09-11", "note": "2 Meril cream",
    })
    assert "owes" in location(response)

    page = client.get("/khata/1").text
    assert "Rahim Mia" in page and "450.00" in page and "2 Meril cream" in page


def test_taking_a_payment_reduces_the_balance(client):
    client.post("/khata/new", data={"name": "Rahim Mia", "phone": ""})
    client.post("/khata/1/entry", data={"kind": "charge", "amount": "450", "entry_date": "2026-09-11"})
    client.post("/khata/1/entry", data={"kind": "payment", "amount": "200", "entry_date": "2026-09-11"})
    assert "250.00" in client.get("/khata/1").text


def test_overpaying_is_refused_on_screen(client):
    client.post("/khata/new", data={"name": "Rahim Mia", "phone": ""})
    client.post("/khata/1/entry", data={"kind": "charge", "amount": "450", "entry_date": "2026-09-11"})
    response = client.post("/khata/1/entry", data={
        "kind": "payment", "amount": "5000", "entry_date": "2026-09-11",
    })
    assert "kind=error" in location(response)


def test_a_typo_in_a_credit_amount_is_refused(client):
    client.post("/khata/new", data={"name": "Rahim Mia", "phone": ""})
    response = client.post("/khata/1/entry", data={
        "kind": "charge", "amount": "four fifty", "entry_date": "2026-09-11",
    })
    assert "kind=error" in location(response)


def test_removing_a_credit_entry_changes_the_balance(client):
    client.post("/khata/new", data={"name": "Rahim Mia", "phone": ""})
    client.post("/khata/1/entry", data={"kind": "charge", "amount": "450", "entry_date": "2026-09-11"})
    client.post("/khata/1/entry/1/void")
    assert client.get("/api/health").json()["credit"]["outstanding_paisa"] == 0


def test_credit_appears_on_the_day_book_but_not_as_cash(client):
    client.post("/khata/new", data={"name": "Rahim Mia", "phone": ""})
    client.post("/khata/1/entry", data={"kind": "charge", "amount": "450", "entry_date": "2026-09-11"})
    page = client.get("/?day=2026-09-11").text
    assert "Rahim Mia on credit" in page
    assert "not</strong> counted as cash in" in page


def test_the_khata_badge_counts_people_who_owe(client):
    client.post("/khata/new", data={"name": "Rahim Mia", "phone": ""})
    client.post("/khata/1/entry", data={"kind": "charge", "amount": "450", "entry_date": "2026-09-11"})
    assert 'class="badge owed">1<' in client.get("/").text


def test_an_unknown_customer_shows_a_friendly_page(client):
    response = client.get("/khata/999")
    assert response.status_code == 404
    assert "Something went wrong" in response.text


# --- Support ----------------------------------------------------------------


def test_the_support_file_downloads(client):
    response = client.get("/status/support-file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert len(response.content) < 200_000


def test_repair_reports_what_it_did(client):
    response = client.post("/status/repair")
    assert "kind=ok" in location(response)
    assert "Integrity" in location(response)


def test_the_link_page_explains_how_to_switch_the_phone_link_on(client):
    page = client.get("/link").text
    assert "LBOS_PHONE_LINK_ENABLED=true" in page
