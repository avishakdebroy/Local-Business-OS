"""The optional AI assist must help without ever bypassing review."""

from datetime import date

from lbos.domain.entities import Extraction
from lbos.interpretation import pipeline
from lbos.interpretation.pipeline import decide_status, interpret

TODAY = date(2026, 9, 2)
CLEAR = "Purchased from Karim Traders\nDate: 30/08/2026\nGrand Total: Tk 2,572.50\nPaid by bKash"


def llm_returning(extraction):
    return lambda text, settings, hint="auto", today=None: extraction


def test_the_app_works_with_the_model_switched_off(settings):
    assert not settings.llm_enabled
    result = interpret(CLEAR, settings, hint="purchase", today=TODAY)
    assert result.extractor == "rules"
    assert result.fields["total_paisa"] == 257_250


def test_the_model_being_unreachable_changes_nothing(settings, monkeypatch):
    enabled = settings.model_copy(update={"llm_enabled": True, "llm_base_url": "http://127.0.0.1:1"})
    result = interpret(CLEAR, enabled, hint="purchase", today=TODAY)
    assert result.extractor == "rules"
    assert result.fields["total_paisa"] == 257_250


def test_agreement_raises_confidence_a_little(settings, monkeypatch):
    enabled = settings.model_copy(update={"llm_enabled": True})
    agreeing = Extraction("purchase", 0.9, {"total_paisa": 257_250}, "llm")
    monkeypatch.setattr(pipeline.llm, "extract", llm_returning(agreeing))

    baseline = interpret(CLEAR, settings, hint="purchase", today=TODAY).confidence
    assisted = interpret(CLEAR, enabled, hint="purchase", today=TODAY)
    assert assisted.confidence >= baseline
    assert assisted.extractor == "rules+llm"


def test_disagreement_on_the_amount_forces_review(settings, monkeypatch):
    enabled = settings.model_copy(update={"llm_enabled": True})
    disagreeing = Extraction("purchase", 0.99, {"total_paisa": 999_999}, "llm")
    monkeypatch.setattr(pipeline.llm, "extract", llm_returning(disagreeing))

    result = interpret(CLEAR, enabled, hint="purchase", today=TODAY)
    assert decide_status(result, enabled) == "pending_review"
    assert any("Please check" in note for note in result.notes)
    # The rules reading is kept; the model does not overwrite it.
    assert result.fields["total_paisa"] == 257_250


def test_disagreement_on_the_type_forces_review(settings, monkeypatch):
    enabled = settings.model_copy(update={"llm_enabled": True})
    monkeypatch.setattr(
        pipeline.llm, "extract", llm_returning(Extraction("memo", 0.99, {}, "llm"))
    )
    result = interpret(CLEAR, enabled, hint="purchase", today=TODAY)
    assert decide_status(result, enabled) == "pending_review"
    assert result.doc_type == "purchase"


def test_the_model_can_fill_a_blank_the_rules_left(settings, monkeypatch):
    enabled = settings.model_copy(update={"llm_enabled": True})
    monkeypatch.setattr(
        pipeline.llm, "extract",
        llm_returning(Extraction("purchase", 0.8, {"category": "supplies"}, "llm")),
    )
    result = interpret(CLEAR, enabled, hint="purchase", today=TODAY)
    assert result.fields["category"] == "supplies"


def test_a_missing_required_field_holds_the_entry_however_confident(settings):
    over_confident = Extraction("purchase", 1.0, {"entry_date": "2026-09-02"}, "rules")
    assert decide_status(over_confident, settings) == "pending_review"
    assert pipeline.blocking_gaps(over_confident) == ["total_paisa"]


def test_stock_without_a_direction_is_a_blocking_gap(settings):
    extraction = Extraction(
        "stock", 1.0,
        {"entry_date": "2026-09-02", "lines": [{"name": "rice", "qty_milli": 1000, "direction": None}]},
        "rules",
    )
    assert "lines.direction" in pipeline.blocking_gaps(extraction)
    assert decide_status(extraction, settings) == "pending_review"


def test_the_threshold_is_configurable(settings):
    extraction = Extraction("memo", 0.88, {"entry_date": "2026-09-02", "body": "x"}, "rules")
    assert decide_status(extraction, settings) == "posted"
    strict = settings.model_copy(update={"auto_post_threshold": 1.0})
    assert decide_status(extraction, strict) == "pending_review"
