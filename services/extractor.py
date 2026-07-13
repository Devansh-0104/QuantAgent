import httpx

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


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

    def analyze(self, page_url: str):

        links = self._html_links(page_url)

        ats_links = self._score_links(page_url, links)

        if ats_links:
            return ats_links

        print("No ATS links in HTML. Trying browser...")

        links = self._browser_links(page_url)

        return self._score_links(page_url, links)

    def _html_links(self, url):

        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=20,
        )

        soup = BeautifulSoup(
            response.text,
            "lxml",
        )

        return [
            tag["href"]
            for tag in soup.find_all("a", href=True)
        ]

    def _browser_links(self, url):

        with sync_playwright() as p:

            browser = p.chromium.launch(headless=True)

            page = browser.new_page()

            page.goto(
                url,
                wait_until="networkidle",
                timeout=60000,
            )

            hrefs = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href)"
            )

            browser.close()

            return hrefs

    def _score_links(self, base_url, hrefs):

        scored = []

        seen = set()

        for href in hrefs:

            url = urljoin(base_url, href)

            if url in seen:
                continue

            seen.add(url)

            text = href.lower()

            score = 0

            if any(x in text for x in self.ATS_HINTS):
                score = 100

            elif "apply" in text:
                score = 90

            elif any(x in text for x in self.KEYWORDS):
                score = 60

            if score > 0:
                scored.append((score, url))

        scored.sort(reverse=True)

        return [u for _, u in scored]