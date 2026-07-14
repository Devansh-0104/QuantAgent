import unittest
from unittest.mock import Mock
from unittest.mock import patch

import httpx
from playwright.sync_api import Error as PlaywrightError
from typer.testing import CliRunner

from app.cli import app
from scrapers.ashby import AshbyScraper
from scrapers.base import ATS
from scrapers.base import UnsupportedScraperError
from scrapers.custom import CustomScraper
from scrapers.greenhouse import GreenhouseScraper
from scrapers.lever import LeverScraper
from scrapers.workday import WorkdayScraper
from scrapers.smartrecruiters import SmartRecruitersScraper
from scrapers.pinpoint import PinpointScraper
from services.extractor import Extractor
from services.matcher import ATSDetector
from services.notifier import ScraperFactory


class ATSDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = ATSDetector()

    def test_detects_exact_and_subdomain_hosts(self) -> None:
        self.assertEqual(
            self.detector.detect("https://boards.greenhouse.io/example"),
            ATS.GREENHOUSE,
        )
        self.assertEqual(
            self.detector.detect("https://jobs.lever.co/example"),
            ATS.LEVER,
        )

    def test_does_not_match_embedded_domain_text(self) -> None:
        self.assertEqual(
            self.detector.detect("https://greenhouse.io.example.com/jobs"),
            ATS.CUSTOM,
        )
        self.assertEqual(
            self.detector.detect("https://notlever.co/jobs"),
            ATS.CUSTOM,
        )

    def test_invalid_url_is_custom(self) -> None:
        self.assertEqual(self.detector.detect("not-a-url"), ATS.CUSTOM)


class ProviderTests(unittest.TestCase):
    def test_greenhouse_parses_supported_board_urls(self) -> None:
        scraper = GreenhouseScraper()
        self.assertEqual(
            scraper._board_name("https://boards.greenhouse.io/example/jobs/1"),
            "example",
        )
        self.assertEqual(
            scraper._board_name(
                "https://boards.greenhouse.io/embed/job_board?for=example"
            ),
            "example",
        )

    def test_greenhouse_rejects_url_without_board(self) -> None:
        with self.assertRaises(ValueError):
            GreenhouseScraper()._board_name("https://boards.greenhouse.io/")

    def test_greenhouse_prefers_explicit_board_over_talent_community(self) -> None:
        self.assertEqual(
            GreenhouseScraper()._board_name(
                "https://boards.greenhouse.io/talent_community?for=jumptrading"
            ),
            "jumptrading",
        )

    def test_greenhouse_fetches_jobs_from_api(self) -> None:
        response = Mock()
        response.json.return_value = {"jobs": [{"id": 1}]}

        with patch("scrapers.greenhouse.http_client.get", return_value=response) as get:
            jobs = GreenhouseScraper().scrape(
                "https://boards.greenhouse.io/example/jobs/1"
            )

        self.assertEqual(jobs, [{"id": 1}])
        response.raise_for_status.assert_called_once_with()
        get.assert_called_once_with(
            "https://boards-api.greenhouse.io/v1/boards/example/jobs",
            timeout=20,
        )

    def test_lever_fetches_jobs_from_api(self) -> None:
        response = Mock()
        response.json.return_value = [{"id": "one"}]

        with patch("scrapers.lever.http_client.get", return_value=response) as get:
            jobs = LeverScraper().scrape("https://jobs.lever.co/example/one")

        self.assertEqual(jobs, [{"id": "one"}])
        response.raise_for_status.assert_called_once_with()
        get.assert_called_once_with(
            "https://api.lever.co/v0/postings/example?mode=json",
            timeout=20,
        )

    def test_provider_payloads_are_validated(self) -> None:
        response = Mock()
        response.json.return_value = {"unexpected": []}

        with patch("scrapers.greenhouse.http_client.get", return_value=response):
            with self.assertRaises(ValueError):
                GreenhouseScraper().scrape("https://boards.greenhouse.io/example")

    def test_factory_returns_only_supported_scrapers(self) -> None:
        factory = ScraperFactory()
        self.assertIsInstance(factory.get(ATS.GREENHOUSE), GreenhouseScraper)
        self.assertIsInstance(factory.get(ATS.LEVER), LeverScraper)
        self.assertIsInstance(factory.get(ATS.CUSTOM), CustomScraper)

        self.assertIsInstance(factory.get(ATS.ASHBY), AshbyScraper)
        self.assertIsInstance(factory.get(ATS.WORKDAY), WorkdayScraper)
        self.assertIsInstance(
            factory.get(ATS.SMARTRECRUITERS), SmartRecruitersScraper
        )
        self.assertIsInstance(factory.get(ATS.PINPOINT), PinpointScraper)

class ExtractorTests(unittest.TestCase):
    def test_static_extraction_validates_status(self) -> None:
        request = httpx.Request("GET", "https://example.com/careers")
        response = httpx.Response(500, request=request)

        with patch("services.extractor.http_client.get", return_value=response):
            with self.assertRaises(httpx.HTTPStatusError):
                Extractor()._html_links("https://example.com/careers")

    def test_browser_is_not_used_when_static_candidates_exist(self) -> None:
        extractor = Extractor()
        with (
            patch.object(
                extractor,
                "_html_links",
                return_value=["https://jobs.lever.co/example"],
            ),
            patch.object(extractor, "_browser_links") as browser_links,
        ):
            result = extractor.analyze("https://example.com/careers")

        self.assertEqual(result, ["https://jobs.lever.co/example"])
        browser_links.assert_not_called()

    def test_browser_failure_returns_no_links(self) -> None:
        extractor = Extractor()
        with (
            patch.object(extractor, "_html_links", return_value=[]),
            patch(
                "services.extractor.sync_playwright",
                side_effect=PlaywrightError("browser unavailable"),
            ),
        ):
            result = extractor.analyze("https://example.com/careers")

        self.assertEqual(result, [])

    def test_non_http_links_are_rejected(self) -> None:
        result = Extractor()._score_links(
            "https://example.com/careers",
            ["mailto:jobs@example.com", "javascript:apply()"],
        )
        self.assertEqual(result, [])


class CLIIntegrationTests(unittest.TestCase):
    def test_scrape_reports_unsupported_provider_cleanly(self) -> None:
        page = Mock(id=1, company_id=1, url="https://example.myworkdayjobs.com/jobs")

        with patch("app.cli.monitor.get_page", return_value=page):
            result = CliRunner().invoke(app, ["scrape", "1"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("WORKDAY failed:", result.stdout)


if __name__ == "__main__":
    unittest.main()
