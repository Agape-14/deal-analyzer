"""Failures and stale searches must not masquerade as complete current data."""
from datetime import date
from types import SimpleNamespace

import httpx
import pytest


@pytest.mark.asyncio
async def test_market_search_uses_current_year_without_blocking_client(monkeypatch):
    from app.services import market_data as market
    queries = []
    async def search(query):
        queries.append(query)
        return []
    async def create(**kwargs):
        assert date.today().isoformat() in kwargs["messages"][0]["content"]
        return SimpleNamespace(content=[SimpleNamespace(text='{"population":null}')])
    monkeypatch.setattr(market, "brave_search", search)
    monkeypatch.setattr(market, "AsyncAnthropic", lambda **kwargs: SimpleNamespace(messages=SimpleNamespace(create=create)))
    result = await market.fetch_market_data("Example", "CA")
    assert all(str(date.today().year) in q for q in queries)
    assert result["research_date"] == date.today().isoformat()
    assert result["population"] is None


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
