"""MODEL_CARDS: release / license / training-cutoff facts for the locally installed replay models (SPEC §5).

Network-off replay does not remove what a model learned in pretraining. ``contamination_flag`` compares an
event's resolution time with the model's knowledge cutoff and public release date:

* ``"likely"``   : the event resolved on or before the end of the cutoff month (the answer may be in the weights);
* ``"unknown"``  : it resolved between the cutoff and the end of the release day (post-training data may cover
  it), or the model has no card, or its cutoff / release date is not verified;
* ``"unlikely"`` : it resolved after the release day (never "none": the model cannot have been trained on it,
  but memorization claims are still not made).

Only facts checked against a cited source are filled in. Anything not verified is ``None`` (unknown) and the
``note`` says so. Installed weight digests are per-machine and are recorded at call time from Ollama
``/api/tags`` (ForecastResult.model_digest), not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType

from models import ContaminationFlag


@dataclass(frozen=True)
class ModelCard:
    tag: str
    """Ollama model tag, e.g. "llama3.1:8b"."""
    family: str
    publisher: str
    license: str
    release_date: date | None
    """Public release date; None = not verified."""
    knowledge_cutoff_month: tuple[int, int] | None
    """(year, month) of the pretraining-data cutoff; None = unknown / not verified."""
    source: str
    """Where the facts above were checked."""
    note: str = ""

    @property
    def cutoff_end(self) -> datetime | None:
        """End of the cutoff month (exclusive upper bound, UTC); None when the cutoff is unknown."""
        if self.knowledge_cutoff_month is None:
            return None
        year, month = self.knowledge_cutoff_month
        first_next = date(year + (month == 12), month % 12 + 1, 1)
        return datetime.combine(first_next, time(0, 0), tzinfo=UTC)

    @property
    def released_after(self) -> datetime | None:
        """Start of the day after the release date (UTC); None when the release date is not verified."""
        if self.release_date is None:
            return None
        return datetime.combine(self.release_date + timedelta(days=1), time(0, 0), tzinfo=UTC)


_LLAMA_SOURCE = (
    "Meta Llama 3.1 model card, https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/MODEL_CARD.md "
    '("Data Freshness: The pretraining data has a cutoff of December 2023"); release date from the license '
    "text bundled with the local Ollama model (`ollama show llama3.1:8b`)."
)

_GEMMA4_NOTE = (
    "Training-data cutoff and release date NOT verified from an official model card; treated as unknown. "
    "License (Apache 2.0) as reported by `ollama show` for the local model. Ollama renders this model's chat "
    "format in server code (renderer gemma4-small), not an inspectable template, so whether it adds any text "
    "(e.g. a date) to the prompt is NOT verified."
)

MODEL_CARDS: MappingProxyType[str, ModelCard] = MappingProxyType(
    {
        "llama3.1:8b": ModelCard(
            tag="llama3.1:8b",
            family="Llama 3.1",
            publisher="Meta",
            license="Llama 3.1 Community License",
            release_date=date(2024, 7, 23),
            knowledge_cutoff_month=(2023, 12),
            source=_LLAMA_SOURCE,
        ),
        "gemma4:e2b": ModelCard(
            tag="gemma4:e2b",
            family="Gemma 4",
            publisher="Google",
            license="Apache License 2.0",
            release_date=None,
            knowledge_cutoff_month=None,
            source="`ollama show gemma4:e2b` (license only)",
            note=_GEMMA4_NOTE,
        ),
        "gemma4:e4b": ModelCard(
            tag="gemma4:e4b",
            family="Gemma 4",
            publisher="Google",
            license="Apache License 2.0",
            release_date=None,
            knowledge_cutoff_month=None,
            source="`ollama show gemma4:e4b` (license only)",
            note=_GEMMA4_NOTE,
        ),
    }
)


def normalize_model_tag(model: str) -> str:
    """Accept "ollama/<tag>" (Prediction.agent_model) or a bare tag; untagged names mean ":latest"."""
    tag = model.strip()
    if tag.startswith("ollama/"):
        tag = tag[len("ollama/") :]
    return tag if ":" in tag else f"{tag}:latest"


def get_model_card(model: str) -> ModelCard | None:
    return MODEL_CARDS.get(normalize_model_tag(model))


def contamination_flag(model: str, event_resolved_at: datetime) -> ContaminationFlag:
    """Pretraining-contamination risk of replaying an event (the event's resolution TIME only) on ``model``.

    ``event_resolved_at`` must be timezone-aware. It is a date, not an outcome value, so this function never
    sees which way the event went.
    """
    if event_resolved_at.tzinfo is None or event_resolved_at.utcoffset() is None:
        raise ValueError("event_resolved_at must be timezone-aware")
    card = get_model_card(model)
    if card is None or card.cutoff_end is None:
        return "unknown"
    if event_resolved_at < card.cutoff_end:
        return "likely"
    released_after = card.released_after
    if released_after is None or event_resolved_at < released_after:
        # Between the pretraining cutoff and the public release: post-training data may cover it.
        return "unknown"
    return "unlikely"
