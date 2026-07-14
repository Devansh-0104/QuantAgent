import logging
from ipaddress import ip_address
from urllib.parse import urljoin
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import httpx
from bs4 import BeautifulSoup

from models.company import Company
from models.page import PageType
from scrapers.base import Resolver
from scrapers.base import http_client
from services.monitor import Monitor
from services.registry import Registry


logger = logging.getLogger(__name__)


KEYWORDS = {
    PageType.CAREERS: [
        "career",
        "careers",
        "join",
        "jobs",
        "work-with-us",
        "vacancies",
    ],
    PageType.STUDENTS: [
        "student",
        "students",
        "graduate",
        "intern",
        "internship",
        "campus",
        "university",
    ],
    PageType.EVENTS: [
        "event",
        "events",
        "competition",
        "hackathon",
        "program",
    ],
}


COMMON_PATHS = {
    PageType.CAREERS: [
        "/careers",
        "/career",
        "/jobs",
        "/join",
        "/join-us",
        "/careers/",
        "/jobs/",
    ],
    PageType.STUDENTS: [
        "/students",
        "/student-programs",
        "/graduate",
        "/graduates",
        "/internships",
        "/internship",
        "/campus",
    ],
    PageType.EVENTS: [
        "/events",
        "/event",
        "/programs",
        "/hackathon",
        "/competitions",
    ],
}


def normalize_http_url(base_url: str, href: str) -> str | None:
    candidate = urljoin(base_url, href.strip())
    parsed = urlsplit(candidate)

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None

    hostname = parsed.hostname.casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return None
    try:
        address = ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            return None

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


class Discovery:
    def __init__(
        self,
        resolver: Resolver,
        registry: Registry | None = None,
        monitor: Monitor | None = None,
    ) -> None:
        self.resolver = resolver
        self.registry = registry or Registry()
        self.monitor = monitor or Monitor()

    def discover(self, company: Company) -> bool:
        website = getattr(company, "website", None) or self.resolver.resolve(
            company.name
        )
        if website is None:
            logger.warning("No website resolved for %s", company.name)
            return False

        normalized_website = normalize_http_url(website, website)
        if normalized_website is None:
            logger.error("Resolver returned an invalid website for %s", company.name)
            return False

        if not self.registry.update_website(company.name, normalized_website):
            logger.error("Unable to persist website for %s", company.name)
            return False

        found: dict[str, PageType] = {}
        get_pages = getattr(self.monitor, "get_pages", None)
        existing_pages = get_pages(company.id) if callable(get_pages) else []
        if not existing_pages:
            self._probe_common_paths(normalized_website, found)
        self._discover_homepage_links(normalized_website, found)

        for url, page_type in found.items():
            self.monitor.register_page(
                company_id=company.id,
                page_type=page_type,
                url=url,
            )

        if not found:
            logger.warning("No recruiting pages discovered for %s", company.name)

        return bool(found)

    def _probe_common_paths(
        self,
        website: str,
        found: dict[str, PageType],
    ) -> None:
        for page_type, paths in COMMON_PATHS.items():
            for path in paths:
                url = normalize_http_url(website, path)
                if url is None:
                    continue

                try:
                    response = http_client.get(
                        url,
                        follow_redirects=True,
                        timeout=10,
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.debug("Common recruiting path failed: %s: %s", url, exc)
                    continue

                response_url = normalize_http_url(url, str(response.url))
                if response_url is not None:
                    found.setdefault(response_url, page_type)
                    break

    def _discover_homepage_links(
        self,
        website: str,
        found: dict[str, PageType],
    ) -> None:
        try:
            response = http_client.get(
                website,
                follow_redirects=True,
                timeout=20,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Unable to inspect homepage %s: %s", website, exc)
            return

        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup.find_all("a", href=True):
            href = tag.get("href")
            if not isinstance(href, str):
                continue

            url = normalize_http_url(website, href)
            if url is None:
                continue

            text = f"{href} {tag.get_text(strip=True)}".lower()
            for page_type, words in KEYWORDS.items():
                if any(word in text for word in words):
                    found.setdefault(url, page_type)
                    break
