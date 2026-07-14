from scrapers.base import JobScraper
from scrapers.base import RawJob
from urllib.parse import urljoin
from urllib.parse import urlsplit

from scrapers.base import http_client


class WorkdayScraper(JobScraper):
    def scrape(self, url: str) -> list[RawJob]:
        parsed = urlsplit(url)
        parts = [part for part in parsed.path.split("/") if part]
        if not parsed.hostname or not parts:
            raise ValueError(f"Unable to determine Workday tenant and site from {url}")
        tenant = parsed.hostname.split(".")[0]
        language_prefix = parts[0] if len(parts) > 1 and ("-" in parts[0] or parts[0].casefold() in {"en", "fr", "de", "es"}) else None
        site_index = 1 if language_prefix else 0
        if len(parts) <= site_index:
            raise ValueError(f"Unable to determine Workday site from {url}")
        site = parts[site_index]
        api = f"{parsed.scheme}://{parsed.netloc}/wday/cxs/{tenant}/{site}/jobs"
        jobs: list[RawJob] = []
        offset = 0
        while True:
            response = http_client.post(
                api,
                timeout=30,
                json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""},
            )
            response.raise_for_status()
            payload = response.json()
            postings = payload.get("jobPostings") if isinstance(payload, dict) else None
            if not isinstance(postings, list):
                raise ValueError("Workday returned an invalid jobs payload")
            for posting in postings:
                if not isinstance(posting, dict):
                    continue
                external_path = posting.get("externalPath")
                if isinstance(external_path, str):
                    posting = dict(posting)
                    posting["url"] = urljoin(f"{parsed.scheme}://{parsed.netloc}", external_path)
                jobs.append(posting)
            offset += len(postings)
            total = payload.get("total") if isinstance(payload, dict) else None
            if not postings or not isinstance(total, int) or offset >= total:
                break
        return jobs
