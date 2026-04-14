"""
Location intelligence.

Everything in this module is free and unauthenticated by default:

  - Geocoding:          OpenStreetMap Nominatim
  - Businesses / POIs:  Overpass API (queries OSM)
  - Apartment buildings: Overpass API (building=apartments + similar tags)
  - Rent context:       HUD Fair Market Rent API (optional, free token)

Nominatim has a strict 1-request-per-second rate limit and requires a
User-Agent header. We cache aggressively on the Deal row
(`deal.location_data`) so we only hit the upstream sources on explicit
refresh. Overpass and Nominatim both support CORS but we proxy through
our backend so we can cache and so browser clients don't fan out.

All functions are async-safe via httpx.AsyncClient. Soft failures are
preferred to hard ones — the user's map should still render even if
Overpass is temporarily slow or HUD is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx


USER_AGENT = os.environ.get(
    "LOCATION_USER_AGENT",
    "Kenyon Deal Analyzer/1.0 (+https://conpulseai.com)",
)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
HUD_API_BASE = "https://www.huduser.gov/hudapi/public"


# ---------- Nominatim geocoding ---------- #

_last_nominatim_call = 0.0
_NOMINATIM_LOCK = asyncio.Lock()


async def _nominatim_throttle() -> None:
    """Serialize + slow down Nominatim calls to respect their 1 req/sec policy.

    Without this, a burst of upload+extract could hit them faster than
    allowed and get us soft-banned. This is a process-level gate; it's
    not perfect but it's correct for single-worker deployments.
    """
    global _last_nominatim_call
    async with _NOMINATIM_LOCK:
        now = time.monotonic()
        gap = now - _last_nominatim_call
        if gap < 1.05:
            await asyncio.sleep(1.05 - gap)
        _last_nominatim_call = time.monotonic()


async def geocode(query: str) -> dict | None:
    """Geocode a free-form string ("Sunset Apartments, Austin, TX") via Nominatim.

    Returns {lat, lng, display_name, bbox} or None if no match.
    """
    q = (query or "").strip()
    if not q:
        return None

    await _nominatim_throttle()
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(
                NOMINATIM_URL,
                params={"q": q, "format": "jsonv2", "limit": 1, "addressdetails": 1},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            r.raise_for_status()
            results = r.json() or []
        except httpx.HTTPError:
            return None

    if not results:
        return None

    hit = results[0]
    try:
        return {
            "lat": float(hit["lat"]),
            "lng": float(hit["lon"]),
            "display_name": hit.get("display_name") or q,
            "bbox": [float(x) for x in (hit.get("boundingbox") or [])],
            "address": hit.get("address") or {},
        }
    except (KeyError, ValueError, TypeError):
        return None


# ---------- Overpass categories ---------- #

# Each category maps to the Overpass "nwr" (nodes/ways/relations) query it
# should use. We keep the category surface small so the UI sidebar is
# decision-friendly, not an OSM tag dump. Icons + colors are UI concerns
# — we just return raw category keys here.
CATEGORY_QUERIES: dict[str, str] = {
    "apartments": """
        nwr["building"="apartments"](around:{r},{lat},{lng});
        nwr["building"="residential"]["residential"="apartments"](around:{r},{lat},{lng});
        nwr["landuse"="residential"]["residential"="apartments"](around:{r},{lat},{lng});
    """,
    "restaurants": """
        nwr["amenity"~"^(restaurant|cafe|fast_food|bar|pub)$"](around:{r},{lat},{lng});
    """,
    "grocery": """
        nwr["shop"~"^(supermarket|convenience|greengrocer)$"](around:{r},{lat},{lng});
    """,
    "transit": """
        nwr["railway"~"^(station|halt|tram_stop)$"](around:{r},{lat},{lng});
        nwr["highway"="bus_stop"](around:{r},{lat},{lng});
        nwr["public_transport"~"^(station|stop_position)$"](around:{r},{lat},{lng});
    """,
    "schools": """
        nwr["amenity"~"^(school|college|university|kindergarten)$"](around:{r},{lat},{lng});
    """,
    "healthcare": """
        nwr["amenity"~"^(hospital|clinic|doctors|pharmacy)$"](around:{r},{lat},{lng});
    """,
    "parks": """
        nwr["leisure"~"^(park|playground|nature_reserve|garden)$"](around:{r},{lat},{lng});
    """,
    "employers": """
        nwr["office"](around:{r},{lat},{lng});
    """,
}


def _element_centroid(el: dict) -> tuple[float, float] | None:
    """Pull a lat/lng out of any Overpass element (node / way / relation)."""
    if "lat" in el and "lon" in el:
        return float(el["lat"]), float(el["lon"])
    center = el.get("center")
    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance in meters between two (lat,lng) pairs."""
    import math

    R = 6371000.0
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


