import httpx

from scrapers.base import JobScraper
from scrapers.base import RawJob


class JaneStreetScraper(JobScraper):
    def scrape(self, url: str) -> list[RawJob]:
        response = httpx.get(url, timeout=30)
        response.raise_for_status()

        payload = response.json()
        if isinstance(payload, dict):
            payload = payload.get("jobs")
        if not isinstance(payload, list):
            raise ValueError("Jane Street returned an invalid jobs payload")

        return payload
