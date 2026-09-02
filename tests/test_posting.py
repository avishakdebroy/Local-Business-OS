"""The rule that matters: an automatic reading is a proposal, not a ledger row."""

from datetime import date

import pytest

from lbos.domain.errors import ConflictError, NotFoundError, ValidationError
from lbos.ledger import posting
from lbos.ledger import repositories as repo

TODAY = date(2026, 9, 2)

CLEAR_PURCHASE = (
    "Purchased from Karim Traders\nDate: 30/08/2026\n"
    "Grand Total: Tk 2,572.50\nVAT 122.50\nPaid by bKash"
)


def capture(conn, settings, text, hint="auto"):
    return posting.capture(conn, settings, text=text, hint=hint, today=TODAY)


def test_a_confident_reading_is_recorded(conn, settings):
    result = capture(conn, settings, CLEAR_PURCHASE, "purchase")
    assert result.status == "posted"
    assert repo.money_totals(conn, "2026-08-30", "2026-08-30")["purchase_paisa"] == 257_250


def test_an_unclear_reading_is_held_and_counts_for_nothing(conn, settings):
    result = capture(conn, settings, "Electricity bill 3400 taka")
    assert result.status == "pending_review"
    assert repo.money_totals(conn, "2026-01-01", "2026-12-31")["purchase_paisa"] == 0


def test_the_same_document_twice_is_not_counted_twice(conn, settings):
    first = capture(conn, settings, CLEAR_PURCHASE, "purchase")
    second = capture(conn, settings, CLEAR_PURCHASE, "purchase")
    assert second.is_duplicate
    assert second.document_id == first.document_id
    assert repo.money_totals(conn, "2026-08-30", "2026-08-30")["purchase_count"] == 1


def test_whitespace_changes_do_not_defeat_duplicate_detection(conn, settings):
    capture(conn, settings, CLEAR_PURCHASE, "purchase")
    noisy = CLEAR_PURCHASE.replace("\n", "\n  ").upper()
    assert capture(conn, settings, noisy, "purchase").is_duplicate


def test_two_photos_that_read_as_nothing_are_two_documents(conn, settings):
    """Files are identified by their bytes, so blank OCR cannot merge them."""
    from lbos.capture.storage import StoredFile

    first = posting.capture(
        conn, settings, text="", source_kind="file", today=TODAY,
        stored=StoredFile(settings.uploads_dir / "a.jpg", "a.jpg", 10, "hash-a"),
    )
    second = posting.capture(
        conn, settings, text="", source_kind="file", today=TODAY,
        stored=StoredFile(settings.uploads_dir / "b.jpg", "b.jpg", 10, "hash-b"),
    )
    assert not second.is_duplicate
    assert first.document_id != second.document_id
    assert second.status == "pending_review"


def test_an_unreadable_photo_is_kept_not_rejected(conn, settings):
    from lbos.capture.storage import StoredFile

    result = posting.capture(
        conn, settings, text="", source_kind="file", today=TODAY,
        warnings=["Could not read text from this photo."],
        stored=StoredFile(settings.uploads_dir / "c.jpg", "c.jpg", 10, "hash-c"),
    )
    assert result.status == "pending_review"
    assert repo.document(conn, result.document_id) is not None


def test_a_zero_amount_can_never_be_recorded(conn, settings):
    """The failure mode of a naive fallback: a stream of ৳0 receipts in the totals."""
    result = capture(conn, settings, "Electricity bill 3400 taka")
    with pytest.raises(ValidationError, match="more than zero"):
        posting.accept(conn, result.document_id, doc_type="purchase",
                       fields={"entry_date": "2026-09-02", "total_paisa": 0})


def test_vat_cannot_exceed_the_total(conn, settings):
    result = capture(conn, settings, "Electricity bill 3400 taka")
    with pytest.raises(ValidationError, match="VAT"):
        posting.accept(conn, result.document_id, doc_type="purchase",
                       fields={"entry_date": "2026-09-02", "total_paisa": 100, "tax_paisa": 200})


def test_an_invalid_date_is_refused(conn, settings):
    result = capture(conn, settings, "Electricity bill 3400 taka")
    with pytest.raises(ValidationError, match="date"):
        posting.accept(conn, result.document_id, doc_type="purchase",
                       fields={"entry_date": "not-a-date", "total_paisa": 100})


def test_accepting_a_held_entry_records_it(conn, settings):
    result = capture(conn, settings, "Electricity bill 3400 taka")
    posting.accept(conn, result.document_id, doc_type="purchase", fields={
        "entry_date": "2026-09-02", "total_paisa": 340_000, "party": "DESCO",
        "category": "utilities", "payment_method": "bkash",
    })
    assert repo.money_totals(conn, "2026-09-02", "2026-09-02")["purchase_paisa"] == 340_000
    assert repo.document(conn, result.document_id)["status"] == "posted"


