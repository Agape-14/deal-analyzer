import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import date
from app.database import get_db
from app.models import Investment, Distribution, Deal
from app.services.portfolio_analytics import (
    investment_performance,
    portfolio_analytics,
)

router = APIRouter()


# ===== Pydantic Models =====

# Bounds chosen to allow any plausible real-estate deal, while rejecting the
# kind of off-by-3-zeros typos that silently corrupt the portfolio page.
INVESTMENT_STATUSES = {"active", "exited", "defaulted", "pending"}


class InvestmentCreate(BaseModel):
    deal_id: Optional[int] = Field(None, ge=1)
    project_name: str = Field("", max_length=255)
    sponsor_name: str = Field("", max_length=255)
    investment_date: Optional[date] = None
    amount_invested: float = Field(0, ge=0, le=1_000_000_000)   # $1B cap
    shares: float = Field(0, ge=0)
    investment_class: str = Field("", max_length=64)
    preferred_return: Optional[float] = Field(None, ge=0, le=100)
    projected_irr: Optional[float] = Field(None, ge=-100, le=300)
    projected_equity_multiple: Optional[float] = Field(None, ge=0, le=20)
    hold_period_years: Optional[float] = Field(None, ge=0, le=50)
    status: str = "active"
    # Allow backfilling already-exited investments in a single POST
    exit_date: Optional[date] = None
    exit_amount: Optional[float] = Field(None, ge=0, le=10_000_000_000)
    notes: str = Field("", max_length=10000)

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v):
        if v is None or v == "":
            return "active"
        if v not in INVESTMENT_STATUSES:
            raise ValueError(f"status must be one of {sorted(INVESTMENT_STATUSES)}")
        return v


class InvestmentUpdate(BaseModel):
    project_name: Optional[str] = Field(None, max_length=255)
    sponsor_name: Optional[str] = Field(None, max_length=255)
    investment_date: Optional[date] = None
    amount_invested: Optional[float] = Field(None, ge=0, le=1_000_000_000)
    shares: Optional[float] = Field(None, ge=0)
    investment_class: Optional[str] = Field(None, max_length=64)
    preferred_return: Optional[float] = Field(None, ge=0, le=100)
    projected_irr: Optional[float] = Field(None, ge=-100, le=300)
    projected_equity_multiple: Optional[float] = Field(None, ge=0, le=20)
    hold_period_years: Optional[float] = Field(None, ge=0, le=50)
    status: Optional[str] = None
    exit_date: Optional[date] = None
    exit_amount: Optional[float] = Field(None, ge=0, le=10_000_000_000)
    notes: Optional[str] = Field(None, max_length=10000)

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v):
        if v is None:
            return v
        if v not in INVESTMENT_STATUSES:
            raise ValueError(f"status must be one of {sorted(INVESTMENT_STATUSES)}")
        return v


class DistributionCreate(BaseModel):
    date: date
    amount: float = Field(..., gt=0, le=1_000_000_000)   # must be positive
    dist_type: str = Field("cash_flow", max_length=64)
    period: str = Field("", max_length=64)
    notes: str = Field("", max_length=2000)


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
        .options(selectinload(Investment.distributions))
    )
    investments = result.scalars().all()

    total_invested = 0
    total_distributions = 0
    total_exit_proceeds = 0
    active_count = 0
    exited_count = 0

    for inv in investments:
        total_invested += inv.amount_invested or 0
        for d in inv.distributions:
            total_distributions += d.amount or 0
        if inv.status == "active":
            active_count += 1
        elif inv.status == "exited":
            exited_count += 1
            total_exit_proceeds += inv.exit_amount or 0

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
    }


@router.get("/portfolio/analytics")
async def portfolio_analytics_endpoint(db: AsyncSession = Depends(get_db)):
    """Portfolio-wide analytics: IRR, multiples, timeseries, concentration."""
    result = await db.execute(
        select(Investment).options(selectinload(Investment.distributions))
    )
    return portfolio_analytics(result.scalars().all())


@router.get("/{investment_id}/performance")
async def investment_performance_endpoint(
    investment_id: int, db: AsyncSession = Depends(get_db)
):
    """Performance metrics & cashflow timeseries for a single investment."""
    result = await db.execute(
        select(Investment)
        .options(selectinload(Investment.distributions))
        .where(Investment.id == investment_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")
    return investment_performance(inv)


@router.post("/")
async def create_investment(data: InvestmentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new investment."""
    # If deal_id provided, auto-populate from deal
    if data.deal_id:
        deal_result = await db.execute(select(Deal).where(Deal.id == data.deal_id))
        deal = deal_result.scalar_one_or_none()
        if deal:
            if not data.project_name:
                data.project_name = deal.project_name
            if not data.sponsor_name and deal.developer:
                deal_result2 = await db.execute(
                    select(Deal).options(selectinload(Deal.developer)).where(Deal.id == data.deal_id)
                )
                deal2 = deal_result2.scalar_one_or_none()
                if deal2 and deal2.developer:
                    data.sponsor_name = deal2.developer.name
            # Pull from metrics
            m = deal.metrics or {}
            ds = m.get('deal_structure', {}) or {}
            tr = m.get('target_returns', {}) or {}
            if not data.preferred_return and ds.get('preferred_return'):
                data.preferred_return = ds['preferred_return']
            if not data.projected_irr:
                data.projected_irr = tr.get('net_irr') or tr.get('target_irr')
            if not data.projected_equity_multiple:
                data.projected_equity_multiple = tr.get('net_equity_multiple') or tr.get('target_equity_multiple')
            if not data.investment_class and ds.get('investment_class'):
                data.investment_class = ds['investment_class']
            if not data.hold_period_years and ds.get('hold_period_years'):
                data.hold_period_years = ds['hold_period_years']

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
