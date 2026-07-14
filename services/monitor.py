import hashlib
import json
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from models.opportunity import Opportunity
from models.opportunity import OpportunityHistory
from models.opportunity import OpportunityStatus
from models.opportunity import utc_now
from models.page import Page
from models.page import PageType
from services.matcher import OpportunityMatch


@dataclass
class ScanResult:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    closed: int = 0
    reopened: int = 0
    new_provider_ids: set[str] = field(default_factory=set, compare=False)


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
        page = self.db.query(Page).filter(Page.url == url).first()
        if page:
            return page

        page = Page(
            company_id=company_id,
            page_type=page_type,
            url=url,
        )
        self.db.add(page)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(Page).filter(Page.url == url).first()
            if existing is None:
                raise
            return existing

        self.db.refresh(page)
        return page

    def get_pages(self, company_id: int) -> list[Page]:
        return self.db.query(Page).filter(Page.company_id == company_id).all()

    def get_page(self, page_id: int) -> Page | None:
        return self.db.query(Page).filter(Page.id == page_id).first()

    # =====================================================
    # Opportunity Repository
    # =====================================================

    def compute_hash(self, item: dict[str, object]) -> str:
        opportunity_type = item.get("type")
        if hasattr(opportunity_type, "value"):
            opportunity_type = opportunity_type.value

        content = {
            "type": opportunity_type or "",
            "title": item.get("title") or "",
            "description": item.get("description") or "",
            "location": item.get("location") or "",
            "url": item.get("url") or "",
            "visa": item.get("visa") or "",
            "deadline": item.get("deadline") or "",
        }
        serialized = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def save_opportunities(
        self,
        opportunities: list[dict[str, object]],
        page_id: int | None = None,
        scan_completed: bool = True,
    ) -> int:
        items = list(opportunities)
        resolved_page_id = page_id
        if resolved_page_id is None and items:
            candidate = items[0].get("page_id")
            if isinstance(candidate, int):
                resolved_page_id = candidate

        if resolved_page_id is None:
            return 0

        return self.reconcile_opportunities(
            resolved_page_id,
            items,
            scan_completed=scan_completed,
        ).new

    def save_matches(self, matches: list[OpportunityMatch]) -> None:
        try:
            for match in matches:
                opportunity = (
                    self.db.query(Opportunity)
                    .filter(
                        Opportunity.company_id == match.company_id,
                        Opportunity.provider_id == match.provider_id,
                    )
                    .first()
                )
                if opportunity is None:
                    raise LookupError(
                        "Unable to persist match for "
                        f"provider opportunity {match.provider_id}"
                    )

                opportunity.match_score = match.result.score
                opportunity.match_priority = match.result.priority
                opportunity.match_reason = "; ".join(match.result.reasons)

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def reconcile_opportunities(
        self,
        page_id: int,
        opportunities: list[dict[str, object]],
        scan_completed: bool = True,
    ) -> ScanResult:
        result = ScanResult()
        seen_ids: set[int] = set()
        now = utc_now()

        try:
            for item in opportunities:
                existing = self._find_opportunity(item)
                item_hash = self.compute_hash(item)

                if existing is None:
                    opportunity = self._create_opportunity(item, item_hash, now)
                    self.db.add(opportunity)
                    self.db.flush()
                    self._record_history(opportunity, "NEW", now)
                    seen_ids.add(opportunity.id)
                    result.new += 1
                    if opportunity.provider_id:
                        result.new_provider_ids.add(opportunity.provider_id)
                    continue

                seen_ids.add(existing.id)
                was_closed = existing.status == OpportunityStatus.CLOSED
                existing.last_seen = now

                if existing.hash != item_hash:
                    self._update_opportunity(existing, item, item_hash, now)
                    if was_closed:
                        existing.status = OpportunityStatus.OPEN
                        self._record_history(existing, "REOPENED", now)
                        result.reopened += 1
                    else:
                        existing.status = OpportunityStatus.UPDATED
                        self._record_history(existing, "UPDATED", now)
                        result.updated += 1
                elif was_closed:
                    existing.status = OpportunityStatus.OPEN
                    existing.last_modified = now
                    self._record_history(existing, "REOPENED", now)
                    result.reopened += 1
                else:
                    if existing.status == OpportunityStatus.UPDATED:
                        existing.status = OpportunityStatus.OPEN
                    result.unchanged += 1

            if scan_completed:
                active_query = self.db.query(Opportunity).filter(
                    Opportunity.page_id == page_id,
                    Opportunity.status != OpportunityStatus.CLOSED,
                )
                if seen_ids:
                    active_query = active_query.filter(
                        Opportunity.id.not_in(seen_ids)
                    )

                for opportunity in active_query.all():
                    opportunity.status = OpportunityStatus.CLOSED
                    opportunity.last_modified = now
                    self._record_history(opportunity, "CLOSED", now)
                    result.closed += 1

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return result

    def _find_opportunity(self, item: dict[str, object]) -> Opportunity | None:
        company_id = item.get("company_id")
        provider_id = item.get("provider_id")
        if provider_id:
            existing = (
                self.db.query(Opportunity)
                .filter(
                    Opportunity.company_id == company_id,
                    Opportunity.provider_id == str(provider_id),
                )
                .first()
            )
            if existing is not None:
                return existing

        return (
            self.db.query(Opportunity)
            .filter(Opportunity.url == item.get("url"))
            .first()
        )

    def _create_opportunity(
        self,
        item: dict[str, object],
        item_hash: str,
        now: datetime,
    ) -> Opportunity:
        return Opportunity(
            company_id=item["company_id"],
            page_id=item["page_id"],
            provider_id=str(item.get("provider_id") or "") or None,
            type=item["type"],
            title=str(item["title"]),
            description=item.get("description"),
            location=item.get("location"),
            url=str(item["url"]),
            visa=item.get("visa"),
            deadline=item.get("deadline"),
            hash=item_hash,
            status=OpportunityStatus.OPEN,
            first_seen=now,
            last_seen=now,
            last_modified=now,
        )

    def _update_opportunity(
        self,
        opportunity: Opportunity,
        item: dict[str, object],
        item_hash: str,
        now: datetime,
    ) -> None:
        opportunity.page_id = item["page_id"]
        opportunity.provider_id = str(item.get("provider_id") or "") or None
        opportunity.type = item["type"]
        opportunity.title = str(item["title"])
        opportunity.description = item.get("description")
        opportunity.location = item.get("location")
        opportunity.url = str(item["url"])
        opportunity.visa = item.get("visa")
        opportunity.deadline = item.get("deadline")
        opportunity.hash = item_hash
        opportunity.last_modified = now

    def _record_history(
        self,
        opportunity: Opportunity,
        event: str,
        now: datetime,
    ) -> None:
        snapshot = {
            "provider_id": opportunity.provider_id,
            "type": opportunity.type.value,
            "title": opportunity.title,
            "description": opportunity.description,
            "location": opportunity.location,
            "url": opportunity.url,
            "visa": opportunity.visa,
            "deadline": opportunity.deadline,
            "status": opportunity.status.value,
            "first_seen": opportunity.first_seen.isoformat(),
            "last_seen": opportunity.last_seen.isoformat(),
            "last_modified": opportunity.last_modified.isoformat(),
        }
        self.db.add(
            OpportunityHistory(
                opportunity_id=opportunity.id,
                event=event,
                snapshot=json.dumps(snapshot, sort_keys=True),
                created_at=now,
            )
        )

    def best_pages(self, company_id: int) -> list[Page]:
        pages = self.get_pages(company_id)
        priority = {
            "open-roles": 100,
            "jobs": 100,
            "careers": 90,
            "career": 90,
            "intern": 85,
            "student": 80,
            "graduate": 80,
            "event": 70,
        }

        scored: list[tuple[int, Page]] = []
        for page in pages:
            score = 0
            url = page.url.lower()
            for keyword, value in priority.items():
                if keyword in url:
                    score = max(score, value)
            scored.append((score, page))

        scored.sort(reverse=True, key=lambda item: item[0])
        return [page for _, page in scored]
