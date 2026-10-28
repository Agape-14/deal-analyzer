from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from app.database import get_db
from app.models import Deal, DealChat
from app.rate_limit import limit
from app.services.analysis import analysis_for_deal
from app.services.grounded_chat import answer_from_analysis

router = APIRouter()

class ChatMessage(BaseModel):
    deal_id: int
    message: str = Field(min_length=1, max_length=4000)

async def current_analysis(db, deal_id):
    deal = await current_deal(db, deal_id)
    return analysis_for_deal(deal)

async def current_deal(db, deal_id):
    deal = (await db.execute(select(Deal).options(selectinload(Deal.documents), selectinload(Deal.developer)).where(Deal.id == deal_id))).scalar_one_or_none()
    if not deal or deal.deleted_at is not None:
        raise HTTPException(404, "Deal not found")
    return deal

def message_payload(row, analysis):
    return {"id": row.id, "role": row.role, "content": row.content,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "analysis_version": row.analysis_version, "answer_kind": row.answer_kind,
            "references": row.references or [],
            "stale": row.role == "assistant" and (row.analysis_input_hash != analysis["input_hash"] or row.analysis_version != analysis["version"])}

@router.post("", dependencies=[Depends(limit("ai"))])
async def chat_with_deal(data: ChatMessage, db: AsyncSession = Depends(get_db)):
    if not data.message.strip():
        raise HTTPException(422, "Enter a question")
    deal = await current_deal(db, data.deal_id)
    analysis = analysis_for_deal(deal)
    text, references = answer_from_analysis(analysis, data.message, deal.documents)
    metadata = {"analysis_version": analysis["version"], "analysis_input_hash": analysis["input_hash"], "answer_kind": "reviewed_facts"}
    db.add(DealChat(deal_id=data.deal_id, role="user", content=data.message.strip(), **metadata))
    reply = DealChat(deal_id=data.deal_id, role="assistant", content=text, references=references, **metadata)
    db.add(reply)
    await db.commit()
    return {"response": text, "message": message_payload(reply, analysis)}


@router.get("/search")
async def search_evidence(q: str, deal_id: int | None = None, db: AsyncSession = Depends(get_db)):
    if not 2 <= len(q.strip()) <= 200:
        raise HTTPException(422, "Search needs 2–200 characters")
    from app.services.evidence_search import search_documents
    query = select(Deal).where(Deal.deleted_at.is_(None)).options(selectinload(Deal.documents)).order_by(Deal.id.desc()).limit(100)
    if deal_id:
        query = query.where(Deal.id == deal_id)
    deals = (await db.execute(query)).scalars().all()
    if deal_id and not deals:
        raise HTTPException(404, "Deal not found")
    hits = []
    for deal in deals:
        for hit in search_documents(deal.documents, q, limit=3):
            hits.append({**hit, "deal_id": deal.id, "project_name": deal.project_name,
                         "analysis_version": deal.analysis_version, "kind": "reported_excerpt"})
    return {"hits": hits[:20], "scope": "Current active sources in up to 100 most recently added deals; 100 documents per deal. Reported excerpts require review."}

@router.get("/history/{deal_id}")
async def get_chat_history(deal_id: int, db: AsyncSession = Depends(get_db)):
    analysis = await current_analysis(db, deal_id)
    rows = (await db.execute(select(DealChat).where(DealChat.deal_id == deal_id).order_by(DealChat.created_at, DealChat.id))).scalars().all()
    return [message_payload(row, analysis) for row in rows]

@router.delete("/history/{deal_id}")
async def clear_chat_history(deal_id: int, db: AsyncSession = Depends(get_db)):
    await current_analysis(db, deal_id)
    rows = (await db.execute(select(DealChat).where(DealChat.deal_id == deal_id))).scalars().all()
    for row in rows:
        await db.delete(row)
    await db.commit()
    return {"message": "Chat history cleared"}
