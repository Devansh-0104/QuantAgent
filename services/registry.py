from app.database import SessionLocal
from models.company import Company


class Registry:

    def __init__(self):
        self.db = SessionLocal()

    def watch(self, company_name: str) -> bool:
        company = (
            self.db.query(Company)
            .filter(Company.name == company_name)
            .first()
        )

        if company:
            return False

        company = Company(name=company_name)
        self.db.add(company)
        self.db.commit()
        return True

    def list(self):
        return (
            self.db.query(Company)
            .order_by(Company.name)
            .all()
        )

    def update_website(self, company_name: str, website: str) -> None:
        company = (
            self.db.query(Company)
            .filter(Company.name == company_name)
            .first()
        )

        if company is None:
            return

        company.website = website
        self.db.commit()

    def get_company(self, name: str) -> Company | None:
        return (
            self.db.query(Company)
            .filter(Company.name == name)
            .first()
        )
    
    def all_companies(self):
        return self.db.query(Company).all()