"""The day book must never present credit as cash in the drawer."""

from datetime import date

from lbos.ledger import credit, posting
from lbos.reporting.daybook import build

DAY = date(2026, 9, 11)


def test_an_empty_day_is_an_empty_page(conn):
    book = build(conn, DAY)
    assert book["lines"] == []
    assert book["net_cash_paisa"] == 0


def test_cash_sales_and_purchases_move_the_cash_position(conn, settings):
    posting.capture(conn, settings, text="Sold. Grand Total 1250 taka cash. Date: 11/09/2026",
                    hint="sale", today=DAY)
    posting.capture(conn, settings,
                    text="Purchase. Date: 11/09/2026. Grand Total: Tk 840. Paid by bKash",
                    hint="purchase", today=DAY)
    book = build(conn, DAY)
    assert book["cash_in_paisa"] == 125_000
    assert book["cash_out_paisa"] == 84_000
    assert book["net_cash_paisa"] == 41_000


def test_goods_given_on_credit_are_not_cash_in(conn):
    """The defect this guards: a day book that teaches the owner to over-count."""
    rahim = credit.add_customer(conn, name="Rahim Mia")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=45_000, entry_date="2026-09-11")

    book = build(conn, DAY)
    assert book["credit_given_paisa"] == 45_000
    assert book["cash_in_paisa"] == 0
    assert book["net_cash_paisa"] == 0


def test_a_repayment_is_cash_in(conn):
    rahim = credit.add_customer(conn, name="Rahim Mia")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=45_000, entry_date="2026-09-10")
    credit.take_payment(conn, customer_id=rahim, amount_paisa=20_000, entry_date="2026-09-11")

    book = build(conn, DAY)
    assert book["cash_in_paisa"] == 20_000
    assert book["credit_received_paisa"] == 20_000
    assert book["credit_given_paisa"] == 0  # the charge was yesterday


def test_a_sale_booked_to_due_is_revenue_but_not_cash(conn, settings):
    result = posting.capture(conn, settings, text="Sold on credit. Total 500 taka",
                             hint="sale", today=DAY)
    posting.accept(conn, result.document_id, doc_type="sale", fields={
        "entry_date": "2026-09-11", "total_paisa": 50_000, "payment_method": "due",
    })
    book = build(conn, DAY)
    assert book["cash_in_paisa"] == 0
    assert any(line["detail"].startswith("on credit") for line in book["lines"])


def test_the_page_only_shows_its_own_day(conn):
    rahim = credit.add_customer(conn, name="Rahim Mia")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=10_000, entry_date="2026-09-10")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=20_000, entry_date="2026-09-11")

    assert build(conn, DAY)["credit_given_paisa"] == 20_000
    assert build(conn, date(2026, 9, 10))["credit_given_paisa"] == 10_000


def test_outstanding_is_the_running_total_not_just_today(conn):
    rahim = credit.add_customer(conn, name="Rahim Mia")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=10_000, entry_date="2026-09-01")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=20_000, entry_date="2026-09-11")

    book = build(conn, DAY)
    assert book["outstanding_paisa"] == 30_000
    assert book["customers_owing"] == 1


def test_neighbouring_days_are_offered_for_paging(conn):
    book = build(conn, DAY)
    assert book["previous_day"] == "2026-09-10"
    assert book["next_day"] == "2026-09-12"
