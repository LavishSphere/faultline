"""FAULTLINE_PREDICTIONS_DB (issue #130): one setting decides the prediction store everywhere it is opened.

Written before the setting. All fixtures are SYNTHETIC (tests/test_routes_replay.py); the model is a mocked Ollama
transport. What must hold:
- a run, reveal, integrity check and benchmark compute through the API, with the setting pointed at a tmp file,
  write nothing to the official default store (its existence and mtime are checked before and after);
- the evaluator's "reveal only into the configured store" check compares against the SAME setting;
- computed scorecards live next to the configured store;
- no route, core module, agent or script opens the official default path directly;
- scripts/record_runs.py (official run) uses the setting, which defaults to the official store;
- scripts/demo_api.py exports the scratch store as the setting and still refuses to point it at the official store;
- scripts/preflight.py prints the store from the setting (WARN on the official default), never prints a sealed
  value, and FAILs when a sealed file is missing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import pytest
from test_routes_replay import CANARY, EVENT, SEALED_RESOLVED_AT, gate_case_file, make_world, run, sealed_file

import config
from config import DEFAULT_PREDICTIONS_DB, get_settings
from core import store as store_module
from core.evaluator import OutcomeVault
from core.store import PredictionStore
from routes import benchmark

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]
SCRIPTS = REPO_ROOT / "scripts"
SEALED_SOURCE_URL = "https://example.org/settlement"  # exists only in the sealed file


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"_t130_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses in the script look their module up here
    spec.loader.exec_module(module)
    return module


def stat_or_none(path: Path) -> tuple[int, int] | None:
    return (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else None


def official_state() -> dict:
    """Existence + mtime of the official store, its SQLite side files and the official computed-scorecards dir."""
    paths = [DEFAULT_PREDICTIONS_DB, DEFAULT_PREDICTIONS_DB.parent / "scorecards"]
    paths += [DEFAULT_PREDICTIONS_DB.with_name(DEFAULT_PREDICTIONS_DB.name + s) for s in ("-journal", "-wal", "-shm")]
    return {str(p): stat_or_none(p) for p in paths}


def counts(db: Path) -> dict[str, int]:
    with sqlite3.connect(db) as conn:
        return dict(conn.execute("SELECT kind, count(*) FROM audit_log GROUP BY kind").fetchall())


# ---------------------------------------------------------------- the setting itself


def test_default_is_the_official_store(monkeypatch):
    monkeypatch.delenv("FAULTLINE_PREDICTIONS_DB", raising=False)
    s = get_settings()
    assert s.predictions_db == DEFAULT_PREDICTIONS_DB == store_module.DEFAULT_DB_PATH
    assert DEFAULT_PREDICTIONS_DB == API_DIR / "var" / "predictions.sqlite3"
    assert s.predictions_db_is_official and store_module.configured_db_path() == DEFAULT_PREDICTIONS_DB
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", "   ")
    assert get_settings().predictions_db == DEFAULT_PREDICTIONS_DB


def test_setting_is_read_per_call_and_made_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(tmp_path / "a.sqlite3"))
    assert store_module.configured_db_path() == tmp_path / "a.sqlite3"
    assert PredictionStore().path == tmp_path / "a.sqlite3"  # the default argument follows the setting
    assert not get_settings().predictions_db_is_official
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", "rel/b.sqlite3")
    assert get_settings().predictions_db == tmp_path / "rel" / "b.sqlite3"
    assert benchmark.computed_dir() == tmp_path / "rel" / "scorecards"


def test_the_official_path_spelled_differently_still_counts_as_official(monkeypatch):
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(API_DIR / "var" / ".." / "var" / "predictions.sqlite3"))
    assert get_settings().predictions_db_is_official


# ---------------------------------------------------------------- API end to end on a tmp store


def test_api_run_reveal_integrity_compute_on_tmp_store_never_touch_the_official_store(tmp_path, monkeypatch):
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)
    before = official_state()
    world = make_world(tmp_path, monkeypatch)  # FAULTLINE_PREDICTIONS_DB = tmp/var/predictions.sqlite3
    assert get_settings().predictions_db == world.db
    assert not (world.db.exists())
    client = world.client()

    resp = run(client)
    assert resp.status_code == 200, resp.text
    pid = resp.json()["prediction"]["prediction_id"]
    assert client.get("/api/integrity", params={"prediction_id": pid}).status_code == 200
    reveal = client.post(f"/api/replay/{pid}/reveal")
    assert reveal.status_code == 200, reveal.text
    compute = client.post("/api/benchmark/compute", json={"agent_variant": "agent_only"})
    assert compute.status_code == 200, compute.text

    # Everything landed in the configured tmp store and the scorecards dir next to it ...
    assert counts(world.db).get("persist", 0) == 1 and counts(world.db).get("reveal", 0) >= 1
    assert sorted((tmp_path / "var" / "scorecards").glob("*.json"))
    # ... and nothing in the official default store: same existence, same mtime.
    assert official_state() == before


# ---------------------------------------------------------------- the evaluator compares against the SAME setting


def test_vault_accepts_only_the_store_named_by_the_setting(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "sealed_outcomes").mkdir(parents=True)
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(data))
    a, b = tmp_path / "a" / "p.sqlite3", tmp_path / "b" / "p.sqlite3"
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(a))
    OutcomeVault(PredictionStore(a))  # the configured store: accepted
    with pytest.raises(ValueError, match="configured prediction store"):
        OutcomeVault(PredictionStore(b))
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(b))  # read per call: now b is the one
    OutcomeVault(PredictionStore(b))
    with pytest.raises(ValueError, match="configured prediction store"):
        OutcomeVault(PredictionStore(a))


# ---------------------------------------------------------------- tripwire: nothing opens the official path directly

OPENERS = [
    *sorted((API_DIR / "routes").glob("*.py")),
    *sorted((API_DIR / "agents").glob("*.py")),
    *sorted(p for p in (API_DIR / "core").glob("*.py") if p.name != "store.py"),
    API_DIR / "main.py",
    SCRIPTS / "record_runs.py",
    SCRIPTS / "demo_api.py",
    SCRIPTS / "preflight.py",
]


@pytest.mark.parametrize("path", OPENERS, ids=lambda p: p.name)
def test_no_store_opener_uses_the_official_default_path_directly(path):
    # The official default is compared against as config.DEFAULT_PREDICTIONS_DB; stores are opened at the setting.
    assert "DEFAULT_DB_PATH" not in path.read_text(encoding="utf-8"), path


# ---------------------------------------------------------------- scripts/record_runs.py


class _StoreProbe:
    def __init__(self, path, **_kw):
        self.path = Path(path)


def _record_runs_store(monkeypatch, tmp_path, argv=()):
    rr = load_script("record_runs")
    opened: list[Path] = []

    def probe(path, **kw):
        opened.append(Path(path))
        return _StoreProbe(path)

    def refuse(*_a, store, **_kw):
        raise rr.Refused(f"test stop before forecasting (store {store.path})")

    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(rr, "PredictionStore", probe)
    monkeypatch.setattr(rr, "run_forecasts", refuse)
    assert rr.main(["--out", str(tmp_path / "out"), *argv]) == 2
    return opened


def test_record_runs_official_run_uses_the_official_store_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FAULTLINE_PREDICTIONS_DB", raising=False)
    assert _record_runs_store(monkeypatch, tmp_path) == [DEFAULT_PREDICTIONS_DB]  # probe: nothing is created
    assert f"prediction store: OFFICIAL {DEFAULT_PREDICTIONS_DB}" in capsys.readouterr().out


def test_record_runs_official_run_follows_an_explicit_setting_and_says_so(tmp_path, monkeypatch, capsys):
    target = tmp_path / "elsewhere.sqlite3"
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(target))
    assert _record_runs_store(monkeypatch, tmp_path) == [target]
    assert "NOT the official store" in capsys.readouterr().out


def test_record_runs_dry_run_never_uses_the_configured_store(tmp_path, monkeypatch):
    monkeypatch.delenv("FAULTLINE_PREDICTIONS_DB", raising=False)
    [opened] = _record_runs_store(monkeypatch, tmp_path, ["--dry-run"])
    assert opened == tmp_path / "out" / "dry-run.sqlite3"


# ---------------------------------------------------------------- scripts/demo_api.py


def test_demo_store_resolution(tmp_path):
    demo = load_script("demo_api")
    assert demo.resolve_store({}) == (DEFAULT_PREDICTIONS_DB, None)
    assert demo.resolve_store({"FAULTLINE_PREDICTIONS_DB": str(tmp_path / "x.sqlite3")}) == (
        tmp_path / "x.sqlite3",
        None,
    )
    scratch = tmp_path / "scratch.sqlite3"
    assert demo.resolve_store({"FAULTLINE_DEMO_STORE": str(scratch)}) == (scratch, None)
    path, why = demo.resolve_store({"FAULTLINE_DEMO_STORE": str(DEFAULT_PREDICTIONS_DB)})
    assert path is None and "official store" in why
    spelled = str(API_DIR / "var" / ".." / "var" / "predictions.sqlite3")
    assert demo.resolve_store({"FAULTLINE_DEMO_STORE": spelled})[0] is None


def _demo_main(monkeypatch):
    import uvicorn

    demo = load_script("demo_api")
    served = []
    monkeypatch.chdir(API_DIR)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: served.append(get_settings().predictions_db))
    # main() writes os.environ directly; register both keys with monkeypatch so they are restored after the test.
    for key in ("FAULTLINE_PREDICTIONS_DB", "FAULTLINE_DEMO_STORE"):
        current = os.environ.get(key)
        monkeypatch.setenv(key, current if current is not None else "")
        if current is None:
            monkeypatch.delenv(key)
    return demo.main(), served


def test_demo_launcher_exports_the_scratch_store_as_the_setting(tmp_path, monkeypatch, capsys):
    scratch = tmp_path / "scratch" / "predictions.sqlite3"
    monkeypatch.setenv("FAULTLINE_DEMO_STORE", str(scratch))
    code, served = _demo_main(monkeypatch)
    assert code == 0 and served == [scratch]
    assert store_module.configured_db_path() == scratch and benchmark.computed_dir() == scratch.parent / "scorecards"
    assert f"SCRATCH {scratch}" in capsys.readouterr().out


def test_demo_launcher_refuses_the_official_store_as_scratch(monkeypatch, capsys):
    monkeypatch.setenv("FAULTLINE_DEMO_STORE", str(DEFAULT_PREDICTIONS_DB))
    code, served = _demo_main(monkeypatch)
    assert code == 2 and served == []
    assert "refusing" in capsys.readouterr().err


def test_demo_launcher_warns_on_the_official_store(monkeypatch, capsys):
    monkeypatch.delenv("FAULTLINE_DEMO_STORE", raising=False)
    monkeypatch.delenv("FAULTLINE_PREDICTIONS_DB", raising=False)
    code, served = _demo_main(monkeypatch)
    assert code == 0 and served == [DEFAULT_PREDICTIONS_DB]
    assert "WARNING prediction store: OFFICIAL" in capsys.readouterr().out


# ---------------------------------------------------------------- scripts/preflight.py


@pytest.fixture
def preflight(tmp_path, monkeypatch):
    """preflight on a tmp data dir with two SYNTHETIC cases and their sealed files; no network, no subprocess."""
    pf = load_script("preflight")
    monkeypatch.setattr(pf, "results", [])
    monkeypatch.setattr(pf, "check_node", lambda: pf.report("PASS", "node", "skipped in test"))
    monkeypatch.setattr(pf, "check_web_build", lambda: pf.report("PASS", "web build", "skipped in test"))
    monkeypatch.setattr(pf, "check_ollama", lambda *_a: pf.report("WARN", "ollama", "skipped in test"))
    monkeypatch.delenv("FAULTLINE_DEMO_STORE", raising=False)
    data = tmp_path / "data"
    (data / "demo_cases").mkdir(parents=True)
    (data / "sealed_outcomes").mkdir()
    for event_id in (EVENT, "SYNTH-SECOND-CASE"):
        case = gate_case_file(event_id)
        (data / "demo_cases" / f"{event_id}.json").write_text(json.dumps(case), encoding="utf-8")
        sealed = sealed_file(event_id)
        (data / "sealed_outcomes" / f"{event_id}.json").write_text(json.dumps(sealed), encoding="utf-8")
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(data))
    return pf, data


SEALED_VALUES = (CANARY, SEALED_RESOLVED_AT, "2025-01-22T19:07", SEALED_SOURCE_URL, '"outcome"')


def test_preflight_prints_no_sealed_value_and_passes_with_every_seal(preflight, tmp_path, monkeypatch, capsys):
    pf, _data = preflight
    scratch = tmp_path / "scratch.sqlite3"
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(scratch))
    assert pf.main([]) == 0
    out = capsys.readouterr().out
    for value in SEALED_VALUES:
        assert value not in out
    assert re.search(rf"\[PASS\] sealed {EVENT}: exists, sha256 [0-9a-f]{{16}}\.\.\.", out)
    assert f"[PASS] prediction store: scratch store {scratch} (not created yet)" in out
    assert not scratch.exists()  # preflight never opens or creates the store


def test_preflight_fails_when_a_sealed_file_is_missing(preflight, capsys):
    pf, data = preflight
    (data / "sealed_outcomes" / "SYNTH-SECOND-CASE.json").unlink()
    assert pf.main([]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] sealed SYNTH-SECOND-CASE: no sealed outcome file" in out
    assert f"[PASS] sealed {EVENT}" in out
    assert "preflight FAIL" in out
    for value in SEALED_VALUES:
        assert value not in out


def test_preflight_warns_when_the_store_is_the_official_default(preflight, monkeypatch, capsys):
    pf, _data = preflight
    monkeypatch.delenv("FAULTLINE_PREDICTIONS_DB", raising=False)
    before = official_state()
    pf.check_store()
    out = capsys.readouterr().out
    assert f"[WARN] prediction store: {DEFAULT_PREDICTIONS_DB}" in out and "OFFICIAL default store" in out
    assert official_state() == before


def test_preflight_fails_when_the_demo_store_names_the_official_store(preflight, monkeypatch, capsys):
    pf, _data = preflight
    monkeypatch.setenv("FAULTLINE_DEMO_STORE", str(DEFAULT_PREDICTIONS_DB))
    pf.check_store()
    assert "[FAIL] prediction store: FAULTLINE_DEMO_STORE is the official store" in capsys.readouterr().out


def test_config_module_has_the_setting_documented_in_env_example():
    assert "FAULTLINE_PREDICTIONS_DB" in (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert hasattr(config.Settings, "predictions_db_is_official")
    assert "predictions_db" in config.Settings.__dataclass_fields__
