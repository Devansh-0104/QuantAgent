from datetime import UTC
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Company(Base):

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )

    website: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    ats: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String,
        default="NEW",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )
