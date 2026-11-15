"""Hard separation between Live Explore (Tavily web search) and the Blind Replay (SPEC §3.3, §5; issue #60).

SPEC §5: "No retrieval tool, Tavily, web search ... is available to the replay model." That is enforced here
by code structure, not by a UI flag:

(a) References. Only the Live Explore surface may reference Tavily or explore code: ``routes/explore.py``, the
    future ``agents/explore_*.py`` (#61) and ``scripts/tavily_curate.py``. Every other module under services/api
    and the repo ``scripts/`` is swept by AST: imports, every string constant (each piece of a concatenation,
    %-format or f-string), attribute, name, keyword and def name. So ``import_module("agents." + "tavily")``,
    ``sys.modules.get``, ``getattr(agents, "tavily")``, ``spec_from_file_location``, ``app.state.faultline_explore``
    and a raw ``httpx.post("https://api.tavily.com/...")`` are all flagged (see EVASIONS). The replay modules are
    also imported in a fresh interpreter to prove that ``agents.tavily`` is not pulled in transitively.
(b) Data. A Tavily result cannot become an ``EvidenceItem`` (it has no ``available_at``, no content hash, no
    event id), and even a forged conversion that dates it by when it was retrieved is refused by the gate.
(c) Runtime. With a key configured, every TavilyClient on a counting mock transport, and every httpx request to
    a Tavily host intercepted, driving every non-explore route and rendering every prompt of a (never empty)
    synthetic store plus the demo cases makes zero Tavily calls. Positive controls prove each tripwire fires.
    The replay and agent test modules are also re-run in a subprocess under the same tripwire.

The checks do not import allow-lists from production code, so weakening the production code cannot weaken
the test. Limit: a static sweep cannot see a name assembled from fragments that are not recognizable on their
own (e.g. "tav" + "ily"); the host-level runtime tripwire covers that case for network calls.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_temporal_gate import AS_OF, make_case, make_evidence, standard_record

from agents import tavily
from core import temporal_gate as gate
from core.temporal_gate import CaseRecord
from main import create_app
from models import EvidenceItem, ReplayCase
from routes import health

API_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = API_DIR.parent.parent
FAKE_KEY = "tvly-test-" + "k" * 32  # never a real key; asserted absent from outputs elsewhere

# Modules allowed to reference Live Explore code at all (paths relative to services/api).
ALLOWED_IMPORTERS = {
    "agents/tavily.py",
    "routes/explore.py",
    "routes/explore_chat.py",  # #187: the LIVE EXPLORE chat routes (agents/explore_chat.py is under the prefix)
    "routes/explore_starters.py",  # #223: chat starter questions from current news (Anthropic web search)
}
ALLOWED_IMPORTER_PREFIXES = ("agents/explore_",)  # #61: agents/explore_analyst.py
# Relative to the repo scripts/ directory. #187: `make chat-models` (check_chat_models.py) prints the chat catalogue.
# #195: chat_qa.py runs the chat QA bank against a running API over HTTP (it imports no FAULTLINE module).
ALLOWED_SCRIPTS = {"tavily_curate.py", "check_chat_models.py", "chat_qa.py"}
# Exact references other files may contain. main.py mounts the router (and nothing else). The CI secret
# scanner names the Tavily key pattern so it can block committed keys.
ALLOWED_REFS = {
    # main.py mounts the router and, in its edge block, names the explore paths so the public-mode admin gate and
    # route table can refuse them (#13). Path strings only: no import of Tavily or explore internals.
    "main.py": {"import:routes.explore", "name:explore", "const:/api/explore", "const:/api/explore/analyze",
                "const:/api/explore/search",
                # #187: mounts the chat router and classifies its exact paths (edge gate, body cap, route table).
                "import:routes.explore_chat", "const:/api/explore/chat", "const:/api/explore/chat/models",
                "const:/api/explore/chat/status", "const:/api/explore/chat/pause",
                # #222: the streamed chat turn, classified like /api/explore/chat.
                "const:/api/explore/chat/stream",
                # #223: mounts the starters router and classifies its path.
                "import:routes.explore_starters", "const:/api/explore/chat/starters"},
    "ci/content_scan.py": {"const:Tavily API key"},
    # #214: /api/health reports which backend the chat's web_search uses (a name, never a key). It imports only the
    # env resolver; health is not a replay module (the replay import test below still runs in a clean interpreter).
    "routes/health.py": {"import:agents.explore_web_search", "import:agents.explore_web_search.provider_from_env"},
}

# Replay-side modules named in the issue and SPEC §8. Existing ones are also imported in a clean interpreter.
REPLAY_MODULES = (
    "core.temporal_gate",
    "core.store",
    "core.evaluator",
    "core.provenance",
    "core.forecasting",
    "agents.provider",
    "agents.local_ollama",
    "agents.model_cards",
    "agents.skeptic",
    "routes.cases",
    "routes.replay",
    "routes.benchmark",
    "routes.recorded",
    "routes.evidence",
)
REQUIRED_ON_MAIN = {"core.temporal_gate", "core.store", "core.evaluator", "core.provenance", "routes.cases",
                    "agents.provider", "agents.local_ollama"}

# Anything that names Live Explore code, state or endpoints. Matched against every import, string constant
# (including each piece of a concatenation, %-format or f-string), attribute, name, keyword, alias and def name.
# `explore_analy` covers agents/explore_analyst.py and the analyze route (#61); `agents.explore_` any future one.
_LIVE_EXPLORE = re.compile(
    r"tavily|faultline_explore|routes\.explore|explore_search|explore_analy|agents\.explore_|/api/explore",
    re.IGNORECASE,
)
_EXACT_EXPLORE = {"explore"}  # e.g. getattr(routes, "explore"), import_module("routes." + "explore")
# Key-presence plumbing (config.py boolean, /api/health notice, OptionalKeys field, the public /api/health boolean
# `tavily_configured` in routes/health.py, #172) may appear anywhere.
_KEY_PRESENCE = re.compile(r"TAVILY_API_KEY|tavily_api_key(?:_set)?|tavily_configured")


def _module_path(dotted: str) -> Path:
    return API_DIR / (dotted.replace(".", "/") + ".py")


def _api_sources() -> list[tuple[str, Path]]:
    skip = {".venv", "var", "tests", "node_modules", "__pycache__", "data"}
    out = []
    for path in sorted(API_DIR.rglob("*.py")):
        rel = path.relative_to(API_DIR)
        if any(part in skip or part.startswith(".") for part in rel.parts[:-1]):
            continue
        out.append((rel.as_posix(), path))
    return out


def _script_sources() -> list[tuple[str, Path]]:
    root = REPO_ROOT / "scripts"
    return [(p.relative_to(root).as_posix(), p) for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]


def live_explore_refs(source: str) -> set[str]:
    """Every reference to Live Explore code in `source`, as ``kind:text`` (comments are not code)."""
    refs: set[str] = set()

    def check(kind: str, text: str | None) -> None:
        if not text:
            return
        if _LIVE_EXPLORE.search(_KEY_PRESENCE.sub("", text)) or text in _EXACT_EXPLORE:
            refs.add(f"{kind}:{text}")

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check("import", alias.name)
                check("alias", alias.asname)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            check("import", base)
            for alias in node.names:
                full = f"{base}.{alias.name}" if base else alias.name
                if _LIVE_EXPLORE.search(full) or alias.name in _EXACT_EXPLORE:
                    refs.add(f"import:{full}")
                check("alias", alias.asname)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            check("const", node.value)
        elif isinstance(node, ast.Attribute):
            check("attr", node.attr)
        elif isinstance(node, ast.Name):
            check("name", node.id)
        elif isinstance(node, ast.keyword):
            check("kw", node.arg)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            check("def", node.name)
        elif isinstance(node, ast.arg):
            check("arg", node.arg)
    return refs


def _offenders() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for rel, path in _api_sources():
        if rel in ALLOWED_IMPORTERS or rel.startswith(ALLOWED_IMPORTER_PREFIXES):
            continue
        extra = live_explore_refs(path.read_text(encoding="utf-8")) - ALLOWED_REFS.get(rel, set())
        if extra:
            found[f"services/api/{rel}"] = sorted(extra)
    for rel, path in _script_sources():
        if rel in ALLOWED_SCRIPTS:
            continue
        extra = live_explore_refs(path.read_text(encoding="utf-8")) - ALLOWED_REFS.get(rel, set())
        if extra:
            found[f"scripts/{rel}"] = sorted(extra)
    return found


# --------------------------------------------------------------------------- (a) imports and references


def test_only_live_explore_modules_reference_tavily_or_explore_code():
    assert _offenders() == {}, "modules outside Live Explore reference Tavily/explore code"


# Each is a way a replay module could reach Live Explore; the sweep must flag every one (audit on PR #73).
EVASIONS = [
    "from agents import tavily",
    "import agents.tavily as t",
    "import importlib\nimportlib.import_module('agents.' + 'tavily')",
    "import importlib\nimportlib.import_module('agents.%s' % 'tavily')",
    "import importlib\nimportlib.import_module('agents.{}'.format('tavily'))",
    "import importlib\nx = 'tavily'\nimportlib.import_module(f'agents.{x}')",
    "import sys\nm = sys.modules.get('agents.tavily')",
    "import agents\nm = getattr(agents, 'tavily')",
    "import importlib.util\nspec = importlib.util.spec_from_file_location('x', 'agents/tavily.py')",
    "def f(request):\n    return request.app.state.faultline_explore",
    "import httpx\nhttpx.post('https://api.tavily.com/search', json={})",
    "from routes import explore",
    "import routes.explore",
    "import importlib\nimportlib.import_module('routes.' + 'explore')",
    "import routes\nr = getattr(routes, 'explore')",
    "from routes.explore import explore_search",
    "def run(tavily_client):\n    return tavily_client",
    "from agents import explore_analyst",
    "import agents.explore_analyst",
    "from agents.explore_analyst import render_prompt",
    "import importlib\nimportlib.import_module('agents.' + 'explore_analyst')",
    "from routes.explore import explore_analyze",
]


@pytest.mark.parametrize("source", EVASIONS)
def test_sweep_flags_every_known_evasion(source):
    assert live_explore_refs(source), source


def test_sweep_flags_a_raw_call_to_a_live_explore_endpoint():
    """#61: this sweep also names the endpoints. Kept out of EVASIONS, which the INTEGRITY panel's own scan
    (routes/integrity.py, #93) must match one for one; extending that scan is a follow-up."""
    assert live_explore_refs("import httpx\nhttpx.post('http://localhost:8000/api/explore/analyze', json={})")


@pytest.mark.parametrize(
    "source",
    [
        "settings.tavily_api_key_set",
        "notice = 'TAVILY_API_KEY not set: Live Explore web search is disabled.'",
        "OptionalKeys(anthropic_api_key=a, tavily_api_key=b)",
        "label = 'LIVE EXPLORE: all curated lenses'",
        "# from agents import tavily  (a comment is not code)\nx = 1",
    ],
)
def test_sweep_allows_key_presence_plumbing_and_prose(source):
    assert live_explore_refs(source) == set()


def test_main_mounts_explore_router_but_touches_no_tavily_client():
    refs = live_explore_refs((API_DIR / "main.py").read_text(encoding="utf-8"))
    assert refs <= ALLOWED_REFS["main.py"], refs
    assert "import:routes.explore" in refs


def test_named_replay_modules_reference_no_live_explore_code():
    present = {m for m in REPLAY_MODULES if _module_path(m).is_file()}
    assert REQUIRED_ON_MAIN <= present
    offenders = {m: sorted(r) for m in sorted(present)
                 if (r := live_explore_refs(_module_path(m).read_text(encoding="utf-8")))}
    assert offenders == {}


def test_replay_modules_do_not_load_tavily_transitively():
    """Import every replay module that exists in a fresh interpreter; agents.tavily must not be loaded."""
    present = [m for m in REPLAY_MODULES if _module_path(m).is_file()]
    assert REQUIRED_ON_MAIN <= set(present)
    code = textwrap.dedent(
        f"""
        import importlib, json, sys
        for name in {present!r}:
            importlib.import_module(name)
        print(json.dumps(sorted(m for m in sys.modules
                                if "tavily" in m or m.startswith(("routes.explore", "agents.explore_")))))
        """
    )
    env = {**os.environ, "PYTHONPATH": str(API_DIR)}
    env.pop("TAVILY_API_KEY", None)
    out = subprocess.run([sys.executable, "-c", code], cwd=API_DIR, env=env, capture_output=True, text=True,
                         timeout=60, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []


def test_tavily_client_cannot_build_replay_evidence():
    """The client module imports nothing from the replay side (no EvidenceItem, gate, store or vault)."""
    tree = ast.parse(Path(tavily.__file__).read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    forbidden = [n for n in names if n == "models" or n.startswith(("core", "routes", "markets", "models."))]
    assert forbidden == []


def test_explore_analyst_reads_no_replay_data():
    """#61: the analyst's evidence is the Tavily results only. It imports no gate, store, vault, case loader or
    market code, and names no replay data directory (its one data file is the ILLUSTRATIVE shock guidance)."""
    path = API_DIR / "agents" / "explore_analyst.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    replay_side = ("core.temporal_gate", "core.store", "core.evaluator", "core.provenance", "markets", "routes")
    assert [n for n in names if n.startswith(replay_side)] == []
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not [c for c in consts if re.search(r"sealed_outcomes|demo_cases|recorded_runs|raw/", c)]


# --------------------------------------------------------------------------- (b) data


def _tavily_payload() -> dict:
    return {
        "query": "regional bank deposit outflows",
        "results": [
            {
                "title": "Deposits fell again",
                "url": "https://news.example.com/deposits",
                "content": "Deposits at small banks fell for a third week.",
                "score": 0.8,
                "published_date": "Tue, 11 Mar 2025 17:00:00 GMT",
            }
        ],
        "response_time": 0.4,
        "request_id": "req-1",
    }


def _search_once() -> tavily.TavilySearchResponse:
    import asyncio

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_tavily_payload()))
    client = tavily.TavilyClient(FAKE_KEY, transport=transport)
    return asyncio.run(client.search("regional bank deposit outflows"))


def test_tavily_result_is_not_an_evidence_item():
    resp = _search_once()
    hit = resp.items[0]
    assert not isinstance(hit, EvidenceItem)
    # A direct conversion fails validation: no available_at, observed_at, content hash, ids or provenance.
    with pytest.raises(ValidationError) as exc:
        EvidenceItem.model_validate(hit.as_dict())
    missing = {e["loc"][0] for e in exc.value.errors() if e["type"] == "missing"}
    assert {"available_at", "evidence_id", "event_id", "content_sha256", "observed_at", "provenance"} <= missing
    # The response API reports retrieval time; it never claims a point-in-time availability.
    assert "available_at" not in hit.as_dict()
    assert hit.retrieved_at == resp.retrieved_at


def test_forged_evidence_from_tavily_is_refused_by_the_gate():
    """Even dated by retrieval time (the only time Live Explore can vouch for), it is after any replay cutoff."""
    resp = _search_once()
    hit = resp.items[0]
    as_of = resp.retrieved_at - timedelta(days=30)
    forged = EvidenceItem(
        evidence_id="tavily-forged-1",
        event_id="explore-sep-case",
        title=hit.title,
        source_url=hit.url,
        published_at=as_of - timedelta(days=1),  # even with a pre-cutoff claimed publish date
        observed_at=resp.retrieved_at,
        available_at=resp.retrieved_at,
        content_sha256="0" * 64,
        content=hit.snippet,
        provenance="REAL_HISTORICAL",
    )
    case = ReplayCase(
        event_id="explore-sep-case",
        title="separation check",
        as_of=as_of,
        horizon_days=30,
        resolution_rule="rule text",
        evidence_ids=["tavily-forged-1"],
        snapshot_hash="sha256:" + "0" * 64,
        synthetic=True,
        provenance="SYNTHETIC",
    )
    store = gate.EvidenceStore([CaseRecord(case=case, evidence=(forged,))])
    snap = store.get_as_of("explore-sep-case", as_of)
    assert snap.evidence_ids == ()
    assert [(x.item_id, x.reason) for x in snap.exclusions] == [("tavily-forged-1", "available_after_as_of")]
    assert not snap.market_available  # no quotes in this case: only agent_only can render
    prompt = gate.render_prompt(snap, "agent_only")
    assert hit.snippet not in prompt and hit.url not in prompt


# --------------------------------------------------------------------------- (c) runtime


class Tripwire:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []  # reached the TavilyClient mock transport
        self.http: list[str] = []  # any httpx request to a *tavily* host, however it was made

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=_tavily_payload())


@pytest.fixture
def tripwire(monkeypatch):
    """Key configured; every TavilyClient forced onto a counting mock transport; and every httpx request to a
    Tavily host (e.g. a raw ``httpx.post``) recorded and answered locally, never sent."""
    monkeypatch.setenv("TAVILY_API_KEY", FAKE_KEY)
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    wire = Tripwire()
    original_init = tavily.TavilyClient.__init__

    def counting_init(self, api_key, *, transport=None, **kwargs):
        original_init(self, api_key, transport=httpx.MockTransport(wire.handler), **kwargs)

    monkeypatch.setattr(tavily.TavilyClient, "__init__", counting_init)
    original_send, original_async_send = httpx.Client.send, httpx.AsyncClient.send

    def intercept(client, request) -> bool:
        """Record a Tavily-host request; True when it must not be forwarded (no mock transport behind it)."""
        if "tavily" not in (request.url.host or "").lower():
            return False
        wire.http.append(str(request.url))
        return not isinstance(getattr(client, "_transport", None), httpx.MockTransport)

    def send(self, request, **kw):
        if intercept(self, request):
            return httpx.Response(599, request=request)
        return original_send(self, request, **kw)

    async def async_send(self, request, **kw):
        if intercept(self, request):
            return httpx.Response(599, request=request)
        return await original_async_send(self, request, **kw)

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(httpx.AsyncClient, "send", async_send)
    return wire


