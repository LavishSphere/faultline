"""ForecastOutput: the strict contract for model answers (issue #36). No network."""

from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from agents.local_ollama import LocalOllamaProvider
from agents.provider import (
    RATIONALE_MAX_CHARS,
    ForecastOutput,
    ModelOutputInvalid,
    ModelProvider,
    ModelUnavailable,
)
from models import ErrorCode

OFFERED = ("evid_a", "evid_b")


def _raw(**overrides) -> str:
    body = {"p_yes": 0.4, "decision": "wait", "rationale": "Orders slowed (evid_a).", "evidence_ids": ["evid_a"]}
    body.update(overrides)
    return json.dumps(body)


def test_valid_output_parses():
    out = ForecastOutput.parse_model_json(_raw(), OFFERED)
    assert out.p_yes == 0.4 and out.decision == "wait" and out.evidence_ids == ["evid_a"]


def test_integer_probability_bounds_accepted():
    assert ForecastOutput.parse_model_json(_raw(p_yes=1), OFFERED).p_yes == 1.0
    assert ForecastOutput.parse_model_json(_raw(p_yes=0), OFFERED).p_yes == 0.0


@pytest.mark.parametrize("bad", [1.01, -0.01, "0.5", True, None, 55])
def test_p_yes_rejected(bad):
    with pytest.raises(ValidationError):
        ForecastOutput.parse_model_json(_raw(p_yes=bad), OFFERED)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_p_yes_in_model_text_rejected(token):
    raw = '{"p_yes": ' + token + ', "decision": "wait", "rationale": "x (evid_a).", "evidence_ids": ["evid_a"]}'
    with pytest.raises(ValidationError):
        ForecastOutput.parse_model_json(raw, OFFERED)


def test_nan_p_yes_python_object_rejected():
    with pytest.raises(ValidationError):
        ForecastOutput.validate_obj(
            {"p_yes": math.nan, "decision": "act", "rationale": "x", "evidence_ids": []}, OFFERED
        )


def test_unknown_evidence_id_rejected():
    with pytest.raises(ValidationError, match="not offered"):
        ForecastOutput.parse_model_json(_raw(evidence_ids=["evid_a", "evid_zzz"]), OFFERED)


def test_validation_without_offered_ids_fails_closed():
    with pytest.raises(ValidationError, match="offered evidence ids are required"):
        ForecastOutput.model_validate_json(_raw())


@pytest.mark.parametrize("decision", ["ACT", "buy", "", None])
def test_decision_must_be_act_wait_hedge(decision):
    with pytest.raises(ValidationError):
        ForecastOutput.parse_model_json(_raw(decision=decision), OFFERED)


def test_rationale_length_limit():
    ForecastOutput.parse_model_json(_raw(rationale="x" * RATIONALE_MAX_CHARS), OFFERED)
    with pytest.raises(ValidationError):
        ForecastOutput.parse_model_json(_raw(rationale="x" * (RATIONALE_MAX_CHARS + 1)), OFFERED)
    for blank in ("", " ", "\n\t  ", "​", " ​‌‍﻿⁠ ", "‎"):
        with pytest.raises(ValidationError):
            ForecastOutput.parse_model_json(_raw(rationale=blank), OFFERED)
    assert ForecastOutput.parse_model_json(_raw(rationale="  ok (evid_a)  "), OFFERED).rationale == "  ok (evid_a)  "


def test_extra_keys_rejected():
    with pytest.raises(ValidationError):
        ForecastOutput.parse_model_json(_raw(confidence="high"), OFFERED)


def test_not_a_json_object_rejected():
    for raw in ("", "Sure! Here is my forecast.", "[0.4]", '{"p_yes": 0.4'):
        with pytest.raises(ValidationError):
            ForecastOutput.parse_model_json(raw, OFFERED)


def test_errors_are_typed_and_carry_no_forecast():
    assert ModelUnavailable.code is ErrorCode.MODEL_UNAVAILABLE
    err = ModelOutputInvalid("bad", raw_outputs=["{", "{"], problems=["p_yes: missing"])
    assert err.raw_outputs == ("{", "{") and not hasattr(err, "output")


def test_local_provider_satisfies_protocol():
    assert isinstance(LocalOllamaProvider("http://127.0.0.1:9", "llama3.1:8b"), ModelProvider)
