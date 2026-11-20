import os
import hashlib
import json
from copy import deepcopy
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import date, datetime, timezone
from app.database import get_db
from app.models import Investment, Distribution, Deal, Developer
from app.services.portfolio_analytics import (
    investment_performance,
    portfolio_analytics,
    active_distributions,
)
from app.services.investment_forecasts import TERM_FIELDS, accepted_forecast, record_term_overrides

router = APIRouter()


# ===== Pydantic Models =====

# Bounds chosen to allow any plausible real-estate deal, while rejecting the
# kind of off-by-3-zeros typos that silently corrupt the portfolio page.
INVESTMENT_STATUSES = {"active", "exited", "defaulted", "pending"}


class InvestmentCreate(BaseModel):
    expected_analysis_version: Optional[int] = Field(None, exclude=True)
    expected_analysis_input_hash: Optional[str] = Field(None, exclude=True)
    terms_override_reason: str = Field("", max_length=2000, exclude=True)
    deal_id: Optional[int] = Field(None, ge=1)
    developer_id: Optional[int] = Field(None, ge=1)
    project_name: str = Field("", max_length=255)
    sponsor_name: str = Field("", max_length=255)
    investment_date: Optional[date] = None
    amount_invested: float = Field(0, ge=0, le=1_000_000_000)   # $1B cap
    shares: float = Field(0, ge=0)
    investment_class: str = Field("", max_length=64)
    preferred_return: Optional[float] = Field(None, ge=0, le=100)
    projected_irr: Optional[float] = Field(None, ge=-100, le=300)
    projected_equity_multiple: Optional[float] = Field(None, ge=0, le=20)
    projected_cash_on_cash: Optional[float] = Field(None, ge=-100, le=300)
    hold_period_years: Optional[float] = Field(None, ge=0, le=50)
    status: str = "active"
    # Allow backfilling already-exited investments in a single POST
    exit_date: Optional[date] = None
    exit_amount: Optional[float] = Field(None, ge=0, le=10_000_000_000)
    residual_value: Optional[float] = Field(None, ge=0, le=10_000_000_000)
    valuation_date: Optional[date] = None
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
    terms_override_reason: str = Field("", max_length=2000, exclude=True)
    confirmed_class_terms: bool = Field(False, exclude=True)
    developer_id: Optional[int] = Field(None, ge=1)
    project_name: Optional[str] = Field(None, max_length=255)
    sponsor_name: Optional[str] = Field(None, max_length=255)
    investment_date: Optional[date] = None
    amount_invested: Optional[float] = Field(None, ge=0, le=1_000_000_000)
    shares: Optional[float] = Field(None, ge=0)
    investment_class: Optional[str] = Field(None, max_length=64)
    preferred_return: Optional[float] = Field(None, ge=0, le=100)
    projected_irr: Optional[float] = Field(None, ge=-100, le=300)
    projected_equity_multiple: Optional[float] = Field(None, ge=0, le=20)
    projected_cash_on_cash: Optional[float] = Field(None, ge=-100, le=300)
    hold_period_years: Optional[float] = Field(None, ge=0, le=50)
    status: Optional[str] = None
    exit_date: Optional[date] = None
    exit_amount: Optional[float] = Field(None, ge=0, le=10_000_000_000)
    residual_value: Optional[float] = Field(None, ge=0, le=10_000_000_000)
    valuation_date: Optional[date] = None
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
    request_id: Optional[str] = Field(None, min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class DistributionUpdate(BaseModel):
    date: date
    amount: float = Field(..., gt=0, le=1_000_000_000)
    dist_type: str = Field("cash_flow", max_length=64)
    period: str = Field("", max_length=64)
    notes: str = Field("", max_length=2000)
    expected_revision: Optional[int] = Field(None, ge=1, exclude=True)


class DistributionRestore(BaseModel):
    expected_revision: Optional[int] = Field(None, ge=1)


# ===== Investment Endpoints =====

@router.get("", include_in_schema=False)
@router.get("/")
async def list_investments(
    trash: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List all investments with distributions."""
    q = (
        select(Investment)
        .options(selectinload(Investment.distributions), selectinload(Investment.deal))
        .order_by(Investment.created_at.desc())
    )
    q = q.where(Investment.deleted_at.is_not(None) if trash else Investment.deleted_at.is_(None))
    result = await db.execute(q)
    investments = result.scalars().all()

    return [_serialize_investment(inv) for inv in investments]


@router.get("/portfolio")
async def portfolio_summary(db: AsyncSession = Depends(get_db)):
    """Get portfolio-level summary stats."""
    result = await db.execute(
        select(Investment)
        .where(Investment.deleted_at.is_(None))
        .options(selectinload(Investment.distributions))
    )
    investments = result.scalars().all()

    return {
        **portfolio_analytics(investments)["summary"],
        "active_investments": sum(inv.status == "active" for inv in investments),
        "exited_investments": sum(inv.status == "exited" for inv in investments),
        "total_investments": len(investments),
    }


@router.get("/portfolio/analytics")
async def portfolio_analytics_endpoint(db: AsyncSession = Depends(get_db)):
    """Portfolio-wide analytics: IRR, multiples, timeseries, concentration."""
    result = await db.execute(
        select(Investment)
        .where(Investment.deleted_at.is_(None))
        .options(selectinload(Investment.distributions))
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
    if not inv or inv.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Investment not found")
    return investment_performance(inv)


@router.post("", include_in_schema=False)
@router.post("/")
async def create_investment(data: InvestmentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new investment."""
    source_metadata = {}
    supplied_terms = {key: getattr(data, key) for key in TERM_FIELDS if key in data.model_fields_set}
    if not supplied_terms.get("investment_class"):
        supplied_terms.pop("investment_class", None)
    # If deal_id provided, auto-populate from deal
    if data.deal_id:
        deal_result = await db.execute(select(Deal).options(selectinload(Deal.developer), selectinload(Deal.documents)).where(Deal.id == data.deal_id, Deal.deleted_at.is_(None)))
        deal = deal_result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Selected deal is unavailable")
        if deal:
            data.developer_id = deal.developer_id
            if not data.project_name:
                data.project_name = deal.project_name
            if not data.sponsor_name and deal.developer:
                data.sponsor_name = deal.developer.name
            # Pull from metrics
            from app.services.analysis import analysis_for_deal
            analysis = analysis_for_deal(deal)
            if ((data.expected_analysis_version is not None and data.expected_analysis_version != analysis["version"]) or
                    (data.expected_analysis_input_hash is not None and data.expected_analysis_input_hash != analysis["input_hash"])):
                raise HTTPException(409, "Accepted deal terms changed. Re-select the deal to review the current revision before saving.")
            source_metadata = {"source_analysis_version": analysis["version"], "source_analysis_input_hash": analysis["input_hash"],
                "terms_context": {key: analysis["facts"][path]["identity"] for key in ("target_irr", "target_equity_multiple", "cash_on_cash")
                                  if (path := analysis["returns"].get(key + "_path")) in analysis["facts"]}}
            snapshot = accepted_forecast(deal, analysis)
            source_metadata["forecast_snapshot"] = snapshot
            defaults = dict(snapshot["terms"])
            if data.investment_class and data.investment_class != defaults.get("investment_class"):
                # An explicit different class never inherits another class's terms.
                defaults = {}
                source_metadata["terms_context"] = {}
            for field, value in defaults.items():
                if field not in supplied_terms and value is not None:
                    setattr(data, field, value)

    validate_position_dates(data.investment_date, data.status, data.exit_date)
    validate_valuation(data.residual_value, data.valuation_date, data.investment_date)
    sponsor = await resolve_sponsor(db, data.developer_id, data.sponsor_name)
    if sponsor:
        data.developer_id, data.sponsor_name = sponsor.id, sponsor.name
    inv = Investment(**data.model_dump(), **source_metadata)
    baseline = (source_metadata.get("forecast_snapshot") or {}).get("terms") or {}
    contexts = deepcopy(inv.terms_context or {})
    for field, key in {"projected_irr": "target_irr", "projected_equity_multiple": "target_equity_multiple", "projected_cash_on_cash": "cash_on_cash"}.items():
        if field in supplied_terms and supplied_terms[field] != baseline.get(field):
            contexts.pop(key, None)
    inv.terms_context = contexts or None
    overridden_class = bool(baseline and inv.investment_class != baseline.get("investment_class"))
    record_term_overrides(inv, {key: (baseline.get(key), value) for key, value in supplied_terms.items()}, data.terms_override_reason,
                          force_fields=supplied_terms.keys() if overridden_class else ())
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
    if not inv or inv.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Investment not found")

    return _serialize_investment(inv)


@router.put("/{investment_id}")
async def update_investment(investment_id: int, data: InvestmentUpdate, db: AsyncSession = Depends(get_db)):
    """Update an investment."""
    result = await db.execute(select(Investment).options(selectinload(Investment.distributions)).where(Investment.id == investment_id))
    inv = result.scalar_one_or_none()
    if not inv or inv.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Investment not found")

    changes = data.model_dump(exclude_unset=True)
    old_terms = {field: getattr(inv, field) for field in TERM_FIELDS}
    if "investment_class" in changes and changes["investment_class"] != inv.investment_class:
        # Sending an unchanged default with a new class is not an affirmative
        # review of that class's return. Clear it until explicitly re-entered.
        for field in TERM_FIELDS:
            if field != "investment_class" and (field not in changes or (changes[field] == old_terms[field] and not data.confirmed_class_terms)):
                changes[field] = None
    for field, value in changes.items():
        setattr(inv, field, value)

    if {"investment_date", "status", "exit_date"} & changes.keys():
        validate_position_dates(inv.investment_date, inv.status, inv.exit_date)
        for dist in active_distributions(inv):
            validate_distribution_date(inv, dist.date)
    validate_valuation(inv.residual_value, inv.valuation_date, inv.investment_date)
    if inv.valuation_date and any(d.date and d.date > inv.valuation_date for d in active_distributions(inv)):
        raise HTTPException(422, "Valuation date must include all recorded distributions. Update or clear the valuation.")
    if "developer_id" in data.model_fields_set or (not inv.developer_id and "sponsor_name" in data.model_fields_set):
        sponsor = await resolve_sponsor(db, inv.developer_id, inv.sponsor_name)
        if sponsor:
            inv.developer_id, inv.sponsor_name = sponsor.id, sponsor.name

    reaffirmed = {field for field in TERM_FIELDS if field in changes and changes[field] is not None} if data.confirmed_class_terms and old_terms["investment_class"] != inv.investment_class else set()
    record_term_overrides(inv, {field: (old_terms[field], getattr(inv, field)) for field in TERM_FIELDS}, data.terms_override_reason, force_fields=reaffirmed)
    context_keys = {"projected_irr": "target_irr", "projected_equity_multiple": "target_equity_multiple", "projected_cash_on_cash": "cash_on_cash"}
    contexts = deepcopy(inv.terms_context or {})
    if old_terms["investment_class"] != inv.investment_class:
        contexts = {}
    else:
        for field, key in context_keys.items():
            if old_terms[field] != getattr(inv, field):
                contexts.pop(key, None)
    inv.terms_context = contexts or None
    await db.commit()
    return {"message": "Investment updated"}


@router.delete("/{investment_id}")
async def delete_investment(investment_id: int, db: AsyncSession = Depends(get_db)):
    """Soft-delete. Follow up with `/restore` or `/purge` as needed."""
    result = await db.execute(select(Investment).where(Investment.id == investment_id))
    inv = result.scalar_one_or_none()
    if not inv or inv.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Investment not found")
    inv.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Investment moved to trash", "id": investment_id}


@router.post("/{investment_id}/restore")
async def restore_investment(investment_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Investment).where(Investment.id == investment_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")
    inv.deleted_at = None
    await db.commit()
    return {"message": "Restored", "id": investment_id}


@router.delete("/{investment_id}/purge")
async def purge_investment(investment_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Investment).where(Investment.id == investment_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")
    if inv.deleted_at is None:
        raise HTTPException(
            status_code=409,
            detail="Investment must be in the trash before it can be purged.",
        )
    await db.delete(inv)
    await db.commit()
    return {"message": "Purged"}


# ===== Distribution Endpoints =====

@router.post("/{investment_id}/distributions")
async def add_distribution(investment_id: int, data: DistributionCreate, db: AsyncSession = Depends(get_db)):
    """Add a distribution to an investment."""
    inv = await ledger_investment(db, investment_id)
    payload = data.model_dump(exclude={"request_id"})
    fingerprint = hashlib.sha256(json.dumps(data.model_dump(mode="json", exclude={"request_id"}), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if data.request_id:
        existing = (await db.execute(select(Distribution).where(Distribution.investment_id == investment_id, Distribution.request_id == data.request_id))).scalar_one_or_none()
        if existing:
            return replay_distribution(existing, fingerprint)
    validate_distribution_date(inv, data.date)
    dist = Distribution(investment_id=investment_id, **payload, request_id=data.request_id, request_fingerprint=fingerprint)
    db.add(dist)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if not data.request_id:
            raise
        existing = (await db.execute(select(Distribution).where(Distribution.investment_id == investment_id, Distribution.request_id == data.request_id))).scalar_one_or_none()
        if not existing:
            raise
        return replay_distribution(existing, fingerprint)
    await db.refresh(dist)
    return {"id": dist.id, "revision": dist.revision, "message": "Distribution added"}


@router.put("/{investment_id}/distributions/{dist_id}")
async def update_distribution(investment_id: int, dist_id: int, data: DistributionUpdate, db: AsyncSession = Depends(get_db)):
    inv = await ledger_investment(db, investment_id)
    dist = await ledger_distribution(db, investment_id, dist_id)
    if dist.deleted_at is not None:
        raise HTTPException(409, "Restore this distribution before editing it.")
    validate_distribution_date(inv, data.date)
    return await change_distribution(db, dist, data.model_dump(), data.expected_revision, "edited")


@router.delete("/{investment_id}/distributions/{dist_id}")
async def delete_distribution(investment_id: int, dist_id: int, expected_revision: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    """Soft-remove cash flow, keeping its audit and an explicit undo route."""
    await ledger_investment(db, investment_id)
    dist = await ledger_distribution(db, investment_id, dist_id)
    if dist.deleted_at is not None:
        if expected_revision is not None and expected_revision != dist.revision:
            raise HTTPException(409, "This distribution changed. Refresh the ledger before continuing.")
        return {"id": dist.id, "revision": dist.revision, "message": "Distribution removed"}
    return await change_distribution(db, dist, {"deleted_at": datetime.now(timezone.utc)}, expected_revision, "removed")


@router.post("/{investment_id}/distributions/{dist_id}/restore")
async def restore_distribution(investment_id: int, dist_id: int, data: Optional[DistributionRestore] = None, db: AsyncSession = Depends(get_db)):
    inv = await ledger_investment(db, investment_id)
    dist = await ledger_distribution(db, investment_id, dist_id)
    expected = data.expected_revision if data else None
    if dist.deleted_at is None:
        if expected is not None and expected != dist.revision:
            raise HTTPException(409, "This distribution changed. Refresh the ledger before continuing.")
        return {"id": dist.id, "revision": dist.revision, "message": "Distribution restored"}
    validate_distribution_date(inv, dist.date)
    return await change_distribution(db, dist, {"deleted_at": None}, expected, "restored")


# ===== Helpers =====

async def ledger_investment(db, investment_id):
    inv = (await db.execute(select(Investment).where(Investment.id == investment_id))).scalar_one_or_none()
    if not inv or inv.deleted_at is not None:
        raise HTTPException(404, "Investment not found. Restore an archived investment before changing its ledger.")
    return inv


async def ledger_distribution(db, investment_id, dist_id):
    dist = (await db.execute(select(Distribution).where(Distribution.id == dist_id, Distribution.investment_id == investment_id))).scalar_one_or_none()
    if not dist:
        raise HTTPException(404, "Distribution not found")
    return dist


def replay_distribution(dist, fingerprint):
    if dist.request_fingerprint != fingerprint:
        raise HTTPException(409, "This payment request was already used with different details. Start a new payment.")
    return {"id": dist.id, "revision": dist.revision, "replayed": True,
            "removed": dist.deleted_at is not None, "message": "Distribution already recorded"}


def distribution_values(dist):
    return {"date": dist.date.isoformat() if dist.date else None, "amount": dist.amount,
            "dist_type": dist.dist_type, "period": dist.period, "notes": dist.notes,
            "deleted_at": dist.deleted_at.isoformat() if dist.deleted_at else None}


async def change_distribution(db, dist, values, expected_revision, action):
    revision = dist.revision or 1
    if expected_revision is not None and expected_revision != revision:
        raise HTTPException(409, "This distribution changed. Refresh the ledger before continuing.")
    history = deepcopy(dist.history or [])
    history.append({"action": action, "revision": revision + 1, "previous_revision": revision,
                    "recorded_at": datetime.now(timezone.utc).isoformat(), "previous": distribution_values(dist)})
    result = await db.execute(update(Distribution).where(Distribution.id == dist.id, Distribution.revision == revision)
                              .values(**values, revision=revision + 1, history=history).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "This distribution changed. Refresh the ledger before continuing.")
    dist_id = dist.id
    await db.commit()
    return {"id": dist_id, "revision": revision + 1, "message": f"Distribution {action}"}


def validate_position_dates(investment_date, status, exit_date):
    if investment_date and investment_date > date.today() and status != "pending":
        raise HTTPException(422, "A completed investment date cannot be in the future. Use pending for a planned investment.")
    if exit_date and (exit_date > date.today() or (investment_date and exit_date < investment_date)):
        raise HTTPException(422, "Exit date must be on or after investment and no later than today.")
    if status == "exited" and not exit_date:
        raise HTTPException(422, "An exited investment needs its actual exit date.")


def validate_distribution_date(inv, paid_on):
    if not paid_on or paid_on > date.today():
        raise HTTPException(422, "Distribution date must be an actual payment date no later than today.")
    if inv.investment_date and paid_on < inv.investment_date:
        raise HTTPException(422, "Distribution date cannot be before the investment date.")
    if inv.status == "exited" and inv.exit_date and paid_on > inv.exit_date:
        raise HTTPException(422, "Distribution date cannot be after the recorded exit. Correct the exit date first.")


def validate_valuation(value, as_of, investment_date):
    if (value is None) != (as_of is None):
        raise HTTPException(422, "A residual value and valuation date must be supplied together, or both cleared.")
    if as_of and (as_of > date.today() or (investment_date and as_of < investment_date)):
        raise HTTPException(422, "Valuation date must be after investment and no later than today.")


async def resolve_sponsor(db, developer_id, sponsor_name):
    if developer_id:
        sponsor = await db.get(Developer, developer_id)
        if not sponsor or sponsor.deleted_at is not None:
            raise HTTPException(422, "The selected sponsor is unavailable.")
        return sponsor
    if sponsor_name and sponsor_name.strip():
        matches = (await db.execute(select(Developer).where(Developer.deleted_at.is_(None), func.lower(func.trim(Developer.name)) == sponsor_name.strip().lower()))).scalars().all()
        if len(matches) == 1:
            return matches[0]
    return None


def _serialize_investment(inv: Investment) -> dict:
    """Serialize investment with calculated metrics."""
    distributions = active_distributions(inv)
    total_distributions = sum(d.amount for d in distributions)
    performance = investment_performance(inv)
    total_returned = performance["total_returned"]
    invested = inv.amount_invested or 0
    
    # Actual equity multiple
    actual_multiple = round(total_returned / invested, 2) if invested > 0 else 0
    
    # Actual cash-on-cash (annual distributions / invested)
    actual_coc = 0
    if invested > 0 and inv.investment_date and distributions:
        today = inv.exit_date or date.today()
        years = max((today - inv.investment_date).days / 365.25, 0.1)
        actual_coc = round((total_distributions / years) / invested * 100, 1)

    return {
        "id": inv.id,
        "deal_id": inv.deal_id,
        "deal_name": inv.deal.project_name if inv.deal else None,
        "project_name": inv.project_name,
        "sponsor_name": inv.developer.name if inv.developer else inv.sponsor_name,
        "developer_id": inv.developer_id or (inv.deal.developer_id if inv.deal else None),
        "investment_date": inv.investment_date.isoformat() if inv.investment_date else None,
        "amount_invested": inv.amount_invested,
        "shares": inv.shares,
        "investment_class": inv.investment_class,
        "preferred_return": inv.preferred_return,
        "projected_irr": inv.projected_irr,
        "projected_equity_multiple": inv.projected_equity_multiple,
        "projected_cash_on_cash": inv.projected_cash_on_cash,
        "hold_period_years": inv.hold_period_years,
        "status": inv.status,
        "exit_date": inv.exit_date.isoformat() if inv.exit_date else None,
        "exit_amount": inv.exit_amount,
        "residual_value": inv.residual_value,
        "valuation_date": inv.valuation_date.isoformat() if inv.valuation_date else None,
        "source_analysis_version": inv.source_analysis_version,
        "source_analysis_input_hash": inv.source_analysis_input_hash,
        "terms_context": inv.terms_context,
        "forecast_snapshot": inv.forecast_snapshot,
        "terms_overrides": inv.terms_overrides,
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
                "revision": d.revision,
            }
            for d in sorted(distributions, key=lambda x: x.date or date.min)
        ],
        "distribution_ledger": [{"id": d.id, **distribution_values(d), "revision": d.revision,
                                 "history": d.history or []}
                                for d in sorted(inv.distributions or [], key=lambda x: (x.date or date.min, x.id))],
    }
