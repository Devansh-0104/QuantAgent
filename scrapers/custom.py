import yaml

from app.config import DATA_DIR
from scrapers.base import JobScraper
from scrapers.base import RawJob
from scrapers.base import Resolver
from scrapers.base import UnsupportedScraperError


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

        if company:

            return company["website"]

        return None


class CustomScraper(JobScraper):

    def scrape(self, url: str) -> list[RawJob]:
        raise UnsupportedScraperError(f"No generic scraper is available for {url}")
