"""The offline reader: what it gets right, and what it correctly refuses to guess."""

from datetime import date

import pytest

from lbos.interpretation.rules import amounts_in, extract, parse_stock_line

TODAY = date(2026, 9, 2)

BENGALI_RECEIPT = "মেসার্স রহিম স্টোর\nতারিখ: ০১/০৯/২০২৬\nমোট: ৳১,২৫০.৫০\nনগদ পরিশোধ"
ENGLISH_BILL = (
    "Karim Traders\nBill No. 4471\nDate: 30/08/2026\n"
    "Rice 2 bag\nOil 3 ltr\nSubtotal 2,450.00\nVAT 122.50\n"
    "Grand Total: Tk 2,572.50\nPaid by bKash"
)


def test_reads_an_english_bill():
    result = extract(ENGLISH_BILL, today=TODAY)
    assert result.fields["total_paisa"] == 257_250
    assert result.fields["tax_paisa"] == 12_250
    assert result.fields["entry_date"] == "2026-08-30"
    assert result.fields["party"] == "Karim Traders"
    assert result.fields["payment_method"] == "bkash"


def test_reads_a_bengali_receipt():
    result = extract(BENGALI_RECEIPT, today=TODAY)
    assert result.fields["total_paisa"] == 125_050
    assert result.fields["entry_date"] == "2026-09-01"
    assert result.fields["payment_method"] == "cash"


def test_quantities_are_not_read_as_money():
    """'2 bag' is a quantity; only 2,572.50 is the bill total."""
    assert [a.value for a in amounts_in("Rice 2 bag")] == []


def test_invoice_and_phone_numbers_are_not_read_as_money():
    assert [a.value for a in amounts_in("Bill No. 4471")] == []
    assert [a.value for a in amounts_in("Mobile: 01712345678")] == []


def test_a_labelled_total_wins_over_a_larger_number():
    text = "Item A 5000\nItem B 4000\nTotal 900"
    assert extract(text, today=TODAY).fields["total_paisa"] == 90_000


def test_an_ambiguous_direction_is_held_for_review():
    """Nothing in this bill says whether the shop sold or bought."""
    result = extract(ENGLISH_BILL, today=TODAY)
    assert result.confidence <= 0.6
    assert any("sale or a purchase" in note for note in result.notes)


def test_an_explicit_sale_is_classified_as_one():
    result = extract("Sold to customer. Grand Total 620 taka cash", today=TODAY)
    assert result.doc_type == "sale"


def test_a_missing_amount_forces_review():
    result = extract("Bought something from the market", hint="purchase", today=TODAY)
    assert result.fields["total_paisa"] is None
    assert result.confidence <= 0.2


def test_stock_lines_are_read():
    result = extract("received 20 kg miniket rice @ 62\nreceived 12 pcs soap", today=TODAY)
    assert result.doc_type == "stock"
    names = [line["name"] for line in result.fields["lines"]]
    assert names == ["miniket rice", "soap"]
    assert result.fields["lines"][0]["qty_milli"] == 20_000
    assert result.fields["lines"][0]["unit"] == "kg"
    assert result.fields["lines"][0]["unit_cost_paisa"] == 6_200
    assert all(line["direction"] == "in" for line in result.fields["lines"])


def test_cue_words_are_not_matched_inside_other_words():
    """'in' inside 'miniket' must not be stripped out of the item name."""
    draft = parse_stock_line("received 20 kg miniket rice")
    assert draft is not None
    assert draft.name == "miniket rice"


def test_an_ordinary_sentence_with_a_number_is_not_stock():
    result = extract("Shop closed early today for the storm. Reopen tomorrow 9am.", today=TODAY)
    assert result.doc_type == "memo"


def test_stock_direction_out_is_detected():
    result = extract("stock out 3 bottle soyabean oil damaged", today=TODAY)
    assert result.fields["lines"][0]["direction"] == "out"
    assert result.fields["lines"][0]["unit"] == "bottle"


def test_a_plain_note_is_confident():
    result = extract("Remember to call the landlord about the shutter.", today=TODAY)
    assert result.doc_type == "memo"
    assert result.confidence >= 0.85


def test_a_bare_number_is_not_guessed_at():
    result = extract("1250", today=TODAY)
    assert result.confidence < 0.5


def test_empty_text_is_handled():
    result = extract("", today=TODAY)
    assert result.doc_type == "memo"
    assert result.confidence <= 0.1


def test_missing_date_falls_back_to_today_and_says_so():
    result = extract("Sold. Total 500 taka", today=TODAY)
    assert result.fields["entry_date"] == "2026-09-02"
    assert any("No date" in note for note in result.notes)


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "!!!", "৳", "0"])
def test_extraction_never_raises(text):
    assert extract(text, today=TODAY) is not None
