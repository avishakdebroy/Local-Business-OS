"""The বাকি খাতা: balances must be derived, and never silently wrong."""

import pytest

from lbos.domain.errors import NotFoundError, ValidationError
from lbos.ledger import credit
from lbos.ledger import repositories as repo


@pytest.fixture
def rahim(conn):
    return credit.add_customer(conn, name="Rahim Mia", phone="01712345678")


def test_a_customer_is_matched_regardless_of_spacing_and_case(conn, rahim):
    assert credit.add_customer(conn, name="rahim   MIA") == rahim
    assert len(repo.customers_with_balance(conn, only_owing=False)) == 1


def test_a_customer_needs_a_name(conn):
    with pytest.raises(ValidationError, match="name"):
        credit.add_customer(conn, name="   ")


def test_credit_then_payment_moves_the_balance(conn, rahim):
    credit.give_credit(conn, customer_id=rahim, amount_paisa=45_000, entry_date="2026-09-08")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=30_000, entry_date="2026-09-10")
    assert repo.customer(conn, rahim)["balance_paisa"] == 75_000

    credit.take_payment(conn, customer_id=rahim, amount_paisa=50_000, entry_date="2026-09-11")
    assert repo.customer(conn, rahim)["balance_paisa"] == 25_000


def test_the_balance_is_derived_not_stored(conn, rahim):
    """Voiding an entry must change the balance with no separate update."""
    first = credit.give_credit(conn, customer_id=rahim, amount_paisa=45_000, entry_date="2026-09-08")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=30_000, entry_date="2026-09-09")
    assert repo.customer(conn, rahim)["balance_paisa"] == 75_000

    credit.void_entry(conn, first.entry_id, "entered twice")
    assert repo.customer(conn, rahim)["balance_paisa"] == 30_000


def test_overpayment_is_refused_with_the_real_balance_named(conn, rahim):
    credit.give_credit(conn, customer_id=rahim, amount_paisa=25_000, entry_date="2026-09-08")
    with pytest.raises(ValidationError, match="250.00"):
        credit.take_payment(conn, customer_id=rahim, amount_paisa=99_999, entry_date="2026-09-09")
    assert repo.customer(conn, rahim)["balance_paisa"] == 25_000


def test_a_zero_or_negative_amount_is_refused(conn, rahim):
    for bad in (0, -100):
        with pytest.raises(ValidationError, match="more than zero"):
            credit.give_credit(conn, customer_id=rahim, amount_paisa=bad, entry_date="2026-09-08")


def test_a_bad_date_is_refused(conn, rahim):
    with pytest.raises(ValidationError, match="date"):
        credit.give_credit(conn, customer_id=rahim, amount_paisa=1000, entry_date="not-a-date")


def test_an_unknown_customer_is_reported(conn):
    with pytest.raises(NotFoundError):
        credit.give_credit(conn, customer_id=4242, amount_paisa=1000, entry_date="2026-09-08")


def test_only_those_who_owe_are_listed_by_default(conn, rahim):
    salma = credit.add_customer(conn, name="Salma Begum")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=25_000, entry_date="2026-09-08")
    credit.give_credit(conn, customer_id=salma, amount_paisa=10_000, entry_date="2026-09-08")
    credit.take_payment(conn, customer_id=salma, amount_paisa=10_000, entry_date="2026-09-09")

    owing = [c["name"] for c in repo.customers_with_balance(conn, only_owing=True)]
    assert owing == ["Rahim Mia"]
    assert len(repo.customers_with_balance(conn, only_owing=False)) == 2


def test_the_statement_reads_down_the_page_like_paper(conn, rahim):
    credit.give_credit(conn, customer_id=rahim, amount_paisa=45_000, entry_date="2026-09-08")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=30_000, entry_date="2026-09-10")
    credit.take_payment(conn, customer_id=rahim, amount_paisa=50_000, entry_date="2026-09-11")

    entries = credit.statement(conn, rahim)["entries"]
    assert [e["balance_after"] for e in entries] == [25_000, 75_000, 45_000]


def test_totals_across_all_customers(conn, rahim):
    salma = credit.add_customer(conn, name="Salma Begum")
    credit.give_credit(conn, customer_id=rahim, amount_paisa=25_000, entry_date="2026-09-08")
    credit.give_credit(conn, customer_id=salma, amount_paisa=12_000, entry_date="2026-09-08")
    assert repo.credit_totals(conn) == {"outstanding_paisa": 37_000, "customers_owing": 2}


def test_customer_search_matches_name_or_phone(conn, rahim):
    credit.add_customer(conn, name="Salma Begum", phone="01999888777")
    assert [c["name"] for c in repo.customers_with_balance(conn, search="rahim")] == ["Rahim Mia"]
    assert [c["name"] for c in repo.customers_with_balance(conn, search="01999")] == ["Salma Begum"]
