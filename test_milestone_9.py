import unittest
from datetime import date
from datetime import timedelta
from unittest.mock import Mock
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from models.company import Company
from models.notification import Notification
from models.notification import NotificationStatus
from models.notification import NotificationType
from models.opportunity import Opportunity
from models.opportunity import OpportunityPriority
from models.opportunity import OpportunityType
from models.page import Page
from models.page import PageType
from services.monitor import ScanResult
from services.notifier import DailyReportMetrics
from services.notifier import NotificationBatchResult
from services.notifier import NotificationService
from services.sync import CompanySyncResult
from services.sync import PageScanResult
from services.sync import SyncService
from services.sync import SyncStatus


class DailyReportTests(unittest.TestCase):
    report_date = date(2026, 7, 14)

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        session = self.session_factory()
        company = Company(name="Jane & Partners")
        session.add(company)
        session.flush()
        page = Page(
            company_id=company.id,
            page_type=PageType.CAREERS,
            url="https://example.com/jobs",
        )
        session.add(page)
        session.flush()
        start, end = NotificationService._utc_day_bounds(self.report_date)
        current = Opportunity(
            company_id=company.id,
            page_id=page.id,
            provider_id="today",
            type=OpportunityType.INTERNSHIP,
            title="Quant <Research> Intern",
            location="London",
            url="https://example.com/jobs/today?a=1&b=2",
            deadline="31 July",
            match_score=96,
            match_priority=OpportunityPriority.HIGH,
            first_seen=start + (end - start) / 2,
        )
        previous = Opportunity(
            company_id=company.id,
            page_id=page.id,
            provider_id="yesterday",
            type=OpportunityType.JOB,
            title="Previous Role",
            url="https://example.com/jobs/yesterday",
            match_score=50,
            match_priority=OpportunityPriority.MEDIUM,
            first_seen=start - timedelta(hours=1),
        )
        session.add_all([current, previous])
        session.commit()
        session.close()
        self.transport = Mock()

    def tearDown(self) -> None:
        self.engine.dispose()

    def service(self) -> NotificationService:
        with patch("services.notifier.SessionLocal", self.session_factory):
            return NotificationService(
                transport=self.transport,
                sender="alerts@example.com",
                recipient="candidate@example.com",
            )

    @staticmethod
    def metrics() -> DailyReportMetrics:
        return DailyReportMetrics(
            companies_checked=10,
            successful_companies=9,
            failures=1,
            new_opportunities=1,
            updated_opportunities=2,
            closed_opportunities=3,
        )

    def test_daily_dashboard_is_sent_and_deduplicated(self) -> None:
        service = self.service()

        first = service.send_daily_report(self.metrics(), self.report_date)
        duplicate = service.send_daily_report(self.metrics(), self.report_date)

        self.assertEqual(first, NotificationBatchResult(sent=1))
        self.assertEqual(duplicate, NotificationBatchResult(skipped=1))
        self.transport.send.assert_called_once()
        notification = service.db.query(Notification).one()
        self.assertEqual(notification.type, NotificationType.DAILY)
        self.assertEqual(notification.status, NotificationStatus.SENT)
        self.assertEqual(notification.dedupe_key, "daily:2026-07-14")
        body = self.transport.send.call_args.args[3]
        for section in (
            "Executive Summary",
            "High Priority Matches",
            "Medium Priority Matches",
            "Application Deadlines",
            "Recruiting Events",
            "Graduate Programs",
            "Closed Opportunities",
            "Company Activity",
            "Recruiting Trends",
            "System Health",
        ):
            self.assertIn(section, body)
        self.assertIn("Jane &amp; Partners", body)
        self.assertIn("Quant &lt;Research&gt; Intern", body)
        self.assertNotIn("Previous Role", body)
        service.db.close()

    def test_failed_daily_report_is_retried_by_shared_retry_pipeline(self) -> None:
        self.transport.send.side_effect = RuntimeError("mail server unavailable")
        service = self.service()

        failed = service.send_daily_report(self.metrics(), self.report_date)
        self.transport.send.side_effect = None
        retried = service.retry_failed()

        self.assertEqual(failed, NotificationBatchResult(failed=1))
        self.assertEqual(retried, NotificationBatchResult(sent=1))
        notification = service.db.query(Notification).one()
        self.assertEqual(notification.status, NotificationStatus.SENT)
        self.assertEqual(notification.attempts, 2)
        service.db.close()

    def test_disabled_daily_report_is_skipped_without_history(self) -> None:
        with patch("services.notifier.SessionLocal", self.session_factory):
            service = NotificationService(None, None, None)

        result = service.send_daily_report(self.metrics(), self.report_date)

        self.assertEqual(result, NotificationBatchResult(skipped=1))
        self.assertEqual(service.db.query(Notification).count(), 0)
        service.db.close()

    def test_success_rate_handles_empty_run(self) -> None:
        metrics = DailyReportMetrics(0, 0, 0, 0, 0, 0)
        self.assertEqual(metrics.success_rate, 0)