def _non_explore_routes(app) -> list[tuple[str, str]]:
    """(METHOD, path) of every documented /api route except Live Explore (read from OpenAPI: version-robust)."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/api/") or path.startswith("/api/explore"):
            continue
        out.extend((method.upper(), path) for method in sorted(ops) if method in ("get", "post", "put", "delete"))
    return out


def test_no_tavily_call_while_driving_every_non_explore_route(tripwire):
    app = create_app()
    # /api/health would probe a real local Ollama; answer it from a mock instead (still no network).
    app.dependency_overrides[health.get_ollama_transport] = lambda: httpx.MockTransport(
        lambda req: httpx.Response(503)
    )
    client = TestClient(app)
    routes = _non_explore_routes(app)
    assert ("POST", "/api/simulate") in routes and ("GET", "/api/cases") in routes
    for method, path in routes:
        concrete = path.replace("{", "").replace("}", "")  # path params get a literal placeholder value
        if method == "GET":
            client.get(concrete)
            client.get(concrete, params={"as_of": "2024-01-01T00:00:00Z"})
        elif path == "/api/simulate":
            client.post(concrete, json={"shock": {}})
        # Other POST routes (e.g. a future /api/replay/run) would call the local model; the subprocess
        # tripwire below re-runs their own test modules instead.
    assert tripwire.requests == [] and tripwire.http == [], "Tavily was called during replay/sim routes"

    # Positive control: the tripwire does fire for the Live Explore route.
    resp = client.get("/api/explore/search", params={"q": "control query"})
    assert resp.status_code == 200, resp.text
    assert len(tripwire.requests) == 1 and len(tripwire.http) == 1


def test_tripwire_catches_a_raw_http_call_to_tavily(tripwire):
    """Positive control: a direct httpx call that bypasses TavilyClient is recorded and never leaves the process."""
    resp = httpx.post("https://api.tavily.com/search", json={"query": "x"})
    assert resp.status_code == 599
    assert tripwire.http == ["https://api.tavily.com/search"] and tripwire.requests == []


def _synthetic_store() -> gate.EvidenceStore:
    """Two synthetic cases: one with admissible and excluded evidence plus in-window quotes, one evidence-only."""
    second = CaseRecord(
        case=make_case("explore_sep_case_2"),
        evidence=(make_evidence("evid_sep_2", AS_OF - timedelta(days=1), "Second synthetic source text.",
                                event_id="explore_sep_case_2"),),
    )
    return gate.EvidenceStore([standard_record(), second])


def test_no_tavily_call_while_rendering_every_replay_prompt(tripwire):
    """Render every prompt variant for every case of a synthetic store (never empty) and of the committed
    demo cases (empty until #20 lands)."""
    stores = [_synthetic_store(), gate.EvidenceStore.from_dir()]
    assert len(stores[0].case_ids()) == 2
    rendered = 0
    for store in stores:
        for case_id in store.case_ids():
            snap = store.get_as_of(case_id, store.public_case(case_id).as_of)
            for variant in gate.PROMPT_VARIANTS:
                if variant == "agent_plus_market" and not snap.market_available:
                    continue
                assert gate.render_prompt(snap, variant).strip()
                rendered += 1
    assert rendered >= 3  # synthetic case 1 renders both variants, case 2 agent_only
    assert tripwire.requests == [] and tripwire.http == []


_TRIPWIRE_PLUGIN = '''
"""pytest plugin: record every Tavily client construction or search, and every httpx request to a Tavily host."""
import json, os

import httpx

_calls = []


def _tavily_host(request):
    return "tavily" in (request.url.host or "").lower()


def pytest_configure(config):
    from agents import tavily

    original_init = tavily.TavilyClient.__init__

    def init(self, *a, **k):
        _calls.append("init")
        original_init(self, *a, **k)

    async def search(self, *a, **k):
        _calls.append("search")
        raise AssertionError("Tavily search during a replay test")

    tavily.TavilyClient.__init__ = init
    tavily.TavilyClient.search = search

    original_send, original_async_send = httpx.Client.send, httpx.AsyncClient.send

    def send(self, request, **kw):
        if _tavily_host(request):
            _calls.append("http")
            return httpx.Response(599, request=request)
        return original_send(self, request, **kw)

    async def async_send(self, request, **kw):
        if _tavily_host(request):
            _calls.append("http")
            return httpx.Response(599, request=request)
        return await original_async_send(self, request, **kw)

    httpx.Client.send = send
    httpx.AsyncClient.send = async_send


def pytest_unconfigure(config):
    with open(os.environ["EXPLORE_TRIPWIRE_OUT"], "w") as fh:
        json.dump(_calls, fh)
'''

REPLAY_TEST_GLOBS = ("test_temporal_gate*.py", "test_replay*.py", "test_scoring*.py", "test_routes_cases*.py",
                     "test_benchmark*.py", "test_agents_*.py", "test_evaluator*.py", "test_store*.py")


def _run_under_tripwire(tmp_path: Path, targets: list[str], cwd: Path) -> tuple[subprocess.CompletedProcess, list]:
    (tmp_path / "explore_tripwire_plugin.py").write_text(_TRIPWIRE_PLUGIN, encoding="utf-8")
    out_file = tmp_path / "calls.json"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(tmp_path), str(API_DIR)]),
        "TAVILY_API_KEY": FAKE_KEY,
        "EXPLORE_TRIPWIRE_OUT": str(out_file),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "explore_tripwire_plugin", "-p", "no:cacheprovider", *targets],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=300,
    )
    return proc, json.loads(out_file.read_text(encoding="utf-8"))


