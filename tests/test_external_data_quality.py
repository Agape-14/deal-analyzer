"""Failures and stale searches must not masquerade as complete current data."""
from datetime import date
from types import SimpleNamespace

import httpx
import pytest


@pytest.mark.asyncio
async def test_market_search_uses_current_year_without_blocking_client(monkeypatch):
    from app.services import market_data as market
    async def context(city, state):
        return {"status": "unavailable", "observations": [], "message": "No exact place match"}
    monkeypatch.setattr(market, "census_context", context)
    result = await market.fetch_market_data("Example", "CA", "office")
    assert str(date.today().year) in result["research_url"]
    assert "office" in result["asset_guidance"] and "apartment" not in result["asset_guidance"]
    assert result["research_date"] == date.today().isoformat()
    assert result["observations"] == []
    assert "population" not in result  # No generated or unsupported statistic.


@pytest.mark.asyncio
async def test_census_estimates_have_exact_geography_period_and_suppression(monkeypatch):
    from app.services import public_context as public
    public._cache.clear()
    rows = [["NAME", "B01003_001E", "B19013_001E", "B01003_001M", "B19013_001M", "state", "place"],
            ["Example city, California", "10000", "-666666666", "50", "-222222222", "06", "12345"]]
    async def handle(request):
        return httpx.Response(200, json=rows)
    client = httpx.AsyncClient
    monkeypatch.setattr(public.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(handle)))
    result = await public.census_context("Example", "CA")
    population, income = result["observations"]
    assert population["value"] == 10000 and population["margin_of_error"] == 50
    assert population["geography_id"] == "1600000US0612345" and population["geography_level"] == "place"
    assert population["observed_period"] == f"{date.today().year-6}–{date.today().year-2}"
    assert "api.census.gov" in population["source_url"] and population["retrieved_at"]
    assert income["value"] is None and income["status"] == "suppressed_or_unavailable"
    assert (await public.census_context("No match", "CA"))["status"] == "unavailable"


@pytest.mark.asyncio
async def test_land_and_unsupported_asset_profiles_do_not_use_apartment_defaults(monkeypatch):
    from app.services import market_data as market
    async def context(*args):
        return {"observations": [], "status": "unavailable"}
    monkeypatch.setattr(market, "census_context", context)
    for kind in ("land", "industrial", "specialty"):
        result = await market.fetch_market_data("Example", "CA", kind)
        assert "apartment" not in result["research_url"]
        assert result["profile_supported"] == (kind != "specialty")


@pytest.mark.asyncio
async def test_map_partial_failure_is_explicit_and_not_cached_as_complete(monkeypatch):
    from app.services import location_intelligence as location
    calls = []
    async def query(body):
        calls.append(body)
        if '"shop"' in body:
            raise httpx.ReadTimeout("upstream timeout")
        return []
    async def fmr(deal):
        return None
    monkeypatch.setattr(location, "overpass_query", query)
    monkeypatch.setattr(location, "_fmr_from_deal", fmr)
    deal = SimpleNamespace(lat=0.0, lng=0.0, location_data=None, project_name="Example", location="", city="", state="")
    bundle = await location.build_location_bundle(deal)
    assert bundle["lat"] == 0
    assert set(bundle["category_errors"]) == {"grocery"}
    assert bundle["categories"]["grocery"] == []
    assert "parks" not in bundle["category_errors"]
    deal.location_data = bundle
    count = len(calls)
    await location.build_location_bundle(deal)
    assert len(calls) > count


def test_csv_and_workbook_limits_are_explicit(tmp_path, monkeypatch):
    from app.services import spreadsheet_extractor as sheets
    from openpyxl import Workbook
    monkeypatch.setattr(sheets, "MAX_ROWS_PER_SHEET", 2)
    monkeypatch.setattr(sheets, "MAX_SHEETS", 1)
    csv = tmp_path / "rows.csv"
    csv.write_text("Metric,Value\nUnits,10\nIRR,15\n")
    result = sheets.extract_spreadsheet(str(csv))
    assert result.page_diagnostics[0]["truncated"]
    assert "INCOMPLETE SHEET" in result.text
    workbook = Workbook()
    workbook.active.append(["Units", 10])
    workbook.create_sheet("Omitted").append(["IRR", 15])
    path = tmp_path / "sheets.xlsx"
    workbook.save(path)
    result = sheets.extract_spreadsheet(str(path))
    assert result.page_diagnostics[0]["omitted_sheets"] == 1
    assert "INCOMPLETE WORKBOOK" in result.text
