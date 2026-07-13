import httpx

from urllib.parse import urlparse

from scrapers.base import JobScraper


class LeverScraper(JobScraper):

    API = "https://api.lever.co/v0/postings/{company}?mode=json"

    def scrape(self, url: str):

        company = self._company(url)

        api = self.API.format(company=company)

        response = httpx.get(
            api,
            timeout=20
        )

        response.raise_for_status()

        return response.json()

    def _company(self, url: str):

        path = urlparse(url).path.strip("/")

        return path.split("/")[0]