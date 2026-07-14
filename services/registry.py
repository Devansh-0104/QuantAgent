import logging
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from models.company import Company


logger = logging.getLogger(__name__)


class Registry:

    def __init__(self):
        self.db = SessionLocal()

    def watch(self, company_name: str, website: str | None = None) -> bool:
        normalized_name = company_name.strip()
        if not normalized_name:
            raise ValueError("Company name cannot be empty")

        normalized_website = self._validate_website(website)
        company = (
            self.db.query(Company)
            .filter(func.lower(Company.name) == normalized_name.casefold())
            .first()
        )

        if company:
            if normalized_website and company.website != normalized_website:
                company.website = normalized_website
                try:
                    self.db.commit()
                except SQLAlchemyError:
                    self.db.rollback()
                    raise
            return False

        company = Company(name=normalized_name, website=normalized_website)
        self.db.add(company)
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise
        return True

    def list(self):
        return (
            self.db.query(Company)
            .order_by(Company.name)
            .all()
        )

    def update_website(self, company_name: str, website: str) -> bool:
        company = (
            self.db.query(Company)
            .filter(Company.name == company_name)
            .first()
        )

        if company is None:
            return False

        company.website = website
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Unable to update website for %s", company_name)
            return False

        return True

    def get_company(self, name: str) -> Company | None:
        return (
            self.db.query(Company)
            .filter(Company.name == name)
            .first()
        )
    
    def all_companies(self):
        return self.db.query(Company).all()

    @staticmethod
    def _validate_website(website: str | None) -> str | None:
        if website is None:
            return None

        normalized = website.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Website must be an absolute HTTP or HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("Website must not contain embedded credentials")
        return normalized
