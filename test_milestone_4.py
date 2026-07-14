import unittest

from models.opportunity import OpportunityType
from scrapers.base import ATS
from services.monitor import Monitor
from services.normalizer import OpportunityNormalizer


class OpportunityNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = OpportunityNormalizer()

    def test_greenhouse_produces_provider_neutral_contract(self) -> None:
        opportunities = self.normalizer.greenhouse(
            company_id=1,
            page_id=2,
            jobs=[
                {
                    "id": 42,
                    "title": " Quantitative Research Intern ",
                    "location": {"name": " London "},
                    "absolute_url": "https://boards.greenhouse.io/example/jobs/42",
                }
            ],
        )

        self.assertEqual(
            opportunities,
            [
                {
                    "company_id": 1,
                    "page_id": 2,
                    "provider_id": "42",
                    "type": OpportunityType.INTERNSHIP,
                    "title": "Quantitative Research Intern",
                    "description": None,
                    "location": "London",
                    "url": "https://boards.greenhouse.io/example/jobs/42",
                    "visa": None,
                    "deadline": None,
                }
            ],
        )

    def test_lever_produces_same_contract(self) -> None:
        opportunities = self.normalizer.lever(
            company_id=1,
            page_id=2,
            jobs=[
                {
                    "id": "abc",
                    "text": "Graduate Developer",
                    "categories": {"location": "Amsterdam"},
                    "hostedUrl": "https://jobs.lever.co/example/abc",
                }
            ],
        )

        self.assertEqual(opportunities[0]["provider_id"], "abc")
        self.assertEqual(opportunities[0]["type"], OpportunityType.GRADUATE)
        self.assertEqual(opportunities[0]["location"], "Amsterdam")

    def test_generic_entry_point_dispatches_by_provider(self) -> None:
        opportunities = self.normalizer.normalize(
            ATS.LEVER,
            company_id=1,
            page_id=2,
            jobs=[
                {
                    "id": "abc",
                    "text": "Engineer",
                    "categories": {},
                    "hostedUrl": "https://jobs.lever.co/example/abc",
                }
            ],
        )
        self.assertEqual(len(opportunities), 1)

        self.assertEqual(self.normalizer.normalize(ATS.WORKDAY, 1, 2, []), [])

    def test_classification_is_shared_for_all_providers(self) -> None:
        cases = {
            "Software Engineering Intern": OpportunityType.INTERNSHIP,
            "Quantitative Graduate": OpportunityType.GRADUATE,
            "New Grad Trader": OpportunityType.GRADUATE,
            "Recruiting Event": OpportunityType.EVENT,
            "Trading Competition": OpportunityType.COMPETITION,
            "Experienced Engineer": OpportunityType.JOB,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(self.normalizer.classify(title), expected)

    def test_invalid_records_are_rejected_independently(self) -> None:
        jobs = [
            {
                "id": "valid",
                "title": "Engineer",
                "location": None,
                "absolute_url": "https://example.com/jobs/valid",
            },
            {
                "id": "",
                "title": "Missing identity",
                "absolute_url": "https://example.com/jobs/no-id",
            },
            {
                "id": "no-title",
                "title": " ",
                "absolute_url": "https://example.com/jobs/no-title",
            },
            {
                "id": "bad-url",
                "title": "Bad URL",
                "absolute_url": "javascript:void(0)",
            },
        ]

        opportunities = self.normalizer.greenhouse(1, 2, jobs)
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["location"], "")

    def test_hashing_accepts_nullable_values(self) -> None:
        item = {
            "title": "Engineer",
            "location": None,
            "url": "https://example.com/jobs/1",
        }
        monitor = Monitor.__new__(Monitor)
        first_hash = monitor.compute_hash(item)
        self.assertEqual(first_hash, monitor.compute_hash(item))
        self.assertEqual(len(first_hash), 64)


if __name__ == "__main__":
    unittest.main()
