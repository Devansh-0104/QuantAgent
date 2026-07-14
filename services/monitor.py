import hashlib
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal

from models.page import Page
from models.page import PageType
from models.opportunity import Opportunity


class Monitor:

    def __init__(self):

        self.db = SessionLocal()

    # =====================================================
    # Page Registry
    # =====================================================

    def register_page(
        self,
        company_id: int,
        page_type: PageType,
        url: str,
    ) -> Page:

        page = (
            self.db.query(Page)
            .filter(Page.url == url)
            .first()
        )

        if page:
            return page

        page = Page(
            company_id=company_id,
            page_type=page_type,
            url=url
        )

        self.db.add(page)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = (
                self.db.query(Page)
                .filter(Page.url == url)
                .first()
            )
            if existing is None:
                raise
            return existing

        self.db.refresh(page)

        return page

    def get_pages(self, company_id):

        return (
            self.db.query(Page)
            .filter(Page.company_id == company_id)
            .all()
        )

    def get_page(self, page_id):

        return (
            self.db.query(Page)
            .filter(Page.id == page_id)
            .first()
        )

    # =====================================================
    # Opportunity Repository
    # =====================================================

    def compute_hash(self, item):

        text = "|".join([
            item["title"],
            item["location"],
            item["url"]
        ])

        return hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()

    def save_opportunities(self, opportunities):

        added = 0

        for item in opportunities:

            item_hash = self.compute_hash(item)

            existing = (
                self.db.query(Opportunity)
                .filter(Opportunity.url == item["url"])
                .first()
            )

            if existing:

                existing.last_seen = datetime.utcnow()

                existing.hash = item_hash

                # Keep fields updated if they change
                existing.title = item["title"]
                existing.location = item["location"]
                existing.type = item["type"]
                existing.visa = item["visa"]
                existing.deadline = item["deadline"]

                continue

            opportunity = Opportunity(

                company_id=item["company_id"],

                page_id=item["page_id"],

                type=item["type"],

                title=item["title"],

                location=item["location"],

                url=item["url"],

                visa=item["visa"],

                deadline=item["deadline"],

                hash=item_hash,

                first_seen=datetime.utcnow(),

                last_seen=datetime.utcnow()

            )

            self.db.add(opportunity)

            added += 1

        self.db.commit()

        return added
    
    def best_pages(self, company_id):

        pages = self.get_pages(company_id)

        PRIORITY = {

            "open-roles": 100,

            "jobs": 100,

            "careers": 90,

            "career": 90,

            "intern": 85,

            "student": 80,

            "graduate": 80,

            "event": 70,

        }

        scored = []

        for page in pages:

            score = 0

            url = page.url.lower()

            for keyword, value in PRIORITY.items():

                if keyword in url:

                    score = max(score, value)

            scored.append((score, page))

        scored.sort(reverse=True, key=lambda x: x[0])

        return [page for _, page in scored]
