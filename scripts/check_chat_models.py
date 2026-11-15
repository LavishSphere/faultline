"""Print the LIVE EXPLORE chat catalogue as this server would build it (model ids and booleans only, never keys).

Run with `make chat-models` (loads the repo .env into this process only). It calls each configured provider's
model-list endpoint through the same code the API uses (agents.explore_chat.build_catalog), then reports which
featured and vetted models exist, so the defaults are verified against the live lists rather than assumed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "services" / "api"
sys.path.insert(0, str(API_DIR))

from agents import explore_chat as chat  # noqa: E402
from config import get_settings  # noqa: E402


async def main() -> int:
    settings = get_settings()
    print("keys configured:", {p: settings.chat_key_set(p) for p in chat.CHAT_PROVIDERS},
          "tavily:", settings.tavily_api_key_set)
    catalog = await chat.build_catalog(settings, chat.ClientFactory())
    for note in catalog.notes:
        print("note:", note)
    by_provider: dict[str, list[chat.CatalogModel]] = {}
    for m in catalog.models:
        by_provider.setdefault(m.provider, []).append(m)
    for provider, models in by_provider.items():
        affordable = [m for m in models if chat.affordable(m, settings.chat_max_price_per_mtok)]
        print(f"{provider}: {len(models)} models, {len(affordable)} within the public price cap")
    ids = {m.id for m in catalog.models}
    print("featured preference present:")
    for wanted in chat.FEATURED_PREFERENCE:
        m = next((x for x in catalog.models if x.id == wanted), None)
        price = f"out ${m.output_per_mtok}/Mtok" if m and m.output_per_mtok is not None else "price n/a"
        print(f"  {'YES' if wanted in ids else 'no '} {wanted} {price if m else ''}")
    featured = chat.featured_ids([m for m in catalog.models if chat.affordable(m, settings.chat_max_price_per_mtok)],
                                 catalog, settings)
    print("rejected keys:", sorted(catalog.rejected))
    print("featured (public):", featured)
    if settings.anthropic_api_key_set:
        try:
            listed = {m.id async for m in chat.ClientFactory().anthropic().models.list()}
        except Exception as err:  # noqa: BLE001 - report the class only, never the body
            print("anthropic model list failed:", type(err).__name__)
        else:
            for mid, *_ in chat.ANTHROPIC_MODELS:
                print(f"  anthropic list has {mid}: {mid in listed}")
    if "-v" in sys.argv:
        for m in catalog.models:
            print("  ", m.id, "|", m.output_per_mtok)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
