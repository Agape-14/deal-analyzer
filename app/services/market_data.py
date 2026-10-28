"""Asset-aware public research context, without generated numeric statistics."""
from datetime import date
from urllib.parse import urlencode
from app.services.public_context import census_context

PROFILES = {
    "multifamily": "apartment asking rents unit mix occupancy concessions supply pipeline",
    "office": "office lease rents vacancy absorption lease term tenant improvements",
    "retail": "retail lease rents vacancy tenant sales trade area foot traffic",
    "industrial": "industrial warehouse lease rents vacancy absorption logistics supply",
    "hospitality": "hotel occupancy average daily rate RevPAR seasonality supply",
    "land": "land zoning entitlement utilities absorption comparable land sales",
    "mixed_use": "mixed use component specific residential commercial lease rents supply",
}


async def fetch_market_data(city: str, state: str, property_type: str = "multifamily") -> dict:
    profile = property_type.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"apartment": "multifamily", "apartments": "multifamily", "mixed": "mixed_use", "hotel": "hospitality"}
    profile = aliases.get(profile, profile)
    context = await census_context(city, state)
    query = f"{city} {state} {PROFILES.get(profile, property_type + ' property market')} {date.today().year}"
    return {**context, "city": city, "state": state, "property_type": profile,
            "research_date": date.today().isoformat(), "profile_supported": profile in PROFILES,
            "asset_guidance": PROFILES.get(profile, "No supported research profile. Supply asset-specific evidence before drawing market conclusions."),
            "research_url": "https://www.google.com/search?" + urlencode({"q": query}),
            "market_summary": "Public demographics are area context. Asset-specific rent, vacancy and supply claims require matched, dated sources. No generated statistics are used.",
            "data_sources": sorted({o["source_url"] for o in context["observations"]})}
