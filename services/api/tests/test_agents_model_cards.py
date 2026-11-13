"""MODEL_CARDS and contamination_flag (issue #36, SPEC §5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agents.model_cards import MODEL_CARDS, contamination_flag, get_model_card

CUTOFF_END = datetime(2024, 1, 1, tzinfo=UTC)  # end of Dec 2023 for llama3.1:8b


def test_installed_models_have_cards():
    assert {"llama3.1:8b", "gemma4:e2b", "gemma4:e4b"} <= set(MODEL_CARDS)
    for card in MODEL_CARDS.values():
        assert card.source


def test_llama_cutoff_is_december_2023():
    card = MODEL_CARDS["llama3.1:8b"]
    assert card.knowledge_cutoff_month == (2023, 12)
    assert card.cutoff_end == CUTOFF_END


def test_gemma4_cutoff_unknown_not_guessed():
    for tag in ("gemma4:e2b", "gemma4:e4b"):
        card = MODEL_CARDS[tag]
        assert card.knowledge_cutoff_month is None and card.cutoff_end is None
        assert "NOT verified" in card.note


def test_llama_event_before_cutoff_is_likely():
    assert contamination_flag("llama3.1:8b", datetime(2023, 6, 1, tzinfo=UTC)) == "likely"
    assert contamination_flag("llama3.1:8b", CUTOFF_END - timedelta(seconds=1)) == "likely"


def test_llama_event_between_cutoff_and_release_is_unknown():
    assert contamination_flag("llama3.1:8b", CUTOFF_END) == "unknown"
    assert contamination_flag("llama3.1:8b", datetime(2024, 5, 1, tzinfo=UTC)) == "unknown"
    # Release day itself (2024-07-23) is still not "unlikely".
    assert contamination_flag("llama3.1:8b", datetime(2024, 7, 23, 23, 59, tzinfo=UTC)) == "unknown"


def test_llama_event_after_release_is_unlikely_never_none():
    assert contamination_flag("llama3.1:8b", datetime(2024, 7, 24, tzinfo=UTC)) == "unlikely"
    assert contamination_flag("ollama/llama3.1:8b", datetime(2025, 3, 1, tzinfo=UTC)) == "unlikely"


@pytest.mark.parametrize("model", ["gemma4:e2b", "gemma4:e4b", "mystery-model:1b", "llama3.1"])
def test_unknown_cutoff_or_unknown_model_is_unknown(model):
    assert contamination_flag(model, datetime(2020, 1, 1, tzinfo=UTC)) == "unknown"


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        contamination_flag("llama3.1:8b", datetime(2023, 6, 1))


def test_lookup_normalizes_prefix_and_latest():
    assert get_model_card("ollama/llama3.1:8b") is MODEL_CARDS["llama3.1:8b"]
    assert get_model_card("llama3.1") is None  # resolves to llama3.1:latest, which has no card
