from scrapers.base import JobScraper
from scrapers.base import RawJob
from urllib.parse import quote
from urllib.parse import urlsplit

from scrapers.base import http_client


class AshbyScraper(JobScraper):
    API = "https://api.ashbyhq.com/posting-api/job-board/{board}"

    def scrape(self, url: str) -> list[RawJob]:
        parts = [part for part in urlsplit(url).path.split("/") if part]
        if not parts:
            raise ValueError(f"Unable to determine Ashby board from {url}")
        response = http_client.get(
            self.API.format(board=quote(parts[0], safe="")),
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ValueError("Ashby returned an invalid jobs payload")
        return jobs
