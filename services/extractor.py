import logging
from urllib.parse import urljoin
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


logger = logging.getLogger(__name__)


class Extractor:
    ATS_HINTS = [
        "greenhouse",
        "lever",
        "workday",
        "ashby",
        "smartrecruiters",
    ]

    KEYWORDS = [
        "apply",
        "job",
        "career",
        "opening",
        "position",
        "intern",
        "graduate",
    ]

    def analyze(self, page_url: str) -> list[str]:
        try:
            links = self._html_links(page_url)
        except httpx.HTTPError as exc:
            logger.warning("Unable to inspect static page %s: %s", page_url, exc)
            links = []

        ats_links = self._score_links(page_url, links)
        if ats_links:
            return ats_links

        logger.info("No candidate links in static HTML; trying browser extraction")
        return self._score_links(page_url, self._browser_links(page_url))

    def _html_links(self, url: str) -> list[str]:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=20,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        return [
            href
            for tag in soup.find_all("a", href=True)
            if isinstance((href := tag.get("href")), str)
        ]

    def _browser_links(self, url: str) -> list[str]:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(
                        url,
                        wait_until="networkidle",
                        timeout=60000,
                    )
                    return page.eval_on_selector_all(
                        "a[href]",
                        "els => els.map(e => e.href)",
                    )
                finally:
                    browser.close()
        except PlaywrightError as exc:
            logger.warning("Browser extraction failed for %s: %s", url, exc)
            return []

    def _score_links(self, base_url: str, hrefs: list[str]) -> list[str]:
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()

        for href in hrefs:
            url = urljoin(base_url, href)
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
                continue
            if url in seen:
                continue

            seen.add(url)
            text = href.lower()
            score = 0

            if any(hint in text for hint in self.ATS_HINTS):
                score = 100
            elif "apply" in text:
                score = 90
            elif any(keyword in text for keyword in self.KEYWORDS):
                score = 60

            if score > 0:
                scored.append((score, url))

        scored.sort(reverse=True)
        return [url for _, url in scored]
