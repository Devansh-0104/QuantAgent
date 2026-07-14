from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import urlsplit

import httpx

from scrapers.base import JobScraper
from scrapers.base import RawJob


class GreenhouseScraper(JobScraper):
    API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"

    def scrape(self, url: str) -> list[RawJob]:
        board = self._board_name(url)
        api = self.API.format(board=quote(board, safe=""))
        response = httpx.get(api, timeout=20)
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ValueError("Greenhouse returned an invalid jobs payload")

        return payload["jobs"]

    def _board_name(self, url: str) -> str:
        parsed = urlsplit(url)
        path_parts = [part for part in parsed.path.split("/") if part]
        query = parse_qs(parsed.query)

        if path_parts and path_parts[0] != "embed":
            return path_parts[0]

        board_values = query.get("for")
        if board_values and board_values[0].strip():
            return board_values[0].strip()

        raise ValueError(f"Unable to determine Greenhouse board from {url}")