def test_correcting_an_entry_supersedes_it_rather_than_duplicating(conn, settings):
    result = capture(conn, settings, "Electricity bill 3400 taka")
    for amount in (340_000, 300_000):
        posting.accept(conn, result.document_id, doc_type="purchase",
                       fields={"entry_date": "2026-09-02", "total_paisa": amount})

    totals = repo.money_totals(conn, "2026-09-02", "2026-09-02")
    assert totals["purchase_paisa"] == 300_000
    assert totals["purchase_count"] == 1

    # The superseded version is retained for audit, not deleted.
    rows = conn.execute(
        "SELECT total_paisa, voided_at FROM money_entries WHERE document_id = ? ORDER BY id",
        (result.document_id,),
    ).fetchall()
    assert [(r["total_paisa"], r["voided_at"] is not None) for r in rows] == [
        (340_000, True), (300_000, False),
    ]


def test_the_type_can_be_corrected_on_review(conn, settings):
    result = capture(conn, settings, "Electricity bill 3400 taka")
    posting.accept(conn, result.document_id, doc_type="memo", fields={
        "entry_date": "2026-09-02", "title": "Not a bill", "body": "filed by mistake",
    })
    assert repo.document(conn, result.document_id)["doc_type"] == "memo"
    assert repo.money_totals(conn, "2026-09-02", "2026-09-02")["purchase_paisa"] == 0


def test_discarding_an_entry_removes_it_from_the_books(conn, settings):
    result = capture(conn, settings, CLEAR_PURCHASE, "purchase")
    posting.reject(conn, result.document_id, note="not ours")
    assert repo.money_totals(conn, "2026-08-30", "2026-08-30")["purchase_paisa"] == 0
    assert repo.document(conn, result.document_id)["status"] == "rejected"


def test_undoing_a_recorded_entry_returns_it_to_review(conn, settings):
    result = capture(conn, settings, CLEAR_PURCHASE, "purchase")
    posting.unpost(conn, result.document_id, "wrong amount")
    assert repo.document(conn, result.document_id)["status"] == "pending_review"
    assert repo.money_totals(conn, "2026-08-30", "2026-08-30")["purchase_paisa"] == 0


def test_only_a_recorded_entry_can_be_undone(conn, settings):
    result = capture(conn, settings, "Electricity bill 3400 taka")
    with pytest.raises(ConflictError):
        posting.unpost(conn, result.document_id, "nope")


def test_an_unknown_entry_reports_clearly(conn, settings):
    with pytest.raises(NotFoundError):
        posting.reject(conn, 4242)


# --- Stock ------------------------------------------------------------------


def test_stock_on_hand_is_derived_from_movements(conn, settings):
    result = capture(conn, settings, "received 20 kg miniket rice", "stock")
    posting.accept(conn, result.document_id, doc_type="stock", fields={
        "entry_date": "2026-09-01",
        "lines": [{"name": "Miniket Rice", "qty_milli": 20_000, "unit": "kg", "direction": "in"}],
    })
    out = capture(conn, settings, "sold 5 kg miniket rice", "stock")
    posting.accept(conn, out.document_id, doc_type="stock", fields={
        "entry_date": "2026-09-02",
        "lines": [{"name": "miniket  rice", "qty_milli": 5_000, "unit": "kg", "direction": "out"}],
    })

    levels = repo.stock_levels(conn)
    assert len(levels) == 1, "case and spacing must not create a second item"
    assert levels[0]["on_hand_milli"] == 15_000


def test_stock_without_a_direction_is_refused(conn, settings):
    result = capture(conn, settings, "rice 20", "stock")
    with pytest.raises(ValidationError, match="in or went out"):
        posting.accept(conn, result.document_id, doc_type="stock", fields={
            "entry_date": "2026-09-02",
            "lines": [{"name": "rice", "qty_milli": 20_000, "unit": "kg", "direction": ""}],
        })


def test_low_stock_is_reported(conn, settings):
    result = capture(conn, settings, "received 2 kg rice", "stock")
    posting.accept(conn, result.document_id, doc_type="stock", fields={
        "entry_date": "2026-09-02",
        "lines": [{"name": "rice", "qty_milli": 2_000, "unit": "kg", "direction": "in"}],
    })
    item_id = repo.stock_levels(conn)[0]["item_id"]
    repo.set_reorder_level(conn, item_id, 5_000)
    conn.commit()
    assert [row["name"] for row in repo.stock_levels(conn, low_only=True)] == ["rice"]
