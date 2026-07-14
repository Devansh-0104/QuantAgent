import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from app.config import load_email_settings
from app.database import Base
from models.company import Company
from models.notification import Notification
from models.notification import NotificationStatus
from models.opportunity import Opportunity
from models.opportunity import OpportunityPriority
from models.opportunity import OpportunityType
from models.page import Page
from models.page import PageType
from scrapers.base import ATS
from services.matcher import MatchResult
from services.matcher import OpportunityMatch
from services.monitor import ScanResult
from services.notifier import NotificationBatchResult
from services.notifier import NotificationService
from services.sync import SyncService
from services.sync import SyncStatus


class NotificationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        session = self.session_factory()
        company = Company(name="A&B Capital")
        session.add(company)
        session.flush()
        page = Page(
            company_id=company.id,
            page_type=PageType.CAREERS,
            url="https://example.com/jobs",
        )
        session.add(page)
        session.flush()
        opportunity = Opportunity(
            company_id=company.id,
            page_id=page.id,
            provider_id="new-role",
            type=OpportunityType.JOB,
            title="Quant <script>alert(1)</script>",
            description="Research & trading",
            location="London",
            url="https://example.com/jobs/1?a=1&b=2",
        )
        session.add(opportunity)
        session.commit()
        self.company_id = company.id
        session.close()
        self.transport = Mock()

    def tearDown(self) -> None:
        self.engine.dispose()

    def service(self, transport: Mock | None = None) -> NotificationService:
        with patch("services.notifier.SessionLocal", self.session_factory):
            return NotificationService(
                transport=self.transport if transport is None else transport,
                sender="alerts@example.com",
                recipient="candidate@example.com",
            )

    def high_match(self) -> OpportunityMatch:
        return OpportunityMatch(
            company_id=self.company_id,
            provider_id="new-role",
            result=MatchResult(
                score=92,
                priority=OpportunityPriority.HIGH,
                reasons=("Role match: quant",),
            ),
        )

    def test_high_priority_alert_is_sent_and_persisted_once(self) -> None:
        service = self.service()

        first = service.send_instant_alerts([self.high_match()])
        second = service.send_instant_alerts([self.high_match()])

        self.assertEqual(first, NotificationBatchResult(sent=1))
        self.assertEqual(second, NotificationBatchResult(skipped=1))
        self.transport.send.assert_called_once()
        notification = service.db.query(Notification).one()
        self.assertEqual(notification.status, NotificationStatus.SENT)
        self.assertEqual(notification.attempts, 1)
        body = self.transport.send.call_args.args[3]
        self.assertIn("A&amp;B Capital", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>", body)
        service.db.close()

    def test_non_high_matches_are_skipped(self) -> None:
        service = self.service()
        match = OpportunityMatch(
            company_id=self.company_id,
            provider_id="new-role",
            result=MatchResult(
                score=55,
                priority=OpportunityPriority.MEDIUM,
                reasons=(),
            ),
        )

        result = service.send_instant_alerts([match])

        self.assertEqual(result, NotificationBatchResult(skipped=1))
        self.assertEqual(service.db.query(Notification).count(), 0)
        self.transport.send.assert_not_called()
        service.db.close()

    def test_failed_delivery_is_durable_and_retryable(self) -> None:
        self.transport.send.side_effect = RuntimeError("SMTP unavailable")
        service = self.service()

        first = service.send_instant_alerts([self.high_match()])
        self.transport.send.side_effect = None
        retry = service.retry_failed()

        self.assertEqual(first, NotificationBatchResult(failed=1))
        self.assertEqual(retry, NotificationBatchResult(sent=1))
        notification = service.db.query(Notification).one()
        self.assertEqual(notification.status, NotificationStatus.SENT)
        self.assertEqual(notification.attempts, 2)
        self.assertIsNone(notification.last_error)
        service.db.close()

    def test_disabled_service_does_not_create_records(self) -> None:
        with patch("services.notifier.SessionLocal", self.session_factory):
            service = NotificationService(None, None, None)

        result = service.send_instant_alerts([self.high_match()])

        self.assertEqual(result, NotificationBatchResult(skipped=1))
        self.assertEqual(service.db.query(Notification).count(), 0)
        service.db.close()

    def test_metadata_creates_notification_table(self) -> None:
        self.assertIn("notifications", inspect(self.engine).get_table_names())


class NotificationConfigurationTests(unittest.TestCase):
    def test_missing_configuration_disables_email(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(load_email_settings())

    def test_complete_configuration_is_loaded(self) -> None:
        values = {
            "QUANTAGENT_SMTP_HOST": "smtp.example.com",
            "QUANTAGENT_EMAIL_FROM": "from@example.com",
            "QUANTAGENT_EMAIL_TO": "to@example.com",
            "QUANTAGENT_SMTP_PORT": "2525",
            "QUANTAGENT_SMTP_USERNAME": "user",
            "QUANTAGENT_SMTP_PASSWORD": "secret",
            "QUANTAGENT_SMTP_TLS": "false",
        }
        with patch.dict(os.environ, values, clear=True):
            settings = load_email_settings()

        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertEqual(settings.port, 2525)
        self.assertFalse(settings.use_tls)

    def test_incomplete_credentials_are_rejected(self) -> None:
        values = {
            "QUANTAGENT_SMTP_HOST": "smtp.example.com",
            "QUANTAGENT_EMAIL_FROM": "from@example.com",
            "QUANTAGENT_EMAIL_TO": "to@example.com",
            "QUANTAGENT_SMTP_USERNAME": "user",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(ValueError, "configured together"):
                load_email_settings()


class NotificationSyncIntegrationTests(unittest.TestCase):
    def build_service(self, lifecycle: ScanResult) -> tuple[SyncService, Mock]:
        opportunity = {
            "company_id": 2,
            "provider_id": "new-role",
        }
        monitor = Mock()
        monitor.reconcile_opportunities.return_value = lifecycle
        matcher = Mock()
        matcher.match_many.return_value = [
            OpportunityMatch(
                company_id=2,
                provider_id="new-role",
                result=MatchResult(90, OpportunityPriority.HIGH, ("match",)),
            )
        ]
        notifier = Mock()
        notifier.send_instant_alerts.return_value = NotificationBatchResult(sent=1)
        notifier.retry_failed.return_value = NotificationBatchResult()
        scraper = Mock()
        scraper.scrape.return_value = [{"id": "new-role"}]
        factory = Mock()
        factory.get.return_value = scraper
        normalizer = Mock()
        normalizer.normalize.return_value = [opportunity]
        service = SyncService(
            registry=Mock(),
            discovery=Mock(),
            monitor=monitor,
            extractor=Mock(),
            detector=SimpleNamespace(detect=lambda _url: ATS.LEVER),
            matcher=matcher,
            notifier=notifier,
            factory=factory,
            normalizer=normalizer,
        )
        return service, notifier

    def test_only_new_matches_are_sent_to_notifier(self) -> None:
        service, notifier = self.build_service(
            ScanResult(new=1, new_provider_ids={"new-role"})
        )
        page = SimpleNamespace(id=1, company_id=2, url="https://jobs.lever.co/acme")

        result = service.scan_page(page)

        self.assertEqual(result.status, SyncStatus.SUCCESS)
        notifier.send_instant_alerts.assert_called_once()
        self.assertEqual(
            notifier.send_instant_alerts.call_args.args[0][0].provider_id,
            "new-role",
        )

    def test_existing_matches_are_not_sent_to_notifier(self) -> None:
        service, notifier = self.build_service(ScanResult(unchanged=1))
        page = SimpleNamespace(id=1, company_id=2, url="https://jobs.lever.co/acme")

        service.scan_page(page)

        notifier.send_instant_alerts.assert_called_once_with([])

    def test_delivery_failure_marks_page_partial(self) -> None:
        service, notifier = self.build_service(
            ScanResult(new=1, new_provider_ids={"new-role"})
        )
        notifier.send_instant_alerts.return_value = NotificationBatchResult(failed=1)
        page = SimpleNamespace(id=1, company_id=2, url="https://jobs.lever.co/acme")

        result = service.scan_page(page)

        self.assertEqual(result.status, SyncStatus.PARTIAL)
        self.assertIn("notification(s) failed", result.message or "")


if __name__ == "__main__":
    unittest.main()
