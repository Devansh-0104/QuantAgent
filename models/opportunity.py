from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String

from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.database import Base


class OpportunityType(Enum):

    JOB = "JOB"

    INTERNSHIP = "INTERNSHIP"

    GRADUATE = "GRADUATE"

    EVENT = "EVENT"

    COMPETITION = "COMPETITION"


class Opportunity(Base):

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id")
    )

    page_id: Mapped[int] = mapped_column(
        ForeignKey("pages.id")
    )

    type: Mapped[OpportunityType] = mapped_column(
        SQLEnum(OpportunityType)
    )

    title: Mapped[str] = mapped_column(
        String
    )

    location: Mapped[str | None] = mapped_column(
        String,
        nullable=True
    )

    url: Mapped[str] = mapped_column(
        String,
        unique=True
    )

    visa: Mapped[str | None] = mapped_column(
        String,
        nullable=True
    )

    deadline: Mapped[str | None] = mapped_column(
        String,
        nullable=True
    )

    hash: Mapped[str | None] = mapped_column(
        String,
        nullable=True
    )

    first_seen: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    last_seen: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )