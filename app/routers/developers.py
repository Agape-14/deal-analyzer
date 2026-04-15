from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import Developer, Deal

router = APIRouter()


class DeveloperCreate(BaseModel):
    name: str
    contact_name: Optional[str] = ""
    contact_email: Optional[str] = ""
    phone: Optional[str] = ""
    track_record: Optional[str] = ""
    notes: Optional[str] = ""


class DeveloperUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    track_record: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
async def list_developers(
    trash: bool = False,
    db: AsyncSession = Depends(get_db),
):
    q = select(Developer).order_by(Developer.name)
    q = q.where(Developer.deleted_at.is_not(None) if trash else Developer.deleted_at.is_(None))
    result = await db.execute(q)
    devs = result.scalars().all()
    output = []
    for dev in devs:
        # Count deals
        count_result = await db.execute(
            select(func.count(Deal.id)).where(Deal.developer_id == dev.id)
        )
        deal_count = count_result.scalar() or 0
        output.append({
            "id": dev.id,
            "name": dev.name,
            "contact_name": dev.contact_name,
            "contact_email": dev.contact_email,
            "phone": dev.phone,
            "track_record": dev.track_record,
            "notes": dev.notes,
            "deal_count": deal_count,
            "created_at": dev.created_at.isoformat() if dev.created_at else None,
        })
    return output


@router.post("")
async def create_developer(data: DeveloperCreate, db: AsyncSession = Depends(get_db)):
    dev = Developer(**data.model_dump())
    db.add(dev)
    await db.commit()
    await db.refresh(dev)
    return {"id": dev.id, "name": dev.name, "message": "Developer created"}


@router.get("/{dev_id}")
async def get_developer(dev_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Developer).where(Developer.id == dev_id))
    dev = result.scalar_one_or_none()
    if not dev or dev.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Developer not found")

    # Get deals
    deals_result = await db.execute(
        select(Deal).where(Deal.developer_id == dev_id).order_by(Deal.created_at.desc())
    )
    deals = deals_result.scalars().all()

    return {
        "id": dev.id,
        "name": dev.name,
        "contact_name": dev.contact_name,
        "contact_email": dev.contact_email,
        "phone": dev.phone,
        "track_record": dev.track_record,
        "notes": dev.notes,
        "created_at": dev.created_at.isoformat() if dev.created_at else None,
        "deals": [
            {
                "id": d.id,
                "project_name": d.project_name,
                "location": d.location,
                "property_type": d.property_type,
                "status": d.status,
                "scores": d.scores or {},
            }
            for d in deals
        ],
    }


@router.put("/{dev_id}")
async def update_developer(dev_id: int, data: DeveloperUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Developer).where(Developer.id == dev_id))
    dev = result.scalar_one_or_none()
    if not dev:
        raise HTTPException(status_code=404, detail="Developer not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(dev, key, value)
    await db.commit()
    return {"message": "Developer updated"}


@router.delete("/{dev_id}")
async def delete_developer(dev_id: int, db: AsyncSession = Depends(get_db)):
    """Soft-delete. See the Deal equivalent for semantics."""
    result = await db.execute(select(Developer).where(Developer.id == dev_id))
    dev = result.scalar_one_or_none()
    if not dev or dev.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Developer not found")
    dev.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Developer moved to trash", "id": dev_id}


@router.post("/{dev_id}/restore")
async def restore_developer(dev_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Developer).where(Developer.id == dev_id))
    dev = result.scalar_one_or_none()
    if not dev:
        raise HTTPException(status_code=404, detail="Developer not found")
    dev.deleted_at = None
    await db.commit()
    return {"message": "Restored", "id": dev_id}


@router.delete("/{dev_id}/purge")
async def purge_developer(dev_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Developer).where(Developer.id == dev_id))
    dev = result.scalar_one_or_none()
    if not dev:
        raise HTTPException(status_code=404, detail="Developer not found")
    if dev.deleted_at is None:
        raise HTTPException(
            status_code=409,
            detail="Developer must be in the trash before it can be purged.",
        )
    await db.delete(dev)
    await db.commit()
    return {"message": "Purged"}
