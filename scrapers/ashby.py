from scrapers.base import JobScraper
from scrapers.base import RawJob
from scrapers.base import UnsupportedScraperError


class AshbyScraper(JobScraper):
    def scrape(self, url: str) -> list[RawJob]:
        raise UnsupportedScraperError("Ashby scraping is not implemented")
