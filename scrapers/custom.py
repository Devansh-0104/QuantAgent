import hashlib
import json
from collections.abc import Iterator
from urllib.parse import urljoin

import yaml
from bs4 import BeautifulSoup

from app.config import DATA_DIR
from scrapers.base import JobScraper
from scrapers.base import RawJob
from scrapers.base import Resolver
from scrapers.base import http_client


class CustomResolver(Resolver):

    def __init__(self):

        path = DATA_DIR / "companies.yaml"

        if path.exists():

            with open(path, encoding="utf-8") as f:

                loaded = yaml.safe_load(f)
                self.data = loaded if isinstance(loaded, dict) else {}

        else:

            self.data = {}

    def resolve(self, company_name: str) -> str | None:

        company = self.data.get(company_name)

        if isinstance(company, dict):
            website = company.get("website")
            return website.strip() if isinstance(website, str) else None

        return None


class CustomScraper(JobScraper):

    def scrape(self, url: str) -> list[RawJob]:
        response = http_client.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        jobs = self._structured_jobs(soup, str(response.url))
        if jobs:
            return jobs
        return self._html_jobs(soup, str(response.url))

    def _structured_jobs(self, soup: BeautifulSoup, base_url: str) -> list[RawJob]:
        jobs: list[RawJob] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                payload = json.loads(script.string or script.get_text())
            except (TypeError, ValueError):
                continue
            for item in self._walk_json(payload):
                item_type = item.get("@type")
                types = item_type if isinstance(item_type, list) else [item_type]
                if not any(value in {"JobPosting", "Event"} for value in types):
                    continue
                url = self._text(item.get("url")) or base_url
                title = self._text(item.get("title")) or self._text(item.get("name"))
                if not title:
                    continue
                location = self._location(item.get("jobLocation") or item.get("location"))
                deadline = self._text(item.get("validThrough")) or self._text(item.get("endDate"))
                jobs.append(
                    {
                        "id": self._identity(url, title),
                        "title": title,
                        "description": self._text(item.get("description")),
                        "location": location,
                        "url": urljoin(base_url, url),
                        "deadline": deadline or None,
                        "kind": "event" if "Event" in types else "job",
                    }
                )
        return self._dedupe(jobs)

    def _html_jobs(self, soup: BeautifulSoup, base_url: str) -> list[RawJob]:
        jobs: list[RawJob] = []
        terms = (
            "job", "career", "opening", "position", "vacancy", "intern",
            "graduate", "event", "hackathon", "competition", "insight day",
        )
        generic_labels = {
            "career", "careers", "jobs", "join us", "open positions",
            "view jobs", "see all jobs", "search jobs", "opportunities",
        }
        for tag in soup.find_all("a", href=True):
            href = tag.get("href")
            if not isinstance(href, str):
                continue
            title = " ".join(tag.get_text(" ", strip=True).split())
            searchable = f"{href} {title}".casefold()
            if (
                not title
                or title.casefold() in generic_labels
                or title.casefold().startswith("careers at")
                or len(title) > 180
                or not any(term in searchable for term in terms)
            ):
                continue
            absolute_url = urljoin(base_url, href)
            if not absolute_url.startswith(("http://", "https://")):
                continue
            jobs.append(
                {
                    "id": self._identity(absolute_url, title),
                    "title": title,
                    "description": None,
                    "location": "",
                    "url": absolute_url,
                    "deadline": None,
                    "kind": "event" if any(term in searchable for term in ("event", "hackathon", "competition", "insight day")) else "job",
                }
            )
        return self._dedupe(jobs)

    @classmethod
    def _walk_json(cls, value: object) -> Iterator[dict[str, object]]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from cls._walk_json(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._walk_json(child)

    @classmethod
    def _location(cls, value: object) -> str:
        if isinstance(value, list):
            return "; ".join(filter(None, (cls._location(item) for item in value)))
        if not isinstance(value, dict):
            return cls._text(value)
        address = value.get("address", value)
        if isinstance(address, dict):
            return ", ".join(
                filter(None, (cls._text(address.get(key)) for key in ("addressLocality", "addressRegion", "addressCountry")))
            )
        return cls._text(address)

    @staticmethod
    def _text(value: object) -> str:
        if isinstance(value, str):
            return BeautifulSoup(value, "lxml").get_text(" ", strip=True)
        return ""

    @staticmethod
    def _identity(url: str, title: str) -> str:
        return hashlib.sha256(f"{url}\0{title}".encode()).hexdigest()

    @staticmethod
    def _dedupe(jobs: list[RawJob]) -> list[RawJob]:
        unique: dict[str, RawJob] = {}
        for job in jobs:
            identifier = str(job.get("id", ""))
            if identifier:
                unique.setdefault(identifier, job)
        return list(unique.values())
