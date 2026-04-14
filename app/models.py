from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, JSON, Date
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, date
from app.database import Base


class Developer(Base):
    __tablename__ = "developers"

    id = Column(Integer, primary_key=True, index=True)
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
