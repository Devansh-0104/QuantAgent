from pathlib import Path

import yaml

from scrapers.base import Resolver, JobScraper


class CustomResolver(Resolver):

    def __init__(self):

        path = Path("data/companies.yaml")

        if path.exists():

            with open(path) as f:

                self.data = yaml.safe_load(f)

        else:

            self.data = {}

    def resolve(self, company_name: str):

        company = self.data.get(company_name)

        if company:

            return company["website"]

        return None


class CustomScraper(JobScraper):

    def scrape(self, url: str):

        print(f"Custom scraper: {url}")

        return []