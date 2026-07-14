import unittest
from unittest.mock import Mock
from unittest.mock import patch

from models.opportunity import OpportunityPriority
from models.opportunity import OpportunityType
from scrapers.ashby import AshbyScraper
from scrapers.custom import CustomScraper
from scrapers.workday import WorkdayScraper
from scrapers.pinpoint import PinpointScraper
from services.normalizer import OpportunityNormalizer


class GenericExtractionTests(unittest.TestCase):
    def test_extracts_job_and_event_json_ld(self) -> None:
        response = Mock()
        response.url = "https://example.com/careers"
        response.text = """
        <script type="application/ld+json">
        {"@graph": [
          {"@type":"JobPosting","title":"Quant Developer Intern",
           "url":"/jobs/1","description":"Python and C++",
           "jobLocation":{"address":{"addressLocality":"London"}},
           "validThrough":"2026-08-01"},
          {"@type":"Event","name":"Trading Hackathon",
           "url":"/events/one","endDate":"2026-09-01"}
        ]}
        </script>
        """
        with patch("scrapers.custom.http_client.get", return_value=response):
            jobs = CustomScraper().scrape("https://example.com/careers")

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["location"], "London")
        normalized = OpportunityNormalizer().generic(1, 2, jobs)
        self.assertEqual(normalized[0]["type"], OpportunityType.INTERNSHIP)
        self.assertEqual(normalized[1]["type"], OpportunityType.COMPETITION)
        self.assertEqual(normalized[0]["deadline"], "2026-08-01")

    def test_generic_navigation_link_is_not_an_opportunity(self) -> None:
        response = Mock()
        response.url = "https://example.com"
        response.text = '<a href="/careers">Careers</a>'
        with patch("scrapers.custom.http_client.get", return_value=response):
            self.assertEqual(CustomScraper().scrape("https://example.com"), [])


class ProviderContractTests(unittest.TestCase):
    def test_pinpoint_empty_board_is_authoritative(self) -> None:
        response = Mock()
        response.json.return_value = {"data": []}
        with patch("scrapers.pinpoint.http_client.get", return_value=response) as get:
            self.assertEqual(
                PinpointScraper().scrape("https://example.pinpointhq.com/"), []
            )
        get.assert_called_once_with(
            "https://example.pinpointhq.com/postings.json", timeout=30
        )

    def test_ashby_public_board_contract(self) -> None:
        response = Mock()
        response.json.return_value = {"jobs": [{"id": "one"}]}
        with patch("scrapers.ashby.http_client.get", return_value=response) as get:
            jobs = AshbyScraper().scrape("https://jobs.ashbyhq.com/example")
        self.assertEqual(jobs, [{"id": "one"}])
        get.assert_called_once_with(
            "https://api.ashbyhq.com/posting-api/job-board/example",
            timeout=20,
        )

    def test_workday_paginates_and_builds_public_urls(self) -> None:
        response = Mock()
        response.json.return_value = {
            "jobPostings": [
                {
                    "title": "Engineer",
                    "externalPath": "/en-US/site/job/Engineer_R1",
                }
            ],
            "total": 1,
        }
        with patch("scrapers.workday.http_client.post", return_value=response):
            jobs = WorkdayScraper().scrape(
                "https://example.wd5.myworkdayjobs.com/en-US/site"
            )
        self.assertEqual(
            jobs[0]["url"],
            "https://example.wd5.myworkdayjobs.com/en-US/site/job/Engineer_R1",
        )


if __name__ == "__main__":
    unittest.main()
