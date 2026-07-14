from scrapers.base import JobScraper
from scrapers.base import RawJob
from scrapers.base import UnsupportedScraperError


class WorkdayScraper(JobScraper):
    def scrape(self, url: str) -> list[RawJob]:
        raise UnsupportedScraperError("Workday scraping is not implemented")
