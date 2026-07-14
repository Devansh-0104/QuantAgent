from urllib.parse import quote
from urllib.parse import urlsplit

import httpx

from scrapers.base import JobScraper
from scrapers.base import RawJob


class LeverScraper(JobScraper):
    API = "https://api.lever.co/v0/postings/{company}?mode=json"

    def scrape(self, url: str) -> list[RawJob]:
        company = self._company(url)
        api = self.API.format(company=quote(company, safe=""))
        response = httpx.get(api, timeout=20)
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Lever returned an invalid jobs payload")

        return payload

    def _company(self, url: str) -> str:
        path_parts = [part for part in urlsplit(url).path.split("/") if part]
        if not path_parts:
            raise ValueError(f"Unable to determine Lever company from {url}")

        return path_parts[0]
