import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from models.company import Company
from models.opportunity import Opportunity
from models.opportunity import OpportunityPriority
from models.opportunity import OpportunityType
from models.page import Page
from models.page import PageType
from scrapers.base import ATS
from services.matcher import OpportunityMatcher
from services.matcher import ProfileValidationError
from services.monitor import Monitor
from services.monitor import ScanResult
from services.sync import SyncStatus
from test_milestone_6 import build_service


VALID_PROFILE = """student: true
graduation_year: 2027
visa_required: true
alert_threshold: 70
roles:
  - Quant Developer
locations:
  - London
skills:
  - python
  - c++
positive_keywords:
  - intern
negative_keywords:
  - senior
"""


class ProfileTestCase(unittest.TestCase):
    def matcher(self, content: str = VALID_PROFILE) -> OpportunityMatcher:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        path = Path(temporary_directory.name) / "profile.yaml"
        path.write_text(content, encoding="utf-8")
        return OpportunityMatcher(path)


class OpportunityMatcherTests(ProfileTestCase):
    def opportunity(self, **changes: object) -> dict[str, object]:
        item: dict[str, object] = {
            "company_id": 1,
            "provider_id": "one",
            "type": OpportunityType.INTERNSHIP,
            "title": "Quant Developer Intern",
            "description": "Python and C++ low latency systems",
            "location": "London",
            "visa": "Sponsorship available",
        }
        item.update(changes)
        return item

    def test_complete_match_scores_one_hundred(self) -> None:
        result = self.matcher().match(self.opportunity())

        self.assertEqual(result.score, 100)
        self.assertEqual(result.priority, OpportunityPriority.HIGH)
        self.assertIn("Role match: quant developer", result.reasons)
        self.assertIn("Location match: london", result.reasons)
        self.assertIn("Skill match: python, c++", result.reasons)
        self.assertIn("Visa match: sponsorship indicated", result.reasons)

    def test_negative_keyword_and_visa_penalties_are_applied(self) -> None:
        result = self.matcher().match(
            self.opportunity(
                title="Senior Quant Developer Intern",
                visa="No sponsorship",
            )
        )

        self.assertEqual(result.score, 30)
        self.assertEqual(result.priority, OpportunityPriority.LOW)
        self.assertIn("Negative keywords: senior", result.reasons)
        self.assertIn("Visa match: sponsorship unavailable", result.reasons)

    def test_priority_uses_configured_threshold(self) -> None:
        profile = VALID_PROFILE.replace("alert_threshold: 70", "alert_threshold: 100")
        result = self.matcher(profile).match(self.opportunity(visa=None))

        self.assertEqual(result.score, 85)
        self.assertEqual(result.priority, OpportunityPriority.MEDIUM)

    def test_negative_keywords_do_not_match_inside_other_words(self) -> None:
        profile = VALID_PROFILE.replace("  - senior", "  - lead")
        result = self.matcher(profile).match(
            self.opportunity(description="Python C++ technical leadership")
        )

        self.assertEqual(result.score, 100)
        self.assertFalse(
            any(reason.startswith("Negative keywords") for reason in result.reasons)
        )

    def test_match_many_requires_persistence_identity(self) -> None:
        matcher = self.matcher()
        with self.assertRaises(ValueError):
            matcher.match_many([{"title": "Engineer"}])

    def test_malformed_profile_has_actionable_error(self) -> None:
        invalid_profile = VALID_PROFILE.replace(
            "alert_threshold: 70",
            "alert_threshold: 101",
        )
        with self.assertRaisesRegex(
            ProfileValidationError,
            "alert_threshold must be between 0 and 100",
        ):
            self.matcher(invalid_profile)


class MatchPersistenceTests(ProfileTestCase):
    def test_monitor_persists_match_result(self) -> None:
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
            url="https://example.com/careers",
        )
        setup.add(page)
        setup.commit()
        company_id = company.id
        page_id = page.id
        setup.close()

        with patch("services.monitor.SessionLocal", session_factory):
            monitor = Monitor()

        opportunity = {
            "company_id": company_id,
            "page_id": page_id,
            "provider_id": "one",
            "type": OpportunityType.INTERNSHIP,
            "title": "Quant Developer Intern",
            "description": "Python and C++",
            "location": "London",
            "url": "https://example.com/jobs/one",
            "visa": "Sponsorship available",
            "deadline": None,
        }
        monitor.reconcile_opportunities(page_id, [opportunity])
        monitor.save_matches(self.matcher().match_many([opportunity]))

        stored = monitor.db.query(Opportunity).one()
        self.assertEqual(stored.match_score, 100)
        self.assertEqual(stored.match_priority, OpportunityPriority.HIGH)
        self.assertIn("Role match", stored.match_reason or "")
        monitor.db.close()
        engine.dispose()


class MatchSyncIntegrationTests(unittest.TestCase):
    def test_matching_failure_is_partial_after_persistence(self) -> None:
        page = Mock(
            id=1,
            company_id=2,
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
        matcher = Mock()
        matcher.match_many.side_effect = ProfileValidationError("invalid profile")
        service = build_service(
            factory=factory,
            normalizer=normalizer,
            monitor=monitor,
            matcher=matcher,
        )

        result = service.scan_page(page)

        self.assertEqual(result.status, SyncStatus.PARTIAL)
        self.assertEqual(result.lifecycle, ScanResult(new=1))
        self.assertIn("Matching failed: invalid profile", result.message or "")
        monitor.save_matches.assert_not_called()


if __name__ == "__main__":
    unittest.main()