def test_replay_test_modules_make_no_tavily_call(tmp_path):
    tests_dir = API_DIR / "tests"
    files = sorted({p.name for g in REPLAY_TEST_GLOBS for p in tests_dir.glob(g)})
    assert {"test_temporal_gate.py", "test_replay_seal.py", "test_scoring.py", "test_routes_cases.py",
            "test_agents_provider.py"} <= set(files)
    proc, calls = _run_under_tripwire(tmp_path, [f"tests/{f}" for f in files], API_DIR)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    assert calls == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (f"from agents import tavily\n\ndef test_calls():\n    tavily.TavilyClient({FAKE_KEY!r})\n", ["init"]),
        ("import httpx\n\ndef test_calls():\n    httpx.post('https://api.tavily.com/search', json={})\n", ["http"]),
    ],
)
def test_tripwire_plugin_detects_a_call(tmp_path, body, expected):
    """Positive controls for the subprocess tripwire: client use and a raw HTTP call are both recorded."""
    probe = tmp_path / "test_probe.py"
    probe.write_text(body, encoding="utf-8")
    _, calls = _run_under_tripwire(tmp_path, [str(probe)], tmp_path)
    assert calls == expected


def test_retrieved_at_is_now_not_a_historical_date():
    """Live Explore stamps results with the retrieval instant; it never back-dates them."""
    before = datetime.now(UTC)
    resp = _search_once()
    after = datetime.now(UTC)
    assert before <= resp.retrieved_at <= after


