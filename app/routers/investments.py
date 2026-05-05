from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from typing import Optional
from datetime import date
from app.database import get_db
from app.models import Investment, Distribution, Deal

router = APIRouter()


# ===== Pydantic Models =====

class InvestmentCreate(BaseModel):
    deal_id: Optional[int] = None
    project_name: str = ""
    sponsor_name: str = ""
    investment_date: Optional[date] = None
    amount_invested: float = 0
    shares: float = 0
    investment_class: str = ""
    preferred_return: Optional[float] = None
    projected_irr: Optional[float] = None
    projected_equity_multiple: Optional[float] = None
    hold_period_years: Optional[float] = None
    status: str = "active"
    notes: str = ""


class InvestmentUpdate(BaseModel):
    project_name: Optional[str] = None
    sponsor_name: Optional[str] = None
    investment_date: Optional[date] = None
    amount_invested: Optional[float] = None
    shares: Optional[float] = None
    investment_class: Optional[str] = None
    preferred_return: Optional[float] = None
    projected_irr: Optional[float] = None
    projected_equity_multiple: Optional[float] = None
    hold_period_years: Optional[float] = None
    status: Optional[str] = None
    exit_date: Optional[date] = None
    exit_amount: Optional[float] = None
    notes: Optional[str] = None


class DistributionCreate(BaseModel):
    date: date
    amount: float
    dist_type: str = "cash_flow"
    period: str = ""
    notes: str = ""


# ===== Investment Endpoints =====

@router.get("/")
async def list_investments(db: AsyncSession = Depends(get_db)):
    """List all investments with distributions."""
    result = await db.execute(
        select(Investment)
        .options(selectinload(Investment.distributions), selectinload(Investment.deal))
        .order_by(Investment.created_at.desc())
    )
    investments = result.scalars().all()

    return [_serialize_investment(inv) for inv in investments]


@router.get("/portfolio")
async def portfolio_summary(db: AsyncSession = Depends(get_db)):
    """Get portfolio-level summary stats."""
    result = await db.execute(
        select(Investment)
        .options(selectinload(Investment.distributions), selectinload(Investment.deal))
    )
    investments = result.scalars().all()

    total_invested = 0
    total_distributions = 0
    total_exit_proceeds = 0
    active_count = 0
    exited_count = 0
    status_counts: dict[str, int] = {}
    sponsor_exposure: dict[str, float] = {}
    property_type_exposure: dict[str, float] = {}

    for inv in investments:
        invested = inv.amount_invested or 0
        total_invested += invested
        for dist in inv.distributions:
            total_distributions += dist.amount or 0

        status = inv.status or "active"
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "active":
            active_count += 1
        elif status == "exited":
            exited_count += 1
            total_exit_proceeds += inv.exit_amount or 0

        sponsor = inv.sponsor_name or "Unassigned"
        sponsor_exposure[sponsor] = sponsor_exposure.get(sponsor, 0) + invested

        property_type = inv.deal.property_type if inv.deal else "standalone"
        property_type_exposure[property_type or "unknown"] = property_type_exposure.get(property_type or "unknown", 0) + invested

    total_returned = total_distributions + total_exit_proceeds
    overall_multiple = round(total_returned / total_invested, 2) if total_invested > 0 else 0
    net_profit = total_returned - total_invested

    return {
        "total_invested": total_invested,
        "total_distributions": total_distributions,
        "total_exit_proceeds": total_exit_proceeds,
        "total_returned": total_returned,
        "net_profit": net_profit,
        "overall_multiple": overall_multiple,
        "active_investments": active_count,
        "exited_investments": exited_count,
        "total_investments": len(investments),
        "status_counts": status_counts,
        "allocation": {
            "by_sponsor": _exposure_rows(sponsor_exposure, total_invested),
            "by_property_type": _exposure_rows(property_type_exposure, total_invested),
        },
    }


