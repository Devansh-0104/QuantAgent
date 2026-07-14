from urllib.parse import urljoin
from urllib.parse import urlsplit

from scrapers.base import JobScraper
from scrapers.base import RawJob
from scrapers.base import http_client


class PinpointScraper(JobScraper):
    def scrape(self, url: str) -> list[RawJob]:
        parsed = urlsplit(url)
        if not parsed.hostname:
            raise ValueError(f"Unable to determine Pinpoint board from {url}")
        endpoint = f"{parsed.scheme}://{parsed.netloc}/postings.json"
        response = http_client.get(endpoint, timeout=30)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ValueError("Pinpoint returned an invalid postings payload")

        jobs: list[RawJob] = []
        for resource in data:
            if not isinstance(resource, dict):
                continue
            attributes = resource.get("attributes")
            item = dict(attributes) if isinstance(attributes, dict) else dict(resource)
            item.setdefault("id", resource.get("id"))
            links = resource.get("links")
            if isinstance(links, dict):
                item.setdefault("url", links.get("self"))
            path = item.get("path") or item.get("slug")
            if not item.get("url") and isinstance(path, str):
                item["url"] = urljoin(endpoint, path)
            jobs.append(item)
        return jobs
