from scrapers.base import ATS
from scrapers.base import JobScraper
from scrapers.base import UnsupportedScraperError
from scrapers.greenhouse import GreenhouseScraper
from scrapers.lever import LeverScraper


class ScraperFactory:
    SCRAPERS: dict[ATS, type[JobScraper]] = {
        ATS.GREENHOUSE: GreenhouseScraper,
        ATS.LEVER: LeverScraper,
    }

    def get(self, ats: ATS) -> JobScraper:
        scraper_class = self.SCRAPERS.get(ats)
        if scraper_class is None:
            raise UnsupportedScraperError(f"No scraper is implemented for {ats.value}")

        return scraper_class()
