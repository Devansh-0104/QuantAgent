import html
import logging
import smtplib
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
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
from models.opportunity import OpportunityStatus
from models.opportunity import OpportunityType
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


@dataclass(frozen=True)
class DailyReportMetrics:
    companies_checked: int
    successful_companies: int
    failures: int
    new_opportunities: int
    updated_opportunities: int
    closed_opportunities: int

    @property
    def success_rate(self) -> int:
        if not self.companies_checked:
            return 0
        return round(100 * self.successful_companies / self.companies_checked)


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

    def send_daily_report(
        self,
        metrics: DailyReportMetrics,
        report_date: date | None = None,
    ) -> NotificationBatchResult:
        result = NotificationBatchResult()
        if not self.enabled:
            logger.warning("Daily reports are disabled: SMTP is not configured")
            result.skipped = 1
            return result

        effective_date = report_date or datetime.now().astimezone().date()
        notification = self._claim_daily_notification(metrics, effective_date)
        if notification is None:
            result.skipped = 1
        elif self._deliver(notification):
            result.sent = 1
        else:
            result.failed = 1
        return result

    def _claim_daily_notification(
        self,
        metrics: DailyReportMetrics,
        report_date: date,
    ) -> Notification | None:
        dedupe_key = f"daily:{report_date.isoformat()}"
        existing = (
            self.db.query(Notification)
            .filter(Notification.dedupe_key == dedupe_key)
            .first()
        )
        if existing is not None:
            return existing if existing.status == NotificationStatus.FAILED else None

        start, end = self._utc_day_bounds(report_date)
        new_opportunities = (
            self.db.query(Opportunity, Company.name)
            .join(Company, Company.id == Opportunity.company_id)
            .filter(
                Opportunity.first_seen >= start,
                Opportunity.first_seen < end,
            )
            .order_by(
                Opportunity.match_score.desc(),
                Company.name,
                Opportunity.title,
            )
            .all()
        )
        previous_start = start - timedelta(days=1)
        previous_count = (
            self.db.query(Opportunity)
            .filter(
                Opportunity.first_seen >= previous_start,
                Opportunity.first_seen < start,
            )
            .count()
        )
        closed_opportunities = (
            self.db.query(Opportunity, Company.name)
            .join(Company, Company.id == Opportunity.company_id)
            .filter(
                Opportunity.status == OpportunityStatus.CLOSED,
                Opportunity.last_modified >= start,
                Opportunity.last_modified < end,
            )
            .order_by(Company.name, Opportunity.title)
            .all()
        )
        subject, body = self._render_daily_email(
            metrics,
            report_date,
            new_opportunities,
            closed_opportunities,
            previous_count,
        )
        notification = Notification(
            opportunity_id=None,
            type=NotificationType.DAILY,
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

    @staticmethod
    def _utc_day_bounds(report_date: date) -> tuple[datetime, datetime]:
        local_timezone = datetime.now().astimezone().tzinfo
        local_start = datetime.combine(report_date, time.min, tzinfo=local_timezone)
        local_end = local_start + timedelta(days=1)
        return (
            local_start.astimezone(UTC).replace(tzinfo=None),
            local_end.astimezone(UTC).replace(tzinfo=None),
        )

    @classmethod
    def _render_daily_email(
        cls,
        metrics: DailyReportMetrics,
        report_date: date,
        opportunity_rows: list[tuple[Opportunity, str]],
        closed_rows: list[tuple[Opportunity, str]],
        previous_count: int,
    ) -> tuple[str, str]:
        opportunities = [row[0] for row in opportunity_rows]
        internships = sum(
            opportunity.type == OpportunityType.INTERNSHIP
            for opportunity in opportunities
        )
        events = sum(
            opportunity.type == OpportunityType.EVENT for opportunity in opportunities
        )
        graduate_programs = sum(
            opportunity.type == OpportunityType.GRADUATE
            for opportunity in opportunities
        )
        jobs = sum(
            opportunity.type == OpportunityType.JOB for opportunity in opportunities
        )
        event_rows = [
            row for row in opportunity_rows if row[0].type == OpportunityType.EVENT
        ]
        graduate_rows = [
            row
            for row in opportunity_rows
            if row[0].type == OpportunityType.GRADUATE
        ]
        high_rows = [
            row
            for row in opportunity_rows
            if row[0].match_priority == OpportunityPriority.HIGH
        ]
        medium_rows = [
            row
            for row in opportunity_rows
            if row[0].match_priority == OpportunityPriority.MEDIUM
        ]
        deadlines = [row for row in opportunity_rows if row[0].deadline]
        company_activity: dict[str, int] = {}
        for _, company_name in opportunity_rows:
            company_activity[company_name] = company_activity.get(company_name, 0) + 1

        difference = len(opportunities) - previous_count
        if difference > 0:
            trend = f"Hiring activity increased by {difference} posting(s) versus yesterday."
        elif difference < 0:
            trend = f"Hiring activity decreased by {abs(difference)} posting(s) versus yesterday."
        else:
            trend = "Hiring activity was unchanged versus yesterday."
        summary = cls._daily_summary(metrics, company_activity, high_rows, trend)

        subject = f"Daily Recruiting Intelligence — {report_date:%d %B %Y}"
        sections = [
            cls._opportunity_section("High Priority Matches", high_rows),
            cls._opportunity_section("Medium Priority Matches", medium_rows),
            cls._opportunity_section("Application Deadlines", deadlines),
            cls._opportunity_section("Recruiting Events", event_rows),
            cls._opportunity_section("Graduate Programs", graduate_rows),
            cls._opportunity_section("Closed Opportunities", closed_rows),
        ]
        activity_html = "".join(
            f"<tr><td>{html.escape(company)}</td><td style='text-align:right'>+{count}</td></tr>"
            for company, count in sorted(
                company_activity.items(), key=lambda item: (-item[1], item[0])
            )
        ) or "<tr><td colspan='2'>No company activity recorded.</td></tr>"
        body = f"""
<html>
  <body style="font-family:Arial,sans-serif;background:#eef2f6;padding:24px;color:#101828;">
    <div style="max-width:820px;margin:auto;background:#fff;border-radius:14px;overflow:hidden;">
      <div style="background:#101828;color:#fff;padding:30px;">
        <p style="margin:0;color:#98a2b3;">QUANTAGENT</p>
        <h1 style="margin:8px 0;">Daily Recruiting Intelligence</h1>
        <p style="margin:0;">{report_date:%A • %d %B %Y}</p>
      </div>
      <div style="padding:28px;">
        <h2>Executive Summary</h2>
        <p>{html.escape(summary)}</p>
        <table style="width:100%;border-collapse:collapse;margin:24px 0;">
          {cls._metric_row("Companies checked", metrics.companies_checked, "Success rate", f"{metrics.success_rate}%")}
          {cls._metric_row("New opportunities", metrics.new_opportunities, "New jobs", jobs)}
          {cls._metric_row("Internships", internships, "Graduate programs", graduate_programs)}
          {cls._metric_row("Recruiting events", events, "Closed opportunities", metrics.closed_opportunities)}
          {cls._metric_row("Updated opportunities", metrics.updated_opportunities, "Failures", metrics.failures)}
        </table>
        {''.join(sections)}
        <h2>Company Activity</h2>
        <table style="width:100%;border-collapse:collapse;">{activity_html}</table>
        <h2>Recruiting Trends</h2>
        <p>{html.escape(trend)}</p>
        <h2>System Health</h2>
        <p>{metrics.successful_companies} of {metrics.companies_checked} companies completed successfully; {metrics.failures} failure(s) recorded.</p>
      </div>
    </div>
  </body>
</html>
""".strip()
        return subject, body

    @staticmethod
    def _metric_row(
        left_label: str,
        left_value: object,
        right_label: str,
        right_value: object,
    ) -> str:
        return (
            "<tr>"
            f"<td style='padding:12px;border:1px solid #eaecf0'><strong>{html.escape(left_label)}</strong><br>{html.escape(str(left_value))}</td>"
            f"<td style='padding:12px;border:1px solid #eaecf0'><strong>{html.escape(right_label)}</strong><br>{html.escape(str(right_value))}</td>"
            "</tr>"
        )

    @staticmethod
    def _opportunity_section(
        title: str,
        rows: list[tuple[Opportunity, str]],
    ) -> str:
        cards = "".join(
            "<div style='border:1px solid #eaecf0;border-radius:8px;padding:14px;margin:10px 0'>"
            f"<strong>{html.escape(company_name)} — {html.escape(opportunity.title)}</strong><br>"
            f"{html.escape(opportunity.location or 'Location not specified')} · "
            f"{opportunity.match_score or 0}%"
            + (
                f" · Deadline: {html.escape(opportunity.deadline)}"
                if opportunity.deadline
                else ""
            )
            + f"<br><a href='{html.escape(opportunity.url, quote=True)}'>View opportunity →</a></div>"
            for opportunity, company_name in rows[:10]
        )
        if not cards:
            cards = "<p style='color:#667085'>None recorded today.</p>"
        return f"<h2>{html.escape(title)}</h2>{cards}"

    @staticmethod
    def _daily_summary(
        metrics: DailyReportMetrics,
        company_activity: dict[str, int],
        high_rows: list[tuple[Opportunity, str]],
        trend: str,
    ) -> str:
        if company_activity:
            most_active, count = max(
                company_activity.items(), key=lambda item: (item[1], item[0])
            )
            activity = f"{most_active} was the most active company with {count} new posting(s)."
        else:
            activity = "No new company activity was recorded."
        return (
            f"{metrics.companies_checked} companies were checked with a "
            f"{metrics.success_rate}% success rate. {len(high_rows)} high-priority "
            f"match(es) were identified. {activity} {trend}"
        )
