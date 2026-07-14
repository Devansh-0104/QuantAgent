import logging
from collections.abc import Callable
from typing import TypedDict
from urllib.parse import urlsplit

from models.opportunity import OpportunityType
from scrapers.base import ATS
from scrapers.base import RawJob


logger = logging.getLogger(__name__)


class NormalizedOpportunity(TypedDict):
    company_id: int
    page_id: int
    provider_id: str
    type: OpportunityType
    title: str
    description: str | None
    location: str
    url: str
    visa: str | None
    deadline: str | None


class OpportunityNormalizer:
    def normalize(
        self,
        ats: ATS,
        company_id: int,
        page_id: int,
        jobs: list[RawJob],
    ) -> list[NormalizedOpportunity]:
        normalizers: dict[
            ATS,
            Callable[[int, int, list[RawJob]], list[NormalizedOpportunity]],
        ] = {
            ATS.GREENHOUSE: self.greenhouse,
            ATS.LEVER: self.lever,
        }
        normalizer = normalizers.get(ats)
        if normalizer is None:
            raise ValueError(f"No normalizer is implemented for {ats.value}")

        return normalizer(company_id, page_id, jobs)

    def greenhouse(
        self,
        company_id: int,
        page_id: int,
        jobs: list[RawJob],
    ) -> list[NormalizedOpportunity]:
        opportunities: list[NormalizedOpportunity] = []

        for job in jobs:
            location_value = job.get("location")
            if isinstance(location_value, dict):
                location = self._text(location_value.get("name"))
            else:
                location = self._text(location_value)

            opportunity = self._build(
                company_id=company_id,
                page_id=page_id,
                provider_id=job.get("id"),
                title=job.get("title"),
                description=job.get("content"),
                location=location,
                url=job.get("absolute_url"),
            )
            if opportunity is not None:
                opportunities.append(opportunity)

        return opportunities

    def lever(
        self,
        company_id: int,
        page_id: int,
        jobs: list[RawJob],
    ) -> list[NormalizedOpportunity]:
        opportunities: list[NormalizedOpportunity] = []

        for job in jobs:
            categories = job.get("categories")
            location = ""
            if isinstance(categories, dict):
                location = self._text(categories.get("location"))

            opportunity = self._build(
                company_id=company_id,
                page_id=page_id,
                provider_id=job.get("id"),
                title=job.get("text"),
                description=job.get("descriptionPlain"),
                location=location,
                url=job.get("hostedUrl"),
            )
            if opportunity is not None:
                opportunities.append(opportunity)

        return opportunities

    def classify(self, title: str) -> OpportunityType:
        normalized_title = title.casefold()

        if "competition" in normalized_title or "hackathon" in normalized_title:
            return OpportunityType.COMPETITION
        if "intern" in normalized_title:
            return OpportunityType.INTERNSHIP
        if "graduate" in normalized_title or "new grad" in normalized_title:
            return OpportunityType.GRADUATE
        if "event" in normalized_title or "program" in normalized_title:
            return OpportunityType.EVENT

        return OpportunityType.JOB

    def _build(
        self,
        company_id: int,
        page_id: int,
        provider_id: object,
        title: object,
        description: object,
        location: str,
        url: object,
    ) -> NormalizedOpportunity | None:
        normalized_provider_id = self._text(provider_id)
        normalized_title = self._text(title)
        normalized_description = self._text(description) or None
        normalized_url = self._text(url)

        if not normalized_provider_id:
            logger.warning("Skipping opportunity without a provider identity")
            return None
        if not normalized_title:
            logger.warning(
                "Skipping opportunity %s without a title",
                normalized_provider_id,
            )
            return None
        if not self._is_http_url(normalized_url):
            logger.warning(
                "Skipping opportunity %s with an invalid URL",
                normalized_provider_id,
            )
            return None

        return {
            "company_id": company_id,
            "page_id": page_id,
            "provider_id": normalized_provider_id,
            "type": self.classify(normalized_title),
            "title": normalized_title,
            "description": normalized_description,
            "location": location,
            "url": normalized_url,
            "visa": None,
            "deadline": None,
        }

    @staticmethod
    def _text(value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, int):
            return str(value)
        return ""

    @staticmethod
    def _is_http_url(url: str) -> bool:
        parsed = urlsplit(url)
        return (
            parsed.scheme.lower() in {"http", "https"}
            and parsed.hostname is not None
        )