@router.post("/")
async def create_investment(data: InvestmentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new investment."""
    # If deal_id is provided, use one eager-loaded query so async SQLAlchemy never lazy-loads relationships.
    if data.deal_id:
        deal_result = await db.execute(
            select(Deal)
            .options(selectinload(Deal.developer))
            .where(Deal.id == data.deal_id)
        )
        deal = deal_result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Linked deal not found")

        if not data.project_name:
            data.project_name = deal.project_name
        if not data.sponsor_name and deal.developer:
            data.sponsor_name = deal.developer.name

        m = deal.metrics or {}
        ds = m.get("deal_structure", {}) or {}
        tr = m.get("target_returns", {}) or {}
        if data.preferred_return is None and ds.get("preferred_return") is not None:
            data.preferred_return = ds["preferred_return"]
        if data.projected_irr is None:
            data.projected_irr = tr.get("net_irr") or tr.get("target_irr")
        if data.projected_equity_multiple is None:
            data.projected_equity_multiple = tr.get("net_equity_multiple") or tr.get("target_equity_multiple")
        if not data.investment_class and ds.get("investment_class"):
            data.investment_class = ds["investment_class"]
        if data.hold_period_years is None and ds.get("hold_period_years") is not None:
            data.hold_period_years = ds["hold_period_years"]

    inv = Investment(**data.model_dump())
    db.add(inv)
    await db.commit()
    await db.refresh(inv)

    return {"id": inv.id, "message": "Investment created"}


@router.get("/{investment_id}")
async def get_investment(investment_id: int, db: AsyncSession = Depends(get_db)):
    """Get single investment with distributions."""
    result = await db.execute(
        select(Investment)
        .options(selectinload(Investment.distributions), selectinload(Investment.deal))
        .where(Investment.id == investment_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")

    return _serialize_investment(inv)


@router.put("/{investment_id}")
async def update_investment(investment_id: int, data: InvestmentUpdate, db: AsyncSession = Depends(get_db)):
    """Update an investment."""
    result = await db.execute(select(Investment).where(Investment.id == investment_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(inv, field, value)

    await db.commit()
    return {"message": "Investment updated"}


@router.delete("/{investment_id}")
async def delete_investment(investment_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an investment."""
    result = await db.execute(select(Investment).where(Investment.id == investment_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")

    await db.delete(inv)
    await db.commit()
    return {"message": "Investment deleted"}


# ===== Distribution Endpoints =====

@router.post("/{investment_id}/distributions")
async def add_distribution(investment_id: int, data: DistributionCreate, db: AsyncSession = Depends(get_db)):
    """Add a distribution to an investment."""
    result = await db.execute(select(Investment).where(Investment.id == investment_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")

    dist = Distribution(investment_id=investment_id, **data.model_dump())
    db.add(dist)
    await db.commit()
    await db.refresh(dist)

    return {"id": dist.id, "message": "Distribution added"}


@router.delete("/{investment_id}/distributions/{dist_id}")
async def delete_distribution(investment_id: int, dist_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a distribution."""
    result = await db.execute(
        select(Distribution).where(Distribution.id == dist_id, Distribution.investment_id == investment_id)
    )
    dist = result.scalar_one_or_none()
    if not dist:
        raise HTTPException(status_code=404, detail="Distribution not found")

    await db.delete(dist)
    await db.commit()
    return {"message": "Distribution deleted"}


# ===== Helpers =====

def _exposure_rows(values: dict[str, float], total: float) -> list[dict]:
    """Return sorted allocation rows with percentage of invested capital."""
    rows = []
    for name, amount in values.items():
        rows.append({
            "name": name,
            "amount": amount,
            "percent": round((amount / total) * 100, 1) if total > 0 else 0,
        })
    return sorted(rows, key=lambda row: row["amount"], reverse=True)


def _serialize_investment(inv: Investment) -> dict:
    """Serialize investment with calculated metrics."""
    total_distributions = sum(d.amount for d in inv.distributions) if inv.distributions else 0
    exit_amount = inv.exit_amount or 0
    total_returned = total_distributions + exit_amount
    invested = inv.amount_invested or 0

    # Actual equity multiple
    actual_multiple = round(total_returned / invested, 2) if invested > 0 else 0

    # Actual cash-on-cash (annual distributions / invested)
    actual_coc = 0
    if invested > 0 and inv.investment_date and inv.distributions:
        from datetime import date as date_type
        today = inv.exit_date or date_type.today()
        years = max((today - inv.investment_date).days / 365.25, 0.1)
        actual_coc = round((total_distributions / years) / invested * 100, 1)

    return {
        "id": inv.id,
        "deal_id": inv.deal_id,
        "deal_name": inv.deal.project_name if inv.deal else None,
        "project_name": inv.project_name,
        "sponsor_name": inv.sponsor_name,
        "investment_date": inv.investment_date.isoformat() if inv.investment_date else None,
        "amount_invested": inv.amount_invested,
        "shares": inv.shares,
        "investment_class": inv.investment_class,
        "preferred_return": inv.preferred_return,
        "projected_irr": inv.projected_irr,
        "projected_equity_multiple": inv.projected_equity_multiple,
        "hold_period_years": inv.hold_period_years,
        "status": inv.status,
        "exit_date": inv.exit_date.isoformat() if inv.exit_date else None,
        "exit_amount": inv.exit_amount,
        "notes": inv.notes,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        # Calculated
        "total_distributions": total_distributions,
        "total_returned": total_returned,
        "actual_multiple": actual_multiple,
        "actual_coc": actual_coc,
        "net_profit": total_returned - invested,
        "distributions": [
            {
                "id": d.id,
                "date": d.date.isoformat() if d.date else None,
                "amount": d.amount,
                "dist_type": d.dist_type,
                "period": d.period,
                "notes": d.notes,
            }
            for d in sorted(inv.distributions, key=lambda x: x.date or date.min)
        ] if inv.distributions else [],
    }