# --------------------------------------------------------------------------- (d) the LIVE EXPLORE chat (#187)

CHAT_MODULES = ("agents.explore_chat", "agents.explore_chat_steps", "routes.explore_chat")  # #222: live step previews
# Everything on the Blind Replay / scoring side, plus the replay-side agents. The chat may import the deterministic
# engine (core.financials, core.optimizer, core.decision, core.research) and its public routes, nothing else.
REPLAY_SIDE = (
    "core.temporal_gate", "core.store", "core.evaluator", "core.provenance", "core.forecasting", "core.scoring",
    "markets", "routes.replay", "routes.cases", "routes.benchmark", "routes.recorded", "routes.integrity",
    "routes.evidence", "routes.health", "agents.provider", "agents.local_ollama", "agents.skeptic",
    "agents.model_cards", "agents.explore_analyst",
)
# Replay data locations (directory / file names). Prose such as the system prompt's "no access to sealed outcomes"
# rule is allowed; a path or store name is not.
_REPLAY_DATA = re.compile(r"sealed_outcomes|demo_cases|recorded_runs|predictions\.sqlite|scorecards?/|raw/|"
                          r"FAULTLINE_PREDICTIONS_DB|FAULTLINE_DEMO_STORE", re.I)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            names.add(n.module or "")
            names |= {f"{n.module}.{a.name}" for a in n.names}
    return names