class DailyReportSyncIntegrationTests(unittest.TestCase):
    def test_sync_sends_one_report_with_aggregated_metrics(self) -> None:
        notifier = Mock()
        notifier.retry_failed.return_value = NotificationBatchResult()
        notifier.send_daily_report.return_value = NotificationBatchResult(sent=1)
        registry = Mock()
        registry.all_companies.return_value = []
        service = SyncService(
            registry=registry,
            discovery=Mock(),
            monitor=Mock(),
            extractor=Mock(),
            detector=Mock(),
            matcher=Mock(),
            notifier=notifier,
            factory=Mock(),
            normalizer=Mock(),
        )
        service.scan_company = Mock(
            side_effect=[
                CompanySyncResult(
                    company_id=1,
                    company_name="Successful",
                    status=SyncStatus.SUCCESS,
                    pages=[
                        PageScanResult(
                            page_id=1,
                            url="https://example.com/one",
                            status=SyncStatus.SUCCESS,
                            lifecycle=ScanResult(new=2, updated=1, closed=1),
                        )
                    ],
                    errors=[],
                ),
                CompanySyncResult(
                    company_id=2,
                    company_name="Partial",
                    status=SyncStatus.PARTIAL,
                    pages=[
                        PageScanResult(
                            page_id=2,
                            url="https://example.com/two",
                            status=SyncStatus.FAILED,
                        )
                    ],
                    errors=["discovery failed"],
                ),
            ]
        )
        registry.all_companies.return_value = [Mock(), Mock()]

        result = service.run()

        notifier.send_daily_report.assert_called_once_with(
            DailyReportMetrics(
                companies_checked=2,
                successful_companies=1,
                failures=2,
                new_opportunities=2,
                updated_opportunities=1,
                closed_opportunities=1,
            )
        )
        self.assertEqual(result.daily_report, NotificationBatchResult(sent=1))
        self.assertEqual(result.status, SyncStatus.PARTIAL)

    def test_daily_report_failure_makes_successful_sync_partial(self) -> None:
        notifier = Mock()
        notifier.retry_failed.return_value = NotificationBatchResult()
        notifier.send_daily_report.return_value = NotificationBatchResult(failed=1)
        registry = Mock()
        registry.all_companies.return_value = [Mock()]
        service = SyncService(
            registry=registry,
            discovery=Mock(),
            monitor=Mock(),
            extractor=Mock(),
            detector=Mock(),
            matcher=Mock(),
            notifier=notifier,
            factory=Mock(),
            normalizer=Mock(),
        )
        service.scan_company = Mock(
            return_value=CompanySyncResult(
                company_id=1,
                company_name="Successful",
                status=SyncStatus.SUCCESS,
                pages=[],
                errors=[],
            )
        )

        result = service.run()

        self.assertEqual(result.status, SyncStatus.PARTIAL)


if __name__ == "__main__":
    unittest.main()
