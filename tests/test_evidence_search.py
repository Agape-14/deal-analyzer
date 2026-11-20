from types import SimpleNamespace as Row

from app.services.evidence_search import search_documents
from app.services.grounded_chat import answer_from_analysis


def source(**changes):
    return Row(**(dict(id=1, filename="Terms.xlsx", file_sha256="abc", extracted_text="--- Sheet: Terms ---\nA1=Transfer restrictions | B1=No redemption before maturity\nA2=Management fee | B2=1%", source_role="active", superseded_by_id=None, extraction_quality={}) | changes))


def test_liquidity_lookup_retains_cell_and_skips_superseded_or_duplicate_sources():
    hits = search_documents([source(), source(id=2), source(id=3, file_sha256="old", source_role="superseded")], "What liquidity is available?")
    assert len(hits) == 1 and hits[0]["document_id"] == 1
    assert hits[0]["sheet"] == "Terms" and hits[0]["cell"] == "A1"
    assert hits[0]["content_hash"] == "abc"


def test_unmatched_question_never_substitutes_returns_and_quotes_are_reported():
    analysis = dict(facts={}, returns={}, questions=[], version=2)
    answer, refs = answer_from_analysis(analysis, "What about a swimming pool?")
    assert "No accepted fact" in answer and "headline returns" not in answer and refs == []
    answer, refs = answer_from_analysis(analysis, "What management fees apply?", [source()])
    assert "Reported source excerpts" in answer and "Management fee" in answer
    assert refs[0]["state"] == "reported" and "revision 2" in answer
