from datetime import UTC
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class OpportunityType(Enum):
    JOB = "JOB"
    INTERNSHIP = "INTERNSHIP"
    GRADUATE = "GRADUATE"
    EVENT = "EVENT"
    COMPETITION = "COMPETITION"


class OpportunityStatus(Enum):
    OPEN = "OPEN"
    UPDATED = "UPDATED"
    CLOSED = "CLOSED"


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"))
    provider_id: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[OpportunityType] = mapped_column(SQLEnum(OpportunityType))
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String, unique=True)
    visa: Mapped[str | None] = mapped_column(String, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String, nullable=True)
    hash: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[OpportunityStatus] = mapped_column(
        SQLEnum(OpportunityStatus),
        default=OpportunityStatus.OPEN,
    )
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_modified: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class OpportunityHistory(Base):
    __tablename__ = "opportunity_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id"),
        nullable=False,
        index=True,
    )
    event: Mapped[str] = mapped_column(String, nullable=False)
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
