import os
import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from app.database import get_db
from app.models import Deal, DealChat, DealDocument

router = APIRouter()


class ChatMessage(BaseModel):
    deal_id: int
    message: str


@router.post("")
async def chat_with_deal(data: ChatMessage, db: AsyncSession = Depends(get_db)):
    """Chat with AI about a specific deal."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    # Get deal with docs
    result = await db.execute(
        select(Deal)
        .options(selectinload(Deal.documents), selectinload(Deal.developer))
        .where(Deal.id == data.deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    # Get chat history
    history_result = await db.execute(
        select(DealChat)
        .where(DealChat.deal_id == data.deal_id)
        .order_by(DealChat.created_at)
    )
    history = history_result.scalars().all()

    # Build system prompt with deal context
    doc_context = ""
    for doc in deal.documents:
        if doc.extracted_text:
            doc_context += f"\n\n--- {doc.filename} ({doc.doc_type}) ---\n"
            doc_context += doc.extracted_text[:20000]

    metrics_str = ""
    if deal.metrics:
        import json
        metrics_str = f"\n\nEXTRACTED METRICS:\n{json.dumps(deal.metrics, indent=2)}"

    scores_str = ""
    if deal.scores:
        import json
        scores_str = f"\n\nDEAL SCORES:\n{json.dumps(deal.scores, indent=2)}"

    system_prompt = f"""You are an expert real estate investment analyst assistant. You are analyzing a specific deal.

DEAL: {deal.project_name}
DEVELOPER: {deal.developer.name if deal.developer else 'Unknown'}
LOCATION: {deal.location or ''}, {deal.city or ''}, {deal.state or ''}
PROPERTY TYPE: {deal.property_type}
STATUS: {deal.status}
{metrics_str}
{scores_str}

DOCUMENT CONTENTS:
{doc_context}

Answer questions about this deal accurately based on the documents and extracted metrics. If you don't know something, say so. Provide specific numbers and references when available. Be concise but thorough."""

    # Build messages
    messages = []
    for chat in history[-20:]:  # Last 20 messages for context
        messages.append({"role": chat.role, "content": chat.content})
    messages.append({"role": "user", "content": data.message})

    # Save user message
    user_chat = DealChat(deal_id=data.deal_id, role="user", content=data.message)
    db.add(user_chat)

    # Call Claude
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )
        assistant_text = response.content[0].text
    except Exception as e:
        await db.commit()
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

    # Save assistant message
    assistant_chat = DealChat(deal_id=data.deal_id, role="assistant", content=assistant_text)
    db.add(assistant_chat)
    await db.commit()

    return {"response": assistant_text}


@router.get("/history/{deal_id}")
async def get_chat_history(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DealChat)
        .where(DealChat.deal_id == deal_id)
        .order_by(DealChat.created_at)
    )
    chats = result.scalars().all()
    return [
        {
            "id": c.id,
            "role": c.role,
            "content": c.content,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in chats
    ]


@router.delete("/history/{deal_id}")
async def clear_chat_history(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DealChat).where(DealChat.deal_id == deal_id)
    )
    chats = result.scalars().all()
    for chat in chats:
        await db.delete(chat)
    await db.commit()
    return {"message": "Chat history cleared"}
