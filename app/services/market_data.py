"""Market Data Service — pulls real market data via Brave Search + Claude AI analysis."""

import os
import json
import httpx
from datetime import date
from anthropic import Anthropic

from app.config import MODEL_MARKET

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
ANTHROPIC_MODEL = MODEL_MARKET


async def brave_search(query: str, count: int = 10) -> list[dict]:
    """Search Brave and return web results."""
    brave_key = os.environ.get("BRAVE_API_KEY")
    if not brave_key:
        raise RuntimeError("BRAVE_API_KEY environment variable is not set")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            BRAVE_SEARCH_URL,
            params={"q": query, "count": count},
            headers={"X-Subscription-Token": brave_key, "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    results = []
    for r in (data.get("web", {}).get("results", []))[:count]:
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("description", ""),
        })
    return results


async def fetch_market_data(city: str, state: str) -> dict:
    """Fetch market data for a city/state using Brave Search + Claude analysis."""
    if not city or not state:
        raise ValueError("City and state are required for market research")

    # Two search queries
    q1 = f"{city} {state} apartment market rent growth population employment 2024 2025"
    q2 = f"{city} {state} new apartment construction pipeline supply multifamily"

    results1 = await brave_search(q1)
    results2 = await brave_search(q2)

    # Format search results for Claude
    search_text = "=== SEARCH 1: Market Overview ===\n"
    for r in results1:
        search_text += f"\nTitle: {r['title']}\nURL: {r['url']}\nSnippet: {r['description']}\n"

    search_text += "\n=== SEARCH 2: Supply Pipeline ===\n"
    for r in results2:
        search_text += f"\nTitle: {r['title']}\nURL: {r['url']}\nSnippet: {r['description']}\n"

    # All source URLs for citation
    all_urls = [r["url"] for r in results1 + results2 if r.get("url")]

    # Use Claude to extract structured data
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    prompt = f"""Analyze these search results about the {city}, {state} apartment/multifamily market.
Extract the best available data into a structured JSON object. Use actual numbers from the sources when available.
If a data point isn't available in the search results, use null (don't make up numbers).

Search Results:
{search_text}

Return ONLY valid JSON with this exact structure (no markdown, no explanation):
{{
  "population": <number or null>,
  "population_growth_pct": <number or null>,
  "median_household_income": <number or null>,
  "unemployment_rate": <number or null>,
  "job_growth_pct": <number or null>,
  "major_employers": [<list of strings>],
  "avg_market_rent_1br": <number or null>,
  "avg_market_rent_2br": <number or null>,
  "rent_growth_yoy": <number or null>,
  "vacancy_rate": <number or null>,
  "new_supply_units": <number or null>,
  "new_supply_pct_of_stock": <number or null>,
  "median_home_price": <number or null>,
  "rent_to_own_ratio": <number or null>,
  "walk_score": null,
  "transit_score": null,
  "crime_rate_trend": <string or null>,
  "top_3_risks": [<3 risk strings based on data>],
  "top_3_strengths": [<3 strength strings based on data>],
  "market_summary": "<2-3 sentence summary of the market>"
}}"""

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()
    # Strip markdown code fences if present
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        response_text = "\n".join(lines)

    market_data = json.loads(response_text)

    # Add metadata
    market_data["data_sources"] = all_urls[:6]
    market_data["research_date"] = date.today().isoformat()
    market_data["city"] = city
    market_data["state"] = state

    return market_data
