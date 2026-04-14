from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, JSON, Date
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, date
from app.database import Base


class Developer(Base):
    __tablename__ = "developers"

    id = Column(Integer, primary_key=True, index=True)
    # Soft-delete timestamp. When non-null the row is hidden from list/get
    # endpoints but remains in the DB for ~30 days so users can Undo.
    deleted_at = Column(DateTime, nullable=True)
    name = Column(String(255), nullable=False)
    contact_name = Column(String(255), default="")
    contact_email = Column(String(255), default="")
    phone = Column(String(50), default="")
    track_record = Column(Text, default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    deals = relationship("Deal", back_populates="developer", cascade="all, delete-orphan")


class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, index=True)
    deleted_at = Column(DateTime, nullable=True)
    developer_id = Column(Integer, ForeignKey("developers.id"), nullable=True)
    project_name = Column(String(500), nullable=False)
    location = Column(String(500), default="")
    city = Column(String(255), default="")
    state = Column(String(100), default="")
    property_type = Column(String(100), default="multifamily")
    status = Column(String(50), default="reviewing")
    metrics = Column(JSON, default=dict)
    scores = Column(JSON, default=dict)
    notes = Column(Text, default="")
    # Location intelligence — cached so we don't re-hit Nominatim/Overpass
    # on every page load. `lat`/`lng` are resolved once (or user-placed),
    # `location_data` caches the last Overpass + HUD FMR bundle with a
    # `fetched_at` timestamp for 7-day staleness checks.
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    location_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    developer = relationship("Developer", back_populates="deals")
    documents = relationship("DealDocument", back_populates="deal", cascade="all, delete-orphan")
    chats = relationship("DealChat", back_populates="deal", cascade="all, delete-orphan")
    investments = relationship("Investment", back_populates="deal", cascade="all, delete-orphan")


class DealDocument(Base):
    __tablename__ = "deal_documents"

    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=False)
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    doc_type = Column(String(50), default="other")
    extracted_text = Column(Text, default="")
    page_count = Column(Integer, default=0)
    upload_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # Per-page extraction diagnostics (source: text|ocr|empty, chars per page).
    # Surfaces OCR failures to the UI so critical missing data is never silent.
    extraction_quality = Column(JSON, default=dict)

    deal = relationship("Deal", back_populates="documents")


class DealChat(Base):
    __tablename__ = "deal_chats"

    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    deal = relationship("Deal", back_populates="chats")


class Investment(Base):
    __tablename__ = "investments"

    id = Column(Integer, primary_key=True, index=True)
    deleted_at = Column(DateTime, nullable=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True)
    project_name = Column(String(500), default="")  # Can track non-deal investments too
    sponsor_name = Column(String(255), default="")
    investment_date = Column(Date, nullable=True)
    amount_invested = Column(Float, default=0)
    shares = Column(Float, default=0)
    investment_class = Column(String(100), default="")  # Class A, Class B, LP, etc.
    preferred_return = Column(Float, nullable=True)  # %
    projected_irr = Column(Float, nullable=True)
    projected_equity_multiple = Column(Float, nullable=True)
    hold_period_years = Column(Float, nullable=True)
    status = Column(String(50), default="active")  # active, exited, defaulted, pending
    exit_date = Column(Date, nullable=True)
    exit_amount = Column(Float, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    deal = relationship("Deal", back_populates="investments")
    distributions = relationship("Distribution", back_populates="investment", cascade="all, delete-orphan")


class Distribution(Base):
    __tablename__ = "distributions"

    id = Column(Integer, primary_key=True, index=True)
    investment_id = Column(Integer, ForeignKey("investments.id"), nullable=False)
    date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    dist_type = Column(String(50), default="cash_flow")  # cash_flow, return_of_capital, sale_proceeds, refinance
    period = Column(String(50), default="")  # Q1 2025, March 2025, etc.
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    investment = relationship("Investment", back_populates="distributions")
