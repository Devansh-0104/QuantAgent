from urllib.parse import quote
from urllib.parse import urlsplit

from scrapers.base import JobScraper
from scrapers.base import RawJob
from scrapers.base import http_client


class SmartRecruitersScraper(JobScraper):
    API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"

    def scrape(self, url: str) -> list[RawJob]:
        parts = [part for part in urlsplit(url).path.split("/") if part]
        if not parts:
            raise ValueError(f"Unable to determine SmartRecruiters company from {url}")
        if parts[0].casefold() in {"company", "companies"} and len(parts) > 1:
            company = parts[1]
        else:
            company = parts[0]
        api = self.API.format(company=quote(company, safe=""))
        jobs: list[RawJob] = []
        offset = 0
        while True:
            response = http_client.get(f"{api}?limit=100&offset={offset}", timeout=30)
            response.raise_for_status()
            payload = response.json()
            content = payload.get("content") if isinstance(payload, dict) else None
            if not isinstance(content, list):
                raise ValueError("SmartRecruiters returned an invalid jobs payload")
            jobs.extend(item for item in content if isinstance(item, dict))
            offset += len(content)
            total = payload.get("totalFound") if isinstance(payload, dict) else None
            if not content or not isinstance(total, int) or offset >= total:
                break
        return jobs
