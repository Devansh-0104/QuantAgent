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


class PageType(Enum):
    CAREERS = "CAREERS"
    EVENTS = "EVENTS"
    STUDENTS = "STUDENTS"
    UNIVERSITY = "UNIVERSITY"
    BLOG = "BLOG"
    OTHER = "OTHER"


class Page(Base):

    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id")
    )

    page_type: Mapped[PageType] = mapped_column(
        SQLEnum(PageType)
    )

    url: Mapped[str] = mapped_column(
        String,
        unique=True
    )

    last_hash: Mapped[str | None] = mapped_column(
        String,
        nullable=True
    )

    last_checked: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )