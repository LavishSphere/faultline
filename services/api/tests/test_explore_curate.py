"""scripts/tavily_curate.py: candidates-only curation notes (supports #20). Mocked Tavily + Wayback, no network."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "tavily_curate.py"
KEY = "tvly-curate-" + "c" * 40
LABEL = "CANDIDATES, NOT VERIFIED: human must confirm available_at from an archive capture"


@pytest.fixture(scope="module")
def curate():
    spec = importlib.util.spec_from_file_location("tavily_curate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["tavily_curate"] = module  # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("tavily_curate", None)


def _tavily(results):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"query": "q", "results": results, "response_time": 0.2})

    return httpx.MockTransport(handler), seen


RESULTS = [
    {"title": "Before | cutoff *story*", "url": "https://a.example/before", "content": "old news",
     "published_date": "Mon, 10 Feb 2025 12:00:00 GMT"},
    {"title": "After cutoff", "url": "https://b.example/after", "content": "the result was",
     "published_date": "Tue, 11 Mar 2025 17:00:00 GMT"},
    {"title": "Undated", "url": "https://c.example/undated", "content": "x"},
]

WAYBACK = {
    "https://a.example/before": {"archived_snapshots": {"closest": {
        "available": True, "url": "http://web.archive.org/web/20250215000000/https://a.example/before",
        "timestamp": "20250215000000", "status": "200"}}},
    "https://b.example/after": {"archived_snapshots": {"closest": {
        "available": True, "url": "http://web.archive.org/web/20250312000000/https://b.example/after",
        "timestamp": "20250312000000", "status": "200"}}},
    "https://c.example/undated": {"archived_snapshots": {}},
}


def _wayback(fail: bool = False):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if fail:
            return httpx.Response(503)
        return httpx.Response(200, json=WAYBACK[req.url.params["url"]])

    return httpx.MockTransport(handler), seen


def _argv(out_dir, *extra):
    return ["Will the Fed cut in March 2025?", "--before", "2025-03-01T00:00:00Z", "--case", "fed-march-2025",
            "--out-dir", str(out_dir), *extra]


def test_writes_labeled_candidates_with_wayback_verdicts(curate, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    t_transport, t_seen = _tavily(RESULTS)
    w_transport, w_seen = _wayback()
    code = curate.run(_argv(tmp_path), tavily_transport=t_transport, wayback_transport=w_transport)
    assert code == 0
    files = list(tmp_path.iterdir())
    assert [f.name for f in files] == ["fed-march-2025.md"]  # one file, nothing else written
    text = files[0].read_text(encoding="utf-8")
    assert f"**{LABEL}**" in text
    assert "Search powered by Tavily" in text
    # Each candidate: url, title (escaped), claimed date verdict, wayback verdict.
    assert "<https://a.example/before>" in text and r"Before \| cutoff \*story\*" in text
    assert "2025-02-10T12:00:00+00:00 (before as_of)" in text
    assert "capture BEFORE as_of" in text
    assert "AFTER as_of: not a valid replay source as dated" in text
    assert "closest capture is AFTER as_of" in text
    assert "NOT AVAILABLE (Tavily detected no date)" in text
    assert "no capture found" in text
    assert "https://web.archive.org/web/20250215000000/" in text
    assert text.count("- [ ] Human check") == 3
    # Tavily asked for results published before the cutoff; Wayback asked for captures near as_of.
    sent = json.loads(t_seen[0].content)
    assert sent["end_date"] == "2025-03-01" and sent["topic"] == "news"
    assert {r.url.params["timestamp"] for r in w_seen} == {"20250301000000"}
    assert KEY not in text and KEY not in capsys.readouterr().out


def test_wayback_failure_is_not_available_not_guessed(curate, tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    t_transport, _ = _tavily(RESULTS[:1])
    w_transport, _ = _wayback(fail=True)
    assert curate.run(_argv(tmp_path), tavily_transport=t_transport, wayback_transport=w_transport) == 0
    text = (tmp_path / "fed-march-2025.md").read_text(encoding="utf-8")
    assert "lookup failed (HTTPStatusError): NOT AVAILABLE" in text
    assert "BEFORE as_of" not in text


def test_missing_key_writes_nothing(curate, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    t_transport, t_seen = _tavily(RESULTS)
    assert curate.run(_argv(tmp_path), tavily_transport=t_transport) == curate.EXIT_UNAVAILABLE
    assert list(tmp_path.iterdir()) == [] and t_seen == []
    assert "TAVILY_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize("sub", ["demo_cases", "sealed_outcomes", "evidence", "x/demo_cases/y"])
def test_refuses_replay_data_directories(curate, tmp_path, monkeypatch, sub):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    t_transport, t_seen = _tavily(RESULTS)
    target = tmp_path / sub
    assert curate.run(_argv(target), tavily_transport=t_transport) == curate.EXIT_USAGE
    assert not target.exists() and t_seen == []


def test_refuses_services_api_data_and_configured_data_dir(curate, tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    t_transport, t_seen = _tavily(RESULTS)
    api_data = REPO_ROOT / "services" / "api" / "data" / "curation-test-should-not-exist"
    assert curate.run(_argv(api_data), tavily_transport=t_transport) == curate.EXIT_USAGE
    assert not api_data.exists()
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))
    assert curate.run(_argv(tmp_path / "data" / "notes"), tavily_transport=t_transport) == curate.EXIT_USAGE
    assert t_seen == []


def test_does_not_overwrite_without_force(curate, tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    (tmp_path / "fed-march-2025.md").write_text("human notes", encoding="utf-8")
    t_transport, t_seen = _tavily(RESULTS)
    assert curate.run(_argv(tmp_path, "--no-wayback"), tavily_transport=t_transport) == curate.EXIT_EXISTS
    assert (tmp_path / "fed-march-2025.md").read_text(encoding="utf-8") == "human notes" and t_seen == []
    assert curate.run(_argv(tmp_path, "--no-wayback", "--force"), tavily_transport=t_transport) == 0
    assert "not checked (--no-wayback)" in (tmp_path / "fed-march-2025.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(("raw", "iso"), [("2025-03-01", "2025-03-01T00:00:00+00:00"),
                                          ("2025-03-01T05:00:00+05:00", "2025-03-01T00:00:00+00:00")])
def test_as_of_parsing(curate, raw, iso):
    assert curate.parse_as_of(raw)[0].isoformat() == iso


@pytest.mark.parametrize("raw", ["2025-03-01T00:00:00", "March 1", "1740787200"])
def test_as_of_rejects_naive_or_unparseable(curate, raw):
    with pytest.raises(curate.CurationError):
        curate.parse_as_of(raw)


def test_default_output_dir_is_docs_curation(curate):
    assert curate.DEFAULT_OUT_DIR == REPO_ROOT / "docs" / "curation"
    assert (REPO_ROOT / "docs" / "curation" / ".gitkeep").is_file()


@pytest.mark.parametrize("variant", ["DATA", "Data", "dAtA"])
def test_refuses_case_variant_of_configured_data_dir_on_every_os(curate, tmp_path, monkeypatch, variant):
    """Refused on case-insensitive (APFS) and case-sensitive (Linux CI) file systems alike: nothing is created."""
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(data))
    t_transport, t_seen = _tavily(RESULTS)
    target = tmp_path / variant / "notes"
    code = curate.run(_argv(target, "--no-wayback"), tavily_transport=t_transport)
    assert code == curate.EXIT_USAGE and t_seen == []
    assert list(data.iterdir()) == []
    assert not target.exists()


@pytest.mark.parametrize("variant", ["DATA", "Data"])
def test_refuses_case_variant_of_services_api_data_on_every_os(curate, monkeypatch, variant):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    t_transport, t_seen = _tavily(RESULTS)
    target = REPO_ROOT / "services" / "api" / variant / "curation-case-variant-test"
    assert curate.run(_argv(target, "--no-wayback"), tavily_transport=t_transport) == curate.EXIT_USAGE
    assert not target.exists() and t_seen == []
    assert not (REPO_ROOT / "services" / "api" / "data" / "curation-case-variant-test").exists()


def test_case_variant_guard_does_not_depend_on_the_file_system(curate, tmp_path):
    """The case-folded compare alone refuses, even when the variant is a real, separate directory."""
    data = tmp_path / "data"
    data.mkdir()
    other = tmp_path / "DATA"
    if not other.exists():  # case-sensitive file system: make it a genuinely different directory
        other.mkdir()
    assert curate._within(other / "notes", data)


def test_refuses_symlinked_directory_into_data(curate, tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(data))
    (tmp_path / "innocent").symlink_to(data, target_is_directory=True)
    t_transport, t_seen = _tavily(RESULTS)
    assert curate.run(_argv(tmp_path / "innocent", "--no-wayback"), tavily_transport=t_transport) == curate.EXIT_USAGE
    assert list(data.iterdir()) == [] and t_seen == []


@pytest.mark.parametrize("force", [False, True])
def test_refuses_symlinked_output_file(curate, tmp_path, monkeypatch, force):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    out = tmp_path / "out"
    out.mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("{}", encoding="utf-8")
    (out / "fed-march-2025.md").symlink_to(victim)
    t_transport, t_seen = _tavily(RESULTS)
    extra = ["--no-wayback", "--force"] if force else ["--no-wayback"]
    assert curate.run(_argv(out, *extra), tavily_transport=t_transport) == curate.EXIT_USAGE
    assert victim.read_text(encoding="utf-8") == "{}" and t_seen == []


def test_symlink_pointing_into_data_is_refused_even_with_force(curate, tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    data = tmp_path / "data" / "demo_cases"
    data.mkdir(parents=True)
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))
    out = tmp_path / "out"
    out.mkdir()
    (out / "fed-march-2025.md").symlink_to(data / "case.json")
    t_transport, _ = _tavily(RESULTS)
    assert curate.run(_argv(out, "--no-wayback", "--force"), tavily_transport=t_transport) == curate.EXIT_USAGE
    assert list(data.iterdir()) == []


def test_file_created_during_search_is_not_overwritten(curate, tmp_path, monkeypatch):
    """Exclusive create: a file that appears between the pre-check and the write is kept, not clobbered."""
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    target = tmp_path / "fed-march-2025.md"

    def handler(req: httpx.Request) -> httpx.Response:
        target.write_text("written by a human meanwhile", encoding="utf-8")
        return httpx.Response(200, json={"query": "q", "results": RESULTS})

    code = curate.run(_argv(tmp_path, "--no-wayback"), tavily_transport=httpx.MockTransport(handler))
    assert code == curate.EXIT_EXISTS
    assert target.read_text(encoding="utf-8") == "written by a human meanwhile"
