from scrapers.base import ATS

from scrapers.greenhouse import GreenhouseScraper
from scrapers.lever import LeverScraper
from scrapers.custom import CustomScraper


class ScraperFactory:

    def get(self, ats: ATS):

        if ats == ATS.GREENHOUSE:
            return GreenhouseScraper()

        if ats == ATS.LEVER:
            return LeverScraper()

        return CustomScraper()