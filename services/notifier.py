import html
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.config import EmailSettings
from app.config import load_email_settings
from app.database import SessionLocal
from models.company import Company
from models.notification import Notification
from models.notification import NotificationStatus
from models.notification import NotificationType
from models.opportunity import Opportunity
from models.opportunity import OpportunityPriority
from models.opportunity import utc_now
from scrapers.base import ATS
from scrapers.base import JobScraper
from scrapers.base import UnsupportedScraperError
from scrapers.greenhouse import GreenhouseScraper
from scrapers.lever import LeverScraper
from services.matcher import OpportunityMatch


logger = logging.getLogger(__name__)


class ScraperFactory:
    SCRAPERS: dict[ATS, type[JobScraper]] = {
        ATS.GREENHOUSE: GreenhouseScraper,
        ATS.LEVER: LeverScraper,
    }

    def get(self, ats: ATS) -> JobScraper:
        scraper_class = self.SCRAPERS.get(ats)
        if scraper_class is None:
            raise UnsupportedScraperError(f"No scraper is implemented for {ats.value}")
        return scraper_class()


class EmailTransport(Protocol):
    def send(
        self,
        sender: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> None: ...


class SMTPEmailTransport:
    def __init__(self, settings: EmailSettings) -> None:
        self.settings = settings

    def send(
        self,
        sender: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> None:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content("This notification requires an HTML-capable email client.")
        message.add_alternative(body, subtype="html")

        with smtplib.SMTP(
            self.settings.host,
            self.settings.port,
            timeout=30,
        ) as smtp:
            if self.settings.use_tls:
                smtp.starttls()
            if self.settings.username and self.settings.password:
                smtp.login(self.settings.username, self.settings.password)
            smtp.send_message(message)


@dataclass
class NotificationBatchResult:
    sent: int = 0
    skipped: int = 0
    failed: int = 0


class NotificationService:
    def __init__(
        self,
        transport: EmailTransport | None,
        sender: str | None,
        recipient: str | None,
    ) -> None:
        self.transport = transport
        self.sender = sender
        self.recipient = recipient
        self.db = SessionLocal()

    @classmethod
    def from_environment(cls) -> "NotificationService":
        settings = load_email_settings()
        if settings is None:
            return cls(transport=None, sender=None, recipient=None)
        return cls(
            transport=SMTPEmailTransport(settings),
            sender=settings.sender,
            recipient=settings.recipient,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.transport and self.sender and self.recipient)

    def send_instant_alerts(
        self,
        matches: list[OpportunityMatch],
    ) -> NotificationBatchResult:
        result = NotificationBatchResult()
        relevant = [
            match
            for match in matches
            if match.result.priority == OpportunityPriority.HIGH
        ]
        result.skipped += len(matches) - len(relevant)

        if not self.enabled:
            result.skipped += len(relevant)
            if relevant:
                logger.warning("Instant alerts are disabled: SMTP is not configured")
            return result

        for match in relevant:
            opportunity = (
                self.db.query(Opportunity)
                .filter(
                    Opportunity.company_id == match.company_id,
                    Opportunity.provider_id == match.provider_id,
                )
                .first()
            )
            if opportunity is None:
                logger.error(
                    "Unable to notify for missing provider opportunity %s",
                    match.provider_id,
                )
                result.failed += 1
                continue

            notification = self._claim_instant_notification(opportunity, match)
            if notification is None:
                result.skipped += 1
                continue

            if self._deliver(notification):
                result.sent += 1
            else:
                result.failed += 1

        return result

    def retry_failed(self, limit: int = 50) -> NotificationBatchResult:
        result = NotificationBatchResult()
        if not self.enabled:
            return result

        failed_notifications = (
            self.db.query(Notification)
            .filter(
                Notification.type == NotificationType.INSTANT,
                Notification.status == NotificationStatus.FAILED,
            )
            .order_by(Notification.created_at)
            .limit(limit)
            .all()
        )
        for notification in failed_notifications:
            if self._deliver(notification):
                result.sent += 1
            else:
                result.failed += 1
        return result

    def _claim_instant_notification(
        self,
        opportunity: Opportunity,
        match: OpportunityMatch,
    ) -> Notification | None:
        dedupe_key = f"instant:{opportunity.id}"
        existing = (
            self.db.query(Notification)
            .filter(Notification.dedupe_key == dedupe_key)
            .first()
        )
        if existing is not None:
            return existing if existing.status == NotificationStatus.FAILED else None

        company = self.db.get(Company, opportunity.company_id)
        company_name = company.name if company is not None else "Unknown company"
        subject, body = self._render_instant_email(
            opportunity,
            company_name,
            match,
        )
        notification = Notification(
            opportunity_id=opportunity.id,
            type=NotificationType.INSTANT,
            status=NotificationStatus.PENDING,
            dedupe_key=dedupe_key,
            recipient=self.recipient,
            subject=subject,
            body=body,
            attempts=0,
        )
        self.db.add(notification)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = (
                self.db.query(Notification)
                .filter(Notification.dedupe_key == dedupe_key)
                .first()
            )
            if existing is not None and existing.status == NotificationStatus.FAILED:
                return existing
            return None

        self.db.refresh(notification)
        return notification

    def _deliver(self, notification: Notification) -> bool:
        if not self.enabled:
            return False

        transport = self.transport
        sender = self.sender
        if transport is None or sender is None:
            return False

        notification.attempts += 1
        try:
            transport.send(
                sender,
                notification.recipient,
                notification.subject,
                notification.body,
            )
        except Exception as exc:
            notification.status = NotificationStatus.FAILED
            notification.last_error = str(exc)[:2000]
            self.db.commit()
            logger.exception("Notification delivery failed")
            return False

        notification.status = NotificationStatus.SENT
        notification.sent_at = utc_now()
        notification.last_error = None
        self.db.commit()
        return True

    @staticmethod
    def _render_instant_email(
        opportunity: Opportunity,
        company_name: str,
        match: OpportunityMatch,
    ) -> tuple[str, str]:
        safe_company = html.escape(company_name)
        safe_title = html.escape(opportunity.title)
        safe_location = html.escape(opportunity.location or "Not specified")
        safe_deadline = html.escape(opportunity.deadline or "Not specified")
        safe_url = html.escape(opportunity.url, quote=True)
        summary = (opportunity.description or "No description available").strip()
        safe_summary = html.escape(summary[:600])
        safe_reasons = "<br>".join(
            html.escape(reason) for reason in match.result.reasons
        )
        subject = f"New Opportunity — {company_name} | {opportunity.title}"
        subject = " ".join(subject.replace("\r", " ").replace("\n", " ").split())
        body = f"""
<html>
  <body style="font-family:Arial,sans-serif;background:#f4f6f8;padding:24px;">
    <div style="max-width:680px;margin:auto;background:#fff;padding:28px;border-radius:12px;">
      <p style="color:#667085;margin:0 0 8px;">QUANTAGENT INSTANT ALERT</p>
      <h1 style="margin:0 0 8px;">{safe_title}</h1>
      <h2 style="color:#344054;margin:0 0 24px;">{safe_company}</h2>
      <p><strong>Location:</strong> {safe_location}</p>
      <p><strong>Deadline:</strong> {safe_deadline}</p>
      <p><strong>Match score:</strong> {match.result.score}%</p>
      <p><strong>Priority:</strong> {match.result.priority.value.title()}</p>
      <h3>Why this matches</h3>
      <p>{safe_reasons}</p>
      <h3>Summary</h3>
      <p>{safe_summary}</p>
      <p style="margin-top:28px;">
        <a href="{safe_url}" style="background:#175cd3;color:#fff;padding:12px 20px;text-decoration:none;border-radius:8px;">Apply now</a>
      </p>
    </div>
  </body>
</html>
""".strip()
        return subject, body
