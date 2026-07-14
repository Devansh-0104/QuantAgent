import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from models.company import Company
from models.opportunity import Opportunity
from models.opportunity import OpportunityHistory
from models.page import Page
from models.page import PageType
from scrapers.base import ATS
from services.matcher import ATSDetector
from services.monitor import Monitor
from services.monitor import ScanResult
from services.normalizer import OpportunityNormalizer
from services.sync import CompanySyncResult
from services.sync import SyncService
from services.sync import SyncStatus


def build_service(**overrides: object) -> SyncService:
    dependencies = {
        "registry": Mock(),
        "discovery": Mock(),
        "monitor": Mock(),
        "extractor": Mock(),
        "detector": ATSDetector(),
        "factory": Mock(),
        "normalizer": Mock(),
    }
    dependencies.update(overrides)
    return SyncService(**dependencies)  # type: ignore[arg-type]


class SyncServiceTests(unittest.TestCase):
    def test_direct_scrape_uses_provider_neutral_flow(self) -> None:
        page = SimpleNamespace(
            id=10,
            company_id=20,
            url="https://jobs.lever.co/example",
        )
        scraper = Mock()
        scraper.scrape.return_value = [{"id": "one"}]
        factory = Mock()
        factory.get.return_value = scraper
        normalizer = Mock()
        normalizer.normalize.return_value = [{"provider_id": "one"}]
        monitor = Mock()
        monitor.reconcile_opportunities.return_value = ScanResult(new=1)
        extractor = Mock()
        service = build_service(
            factory=factory,
            normalizer=normalizer,
            monitor=monitor,
            extractor=extractor,
        )

        result = service.scan_page(page)  # type: ignore[arg-type]

        self.assertEqual(result.status, SyncStatus.SUCCESS)
        self.assertEqual(result.lifecycle, ScanResult(new=1))
        extractor.analyze.assert_not_called()
        normalizer.normalize.assert_called_once_with(
            ATS.LEVER,
            company_id=20,
            page_id=10,
            jobs=[{"id": "one"}],
        )
        monitor.reconcile_opportunities.assert_called_once_with(
            10,
            [{"provider_id": "one"}],
            scan_completed=True,
        )

    def test_failed_candidate_does_not_stop_later_candidate(self) -> None:
        page = SimpleNamespace(id=1, company_id=2, url="https://example.com/jobs")
        extractor = Mock()
        extractor.analyze.return_value = [
            "https://jobs.lever.co/broken",
            "https://boards.greenhouse.io/working",
        ]
        broken_scraper = Mock()
        broken_scraper.scrape.side_effect = RuntimeError("provider unavailable")
        working_scraper = Mock()
        working_scraper.scrape.return_value = [{"id": 1}]
        factory = Mock()
        factory.get.side_effect = [broken_scraper, working_scraper]
        normalizer = Mock()
        normalizer.normalize.return_value = [{"provider_id": "1"}]
        monitor = Mock()
        monitor.reconcile_opportunities.return_value = ScanResult(new=1)
        service = build_service(
            extractor=extractor,
            factory=factory,
            normalizer=normalizer,
            monitor=monitor,
        )

        result = service.scan_page(page)  # type: ignore[arg-type]

        self.assertEqual(result.status, SyncStatus.PARTIAL)
        self.assertEqual(result.ats, ATS.GREENHOUSE)
        self.assertIn("LEVER failed", result.message or "")

    def test_company_failure_does_not_stop_remaining_companies(self) -> None:
        first = SimpleNamespace(id=1, name="Broken")
        second = SimpleNamespace(id=2, name="Working")
        registry = Mock()
        registry.all_companies.return_value = [first, second]
        service = build_service(registry=registry)
        working_result = CompanySyncResult(
            company_id=2,
            company_name="Working",
            status=SyncStatus.SUCCESS,
            pages=[],
            errors=[],
        )
        service.scan_company = Mock(  # type: ignore[method-assign]
            side_effect=[RuntimeError("broken company"), working_result]
        )

        result = service.run()

        self.assertEqual(len(result.companies), 2)
        self.assertEqual(result.companies[0].status, SyncStatus.FAILED)
        self.assertEqual(result.companies[1], working_result)
        self.assertEqual(result.status, SyncStatus.PARTIAL)

    def test_unexpected_page_failure_does_not_stop_later_pages(self) -> None:
        company = SimpleNamespace(id=1, name="Example")
        pages = [
            SimpleNamespace(id=1, url="https://example.com/one"),
            SimpleNamespace(id=2, url="https://example.com/two"),
        ]
        discovery = Mock()
        discovery.discover.return_value = True
        monitor = Mock()
        monitor.best_pages.return_value = pages
        service = build_service(discovery=discovery, monitor=monitor)
        service.scan_page = Mock(  # type: ignore[method-assign]
            side_effect=[
                RuntimeError("broken page"),
                SimpleNamespace(status=SyncStatus.SUCCESS),
            ]
        )

        result = service.scan_company(company)  # type: ignore[arg-type]

        self.assertEqual(len(result.pages), 2)
        self.assertEqual(result.pages[0].status, SyncStatus.FAILED)
        self.assertEqual(result.pages[1].status, SyncStatus.SUCCESS)
        self.assertEqual(result.status, SyncStatus.PARTIAL)

    def test_partial_page_produces_partial_company_status(self) -> None:
        page = SimpleNamespace(id=1, url="https://example.com/jobs")
        status = SyncService._company_status(
            [
                SimpleNamespace(
                    status=SyncStatus.PARTIAL,
                    page_id=page.id,
                    url=page.url,
                )
            ],  # type: ignore[arg-type]
            [],
        )
        self.assertEqual(status, SyncStatus.PARTIAL)


class SyncIdempotencyTests(unittest.TestCase):
    def test_repeated_full_sync_is_idempotent(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        setup = session_factory()
        company = Company(name="Example")
        setup.add(company)
        setup.flush()
        page = Page(
            company_id=company.id,
            page_type=PageType.CAREERS,
            url="https://jobs.lever.co/example",
        )
        setup.add(page)
        setup.commit()
        company_id = company.id
        setup.close()

        with patch("services.monitor.SessionLocal", session_factory):
            monitor = Monitor()

        registry = Mock()
        registry.all_companies.return_value = [monitor.db.get(Company, company_id)]
        discovery = Mock()
        discovery.discover.return_value = True
        scraper = Mock()
        scraper.scrape.return_value = [
            {
                "id": "one",
                "text": "Quant Developer",
                "categories": {"location": "London"},
                "hostedUrl": "https://jobs.lever.co/example/one",
            }
        ]
        factory = Mock()
        factory.get.return_value = scraper
        service = build_service(
            registry=registry,
            discovery=discovery,
            monitor=monitor,
            factory=factory,
            normalizer=OpportunityNormalizer(),
        )

        first = service.run()
        second = service.run()

        self.assertEqual(first.companies[0].pages[0].lifecycle.new, 1)
        self.assertEqual(second.companies[0].pages[0].lifecycle.unchanged, 1)
        self.assertEqual(monitor.db.query(Opportunity).count(), 1)
        self.assertEqual(monitor.db.query(OpportunityHistory).count(), 1)
        monitor.db.close()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
