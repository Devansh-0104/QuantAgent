from abc import ABC
from abc import abstractmethod
from enum import Enum


class ATS(Enum):

    GREENHOUSE = "GREENHOUSE"
    WORKDAY = "WORKDAY"
    LEVER = "LEVER"
    ASHBY = "ASHBY"
    SMARTRECRUITERS = "SMARTRECRUITERS"
    CUSTOM = "CUSTOM"


class Resolver(ABC):

    @abstractmethod
    def resolve(self, company_name: str) -> str | None:
        pass


class JobScraper(ABC):

    @abstractmethod
    def scrape(self, url: str):
        """
        Returns a list of Opportunity dictionaries.
        """
        pass