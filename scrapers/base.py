from abc import ABC
from abc import abstractmethod
from enum import Enum
import logging
from time import sleep
from typing import TypeAlias

import httpx


RawJob: TypeAlias = dict[str, object]

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


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


class RetryingHTTPClient:
    def __init__(
        self,
        attempts: int = 3,
        backoff_seconds: float = 0.25,
        client: httpx.Client | None = None,
    ) -> None:
        self.attempts = max(1, attempts)
        self.backoff_seconds = max(0, backoff_seconds)
        self.client = client or httpx.Client()

    def get(
        self,
        url: str,
        *,
        timeout: float,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        last_error: httpx.HTTPError | None = None

        for attempt in range(1, self.attempts + 1):
            try:
                response = self.client.get(
                    url,
                    timeout=timeout,
                    follow_redirects=follow_redirects,
                )
                if response.status_code not in TRANSIENT_STATUS_CODES:
                    return response
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in TRANSIENT_STATUS_CODES:
                    raise
                last_error = exc
            except (
                httpx.ConnectError,
                httpx.NetworkError,
                httpx.ProtocolError,
                httpx.TimeoutException,
            ) as exc:
                last_error = exc

            if attempt == self.attempts:
                break

            logger.warning(
                "HTTP GET failed for %s; retrying attempt %s/%s",
                url,
                attempt + 1,
                self.attempts,
            )
            sleep(self.backoff_seconds * attempt)

        if last_error is not None:
            raise last_error

        raise RuntimeError(f"HTTP GET failed for {url}")


http_client = RetryingHTTPClient()