@pytest.mark.parametrize("module", CHAT_MODULES)
def test_chat_modules_import_no_replay_code(module):
    names = _imports(_module_path(module))
    assert [n for n in names if n.startswith(REPLAY_SIDE)] == []
    tree = ast.parse(_module_path(module).read_text(encoding="utf-8"))
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    # Docstrings may describe the walls; code constants may not name replay data.
    docstrings = {n.body[0].value.value for n in ast.walk(tree)
                  if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    assert [c for c in consts - docstrings if _REPLAY_DATA.search(c)] == []


def test_chat_modules_do_not_load_replay_code_transitively():
    code = textwrap.dedent(
        f"""
        import importlib, json, sys
        for name in {CHAT_MODULES!r}:
            importlib.import_module(name)
        side = {REPLAY_SIDE!r}
        print(json.dumps(sorted(m for m in sys.modules if m.startswith(side))))
        """
    )
    env = {**os.environ, "PYTHONPATH": str(API_DIR)}
    out = subprocess.run([sys.executable, "-c", code], cwd=API_DIR, env=env, capture_output=True, text=True,
                         timeout=60, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []


def test_replay_modules_do_not_load_the_chat():
    present = [m for m in REPLAY_MODULES if _module_path(m).is_file()]
    code = textwrap.dedent(
        f"""
        import importlib, json, sys
        for name in {present!r}:
            importlib.import_module(name)
        print(json.dumps(sorted(m for m in sys.modules if "explore_chat" in m)))
        """
    )
    env = {**os.environ, "PYTHONPATH": str(API_DIR)}
    out = subprocess.run([sys.executable, "-c", code], cwd=API_DIR, env=env, capture_output=True, text=True,
                         timeout=60, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []


@pytest.mark.parametrize("source", [
    "from agents import explore_chat",
    "import agents.explore_chat",
    "from routes import explore_chat",
    "import routes.explore_chat",
    "import httpx\nhttpx.post('http://localhost:8000/api/explore/chat', json={})",
])
def test_sweep_flags_references_to_the_chat(source):
    assert live_explore_refs(source), source


def test_chat_tools_expose_no_replay_surface(monkeypatch):
    """The model can only call engine tools: nothing that names a case, a reveal, a prediction or a score."""
    from config import get_settings
    from routes.explore_chat import EngineToolBox

    monkeypatch.setenv("TAVILY_API_KEY", FAKE_KEY)
    names = [t.name for t in EngineToolBox(get_settings(), None).specs()]
    assert names == ["simulate", "optimize", "decision", "list_scenarios", "list_judge_challenges",
                     "list_decision_frames", "vc_lenses", "monte_carlo_decision", "monte_carlo_cash",
                     "query_internal_data", "web_search"]
    assert not [n for n in names if re.search(r"replay|case|reveal|outcome|predict|benchmark|score|seal", n)]
