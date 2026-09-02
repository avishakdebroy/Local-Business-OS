"""Money must be exact and must survive Bengali numerals."""

from decimal import Decimal

import pytest

from lbos.domain.money import Money, format_paisa, group_bd, parse_money


def test_float_amounts_do_not_drift():
    total = Money.zero()
    for _ in range(10):
        total = total + Money.from_taka("0.10")
    assert total.paisa == 100
    assert total.taka == Decimal("1.00")


def test_summing_a_thousand_entries_is_exact():
    total = sum((Money.from_taka("19.99") for _ in range(1000)), Money.zero())
    assert total.paisa == 1_999_000


@pytest.mark.parametrize(
    "text,paisa",
    [
        ("1250", 125_000),
        ("1,250.50", 125_050),
        ("৳১,২৫০.৫০", 125_050),
        ("মোট: ৳১২৫০ টাকা", 125_000),
        ("Total Tk 12345678/-", 1_234_567_800),
        ("Grand Total 2,572.50", 257_250),
        ("৯৯৯", 99_900),
    ],
)
def test_parse_money(text, paisa):
    parsed = parse_money(text)
    assert parsed is not None
    assert parsed.paisa == paisa


def test_parse_money_returns_none_without_a_number():
    assert parse_money("no amount here") is None


def test_rounding_is_half_up():
    assert Money.from_taka("0.005").paisa == 1
    assert Money.from_taka("0.004").paisa == 0


def test_south_asian_digit_grouping():
    assert group_bd("12345678") == "1,23,45,678"
    assert group_bd("999") == "999"
    assert format_paisa(1_234_567_890) == "৳1,23,45,678.90"
    assert format_paisa(-50_000) == "-৳500.00"


def test_currencies_cannot_be_mixed():
    with pytest.raises(ValueError):
        Money(100, "BDT") + Money(100, "USD")


def test_paisa_must_be_an_integer():
    with pytest.raises(TypeError):
        Money(12.5)
