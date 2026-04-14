"""Market research service — stub for now. Will add Brave search integration later."""


async def research_market(city: str, state: str, property_type: str) -> dict:
    """Research market data for a given location. Returns dict of market data."""
    # TODO: Integrate Brave search API for market research
    return {
        "status": "not_implemented",
        "message": "Market research coming soon. Upload offering memos with market data for now."
    }