async def overpass_query(body: str) -> list[dict]:
    """Run a single Overpass query and return the raw element list."""
    query = f"[out:json][timeout:30];({body});out center tags;"
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(OVERPASS_URL, data=query, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        data = r.json() or {}
    return data.get("elements") or []


async def fetch_amenities(
    lat: float,
    lng: float,
    radius_m: int = 1600,   # ~1 mile default
    categories: list[str] | None = None,
    per_category_cap: int = 80,
) -> dict[str, list[dict]]:
    """Fetch POIs per category from Overpass, centered at (lat,lng).

    Returns a flat {category: [{id, lat, lng, name, category, tags, distance_m}]}
    map. Results are sorted by distance and capped so the frontend can render
    them without paging. Exceptions per-category are isolated so one bad
    query doesn't kill the whole response.
    """
    cats = categories or list(CATEGORY_QUERIES.keys())
    out: dict[str, list[dict]] = {c: [] for c in cats}
    origin = (lat, lng)

    # Fan out in parallel, but respect Overpass's soft concurrency guidance
    # by keeping it to 4 at a time.
    sem = asyncio.Semaphore(4)

    async def one(cat: str) -> None:
        tmpl = CATEGORY_QUERIES.get(cat)
        if not tmpl:
            return
        body = tmpl.format(r=radius_m, lat=lat, lng=lng)
        async with sem:
            try:
                elements = await overpass_query(body)
            except httpx.HTTPError:
                return
        points: list[dict] = []
        for el in elements:
            ll = _element_centroid(el)
            if not ll:
                continue
            tags = el.get("tags") or {}
            name = tags.get("name") or tags.get("brand") or tags.get("operator")
            if cat == "apartments" and not name:
                # Unnamed residential blocks everywhere = noise. Skip them.
                continue
            dist = _haversine_m(origin, ll)
            points.append(
                {
                    "id": f"{el.get('type')}/{el.get('id')}",
                    "lat": ll[0],
                    "lng": ll[1],
                    "name": name or _fallback_name(cat, tags),
                    "category": cat,
                    "tags": _slim_tags(tags),
                    "distance_m": round(dist),
                }
            )
        points.sort(key=lambda p: p["distance_m"])
        out[cat] = points[:per_category_cap]

    await asyncio.gather(*(one(c) for c in cats))
    return out


def _fallback_name(cat: str, tags: dict) -> str:
    """Useful label when OSM doesn't have a `name`."""
    if cat == "restaurants":
        return (tags.get("cuisine") or "Restaurant").title()
    if cat == "grocery":
        return (tags.get("shop") or "Grocery").title()
    if cat == "transit":
        return (tags.get("public_transport") or tags.get("railway") or "Transit stop").title()
    if cat == "schools":
        return (tags.get("amenity") or "School").title()
    if cat == "healthcare":
        return (tags.get("amenity") or "Healthcare").title()
    if cat == "parks":
        return (tags.get("leisure") or "Park").title()
    if cat == "employers":
        return (tags.get("office") or "Office").title()
    return cat.title()


# Fields worth surfacing in the popup. Anything else gets dropped.
_RELEVANT_TAG_KEYS = {
    "name", "brand", "cuisine", "phone", "website", "opening_hours",
    "building:levels", "building:flats", "units", "addr:housenumber",
    "addr:street", "addr:city", "addr:postcode", "operator", "shop",
    "amenity", "leisure", "office", "public_transport", "railway",
}


def _slim_tags(tags: dict) -> dict:
    return {k: v for k, v in (tags or {}).items() if k in _RELEVANT_TAG_KEYS}


# ---------- HUD Fair Market Rent ---------- #

async def fetch_hud_fmr(zip_code: str) -> dict | None:
    """
    Fetch HUD Fair Market Rent for a zip code. Returns studio/1br/2br/3br/4br
    dollar values plus metadata, or None if the API is unreachable or the
    token isn't configured. Graceful degradation is intentional — the map
    remains useful without FMR.
    """
    token = os.environ.get("HUD_API_TOKEN")
    if not token:
        return None
    zip5 = (zip_code or "").strip()[:5]
    if not zip5.isdigit() or len(zip5) != 5:
        return None

    url = f"{HUD_API_BASE}/fmr/data/{zip5}"
    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            payload = r.json() or {}
        except httpx.HTTPError:
            return None

    # HUD returns {data: {basicdata: {...}, county_name, metro_name, year, ...}}
    data = payload.get("data") or {}
    basic = data.get("basicdata") or data
    if not isinstance(basic, dict):
        return None

    def _num(v: Any) -> int | None:
        try:
            return int(round(float(v))) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return {
        "zip": zip5,
        "year": data.get("year"),
        "metro": data.get("metro_name") or data.get("counties_msa"),
        "county": data.get("county_name"),
        "rents": {
            "studio": _num(basic.get("Efficiency")),
            "br1": _num(basic.get("One-Bedroom")),
            "br2": _num(basic.get("Two-Bedroom")),
            "br3": _num(basic.get("Three-Bedroom")),
            "br4": _num(basic.get("Four-Bedroom")),
        },
    }


# ---------- Top-level composer ---------- #

async def build_location_bundle(
    deal,
    radius_m: int = 1600,
    force_refresh: bool = False,
) -> dict:
    """
    Compose the full 'Location' payload for a deal. Designed to be safe to
    call on every page load; fetches upstream only when there's no cached
    result or `force_refresh` is true.
    """
    cached = deal.location_data if not force_refresh else None
    # Use cached data if it's from the last 7 days and radius matches.
    if isinstance(cached, dict) and cached.get("radius_m") == radius_m:
        fetched_at = cached.get("fetched_at") or 0
        age = time.time() - float(fetched_at or 0)
        if age < 7 * 86400 and cached.get("categories"):
            return cached

    # Need coords — try stored first, then geocode.
    lat, lng = (deal.lat or None), (deal.lng or None)
    display = None
    if lat is None or lng is None:
        query = _compose_address(deal)
        geo = await geocode(query) if query else None
        if not geo:
            return {
                "lat": None,
                "lng": None,
                "radius_m": radius_m,
                "categories": {},
                "fmr": None,
                "display_name": None,
                "fetched_at": time.time(),
                "error": "Could not geocode address. Set city/state or manually place the marker.",
            }
        lat, lng = geo["lat"], geo["lng"]
        display = geo["display_name"]

    # Kick off Overpass + HUD in parallel
    amenities_task = fetch_amenities(lat, lng, radius_m)
    fmr_task = _fmr_from_deal(deal)
    categories, fmr = await asyncio.gather(amenities_task, fmr_task)

    return {
        "lat": lat,
        "lng": lng,
        "radius_m": radius_m,
        "categories": categories,
        "fmr": fmr,
        "display_name": display or _compose_address(deal),
        "fetched_at": time.time(),
    }


async def _fmr_from_deal(deal) -> dict | None:
    """Pull a zip code out of the deal if possible and look up HUD FMR."""
    # Try explicit zip on the address, then the OSM address if cached.
    zip_guess = _guess_zip(deal)
    if not zip_guess:
        return None
    return await fetch_hud_fmr(zip_guess)


def _compose_address(deal) -> str:
    bits = [deal.project_name, deal.location, deal.city, deal.state]
    return ", ".join(b for b in bits if b)


def _guess_zip(deal) -> str | None:
    # Stored location_data (if previously geocoded) may include the zip.
    loc = deal.location_data or {}
    addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
    z = addr.get("postcode") or addr.get("postal_code")
    if z:
        return str(z).strip()[:5]
    # Plain string "78701" at the end of `deal.location`
    import re

    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", deal.location or "")
    if m:
        return m.group(1)
    return None
