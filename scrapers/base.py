from abc import ABC
from abc import abstractmethod
from enum import Enum
from typing import TypeAlias


RawJob: TypeAlias = dict[str, object]


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
        raise NotImplementedError


class JobScraper(ABC):

    @abstractmethod
    def scrape(self, url: str) -> list[RawJob]:
        """
        Returns a list of Opportunity dictionaries.
        """
        raise NotImplementedError


class UnsupportedScraperError(RuntimeError):
    """Raised when no production scraper exists for an ATS provider."""
