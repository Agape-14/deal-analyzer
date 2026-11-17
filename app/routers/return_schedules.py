"""Save an analyst-reviewed hold projection against the current deal revision."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.analysis import get_deal
from app.routers.field_edits import _refresh_integrity
from app.services.analysis import analysis_for_deal
from app.services.analysis_store import document_manifest
from app.services.return_schedules import SCHEDULE_KEY, ReturnScheduleInput, checked_return_schedule
from app.services.review_drafts import load_documents

router = APIRouter()


class ReturnScheduleUpdate(ReturnScheduleInput):
    expected_revision: int = Field(ge=1)


@router.put("/{deal_id}/analysis/return-schedule")
async def save_return_schedule(deal_id: int, update: ReturnScheduleUpdate, db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    if deal.revision != update.expected_revision:
        raise HTTPException(409, "The deal changed. Reload before reviewing the schedule.")
    if analysis_for_deal(deal)["primary_strategy"] not in {"hold", "hold_with_sale_option"}:
        raise HTTPException(422, "Select a hold strategy before adding a hold return schedule.")
    documents = await load_documents(db, deal.id)
    schedule = ReturnScheduleInput.model_validate(update.model_dump(exclude={"expected_revision"}))
    try:
        record = checked_return_schedule(schedule, documents, document_manifest(documents))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _refresh_integrity(deal, {**(deal.metrics or {}), SCHEDULE_KEY: record})
    await db.commit()
    await db.refresh(deal)
    return {"revision": deal.revision, "analysis": analysis_for_deal(deal)}
